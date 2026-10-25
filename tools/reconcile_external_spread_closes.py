"""Verify the four owner-confirmed cash-outs; append only under paused timers/lock.

No order writes, cancellations, risk changes, worker starts, or secret-file reads.
Full evidence and backups remain private on the server. Never resume trading.
"""

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from kalshi.trading import TradingClient, TradingError
from live import external_spread_closes as external
from live import shared_account_risk as shared
from live.production_lock import account_lock
from tools.account_reconciliation_snapshot import (
    capture,
    read_journals,
    write_private,
    READ_PATHS,
)


def verify_cashouts(rows, confirmation):
    expected = confirmation.get("normalized_fill_sha256")
    if (
        not isinstance(expected, list)
        or not expected
        or len(set(expected)) != len(expected)
    ):
        raise TradingError("Explicit private fill confirmation required")
    observed = [external.fingerprint(row) for row in rows]
    if len(set(observed)) != len(observed) or set(observed) != set(expected):
        raise TradingError("Cash-outs do not match owner confirmation: HALT")
    fees = sum((Decimal(row["fee"]) for row in rows), Decimal(0))
    if fees != Decimal(confirmation["manual_close_fees"]):
        raise TradingError("Confirmed fees do not reconcile")


class ReadOnlyClient(TradingClient):
    def _request(self, method, path, params=None, body=None):
        if method != "GET" or path not in READ_PATHS:
            raise TradingError("Reconciliation permits account GETs only")
        return super()._request(method, path, params, body)


class FrozenAccount:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def orders(self, status):
        if status != "resting":
            raise TradingError("Unexpected account read")
        return self.snapshot["resting_orders"]

    def positions(self):
        return self.snapshot["positions"]

    def fills(self, min_ts=None):
        return self.snapshot["fills"]

    def settlements(self):
        return self.snapshot["settlements"]


def build_plan(snapshot, now, confirmation):
    if (
        snapshot.get("source") != "signed_exchange_gets"
        or snapshot.get("stable_capture") is not True
        or snapshot.get("complete_pagination") is not True
    ):
        raise TradingError("Complete signed capture required")
    journals = deepcopy(snapshot["journals"])
    owner = shared.ownership(journals)
    spread_events = journals["spread"]
    approved = external.approved(spread_events, snapshot["fills"], now)
    candidates = []
    for fill in snapshot["fills"]:
        if str(fill.get("order_id")) in owner["orders"]:
            continue
        if external.recognized(fill, approved):
            continue
        ticker = fill.get("ticker") or fill.get("market_ticker")
        if owner["tickers"].get(ticker) != "spread":
            raise TradingError("Other external activity requires separate review")
        candidates.append(fill)
    # Each signed fill identity must be unique in this complete capture.
    if len({external.normalize(fill)["fid"] for fill in candidates}) != len(candidates):
        raise TradingError("Duplicate external candidates: HALT")
    combined = list(approved.values()) + [
        external.normalize(fill) for fill in candidates
    ]
    verify_cashouts(combined, confirmation)
    snapshot_hash = external.fingerprint(snapshot)
    additions = [
        {
            "event": "external_close",
            "utc": now.isoformat(),
            "reason": "owner_manual_cashout",
            "evidence": external.EVIDENCE,
            "fill": fill,
            "fill_sha256": external.fingerprint(fill),
            "snapshot_sha256": snapshot_hash,
        }
        for fill in candidates
    ]
    spread_events.extend(additions)
    ledger = shared.spread_ledger(
        spread_events, snapshot["fills"], snapshot["settlements"], now
    )
    # Independent reconciliation of the full spread sample, including precise fees.
    if abs(
        Decimal(str(ledger["cumulative"]))
        - Decimal(confirmation["expected_spread_net"])
    ) > Decimal(".00005"):
        raise TradingError(
            "Full spread ledger does not reconcile to verified economics"
        )
    prior_reader = shared.journal_events
    try:
        shared.journal_events = lambda sport: journals.get(sport)
        _, context = shared.state_for(FrozenAccount(snapshot), "spread", now)
    finally:
        shared.journal_events = prior_reader
    if context["account_pnl"].get("unavailable"):
        raise TradingError("Account-wide accounting remains unavailable")
    return {
        "events_to_append": additions,
        "snapshot_sha256": snapshot_hash,
        "journal_sha256": snapshot["journal_sha256"],
        "spread_net": ledger["cumulative"],
        "manual_close_fees": str(
            sum((Decimal(r["fee"]) for r in combined), Decimal(0))
        ),
        "account_pnl": context["account_pnl"],
        "positions_verified": True,
        "candidate_count": len(additions),
        "safe_to_resume": False,
        "trading_actions": 0,
    }


def quiet_capture(client, root):
    snapshot = capture(client, root)
    if snapshot["resting_orders"]:
        raise TradingError("Resting orders must be absent before repair")
    return snapshot


def require_paused():
    for sport in ("nba", "nfl", "spread"):
        for kind in ("timer", "service"):
            unit = f"market-maker-prod-{sport}-auto.{kind}"
            result = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if result.stdout.strip() not in ("inactive", "failed", "unknown"):
                raise TradingError("All production workers and timers must be paused")


def append_verified(root, plan, evidence_dir):
    if not plan["events_to_append"]:
        return None
    _, hashes = read_journals(root)
    if hashes != plan["journal_sha256"]:
        raise TradingError("Journal changed before append: HALT")
    journal = root / "prod-spread-auto/journal.jsonl"
    backup = evidence_dir / ("spread-journal-before-" + uuid.uuid4().hex + ".jsonl")
    data = journal.read_bytes()
    fd = os.open(
        backup,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if hashlib.sha256(backup.read_bytes()).hexdigest() != hashes["spread"]:
        raise TradingError("Journal backup verification failed")
    payload = "".join(
        json.dumps(e, sort_keys=True) + "\n" for e in plan["events_to_append"]
    ).encode()
    with journal.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if journal.read_bytes() != data + payload:
        raise TradingError("Journal append verification failed; retain backup")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply"))
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("/home/trader"))
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        confirmation = json.loads(args.confirmation.read_text())
        if args.confirmation.stat().st_mode & 0o077:
            raise TradingError("Confirmation must be private")
        if not args.evidence_dir.is_dir() or args.evidence_dir.stat().st_mode & 0o077:
            raise TradingError("Private existing evidence directory required")
        if args.action == "plan":
            if args.snapshot is None:
                raise TradingError("Snapshot required")
            plan = build_plan(
                json.loads(args.snapshot.read_text()), datetime.now(UTC), confirmation
            )
        else:
            require_paused()
            client = ReadOnlyClient(dry_run=True, env="prod")
            if not client.can_sign:
                raise TradingError("Signed-read credentials unavailable")
            with account_lock():
                require_paused()
                snapshot = quiet_capture(client, args.root)
                plan = build_plan(snapshot, datetime.now(UTC), confirmation)
                write_private(
                    args.evidence_dir
                    / ("fresh-snapshot-" + uuid.uuid4().hex + ".json"),
                    snapshot,
                )
                write_private(
                    args.evidence_dir / ("verified-plan-" + uuid.uuid4().hex + ".json"),
                    plan,
                )
                append_verified(args.root, plan, args.evidence_dir)
                after = quiet_capture(client, args.root)
                write_private(
                    args.evidence_dir / ("post-snapshot-" + uuid.uuid4().hex + ".json"),
                    after,
                )
                verified = build_plan(after, datetime.now(UTC), confirmation)
                if verified["events_to_append"]:
                    raise TradingError("Repair not idempotent")
        write_private(
            args.evidence_dir / ("result-" + uuid.uuid4().hex + ".json"), plan
        )
        print(
            json.dumps(
                {
                    "status": "PLAN_VERIFIED"
                    if args.action == "plan"
                    else "RECONCILIATION_APPLIED",
                    "manual_fills": len(confirmation["normalized_fill_sha256"]),
                    "events_to_append": plan["candidate_count"],
                    "positions_verified": True,
                    "spread_net": plan["spread_net"],
                    "manual_close_fees": plan["manual_close_fees"],
                    "safe_to_resume": False,
                    "trading_actions": 0,
                }
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "HALTED",
                    "reason_class": type(error).__name__,
                    "safe_to_resume": False,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
