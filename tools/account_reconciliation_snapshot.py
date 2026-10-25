"""Private signed account capture and ownership review. No trading/journal writes."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

READ_PATHS = {"/portfolio/orders": "orders", "/portfolio/positions": "market_positions", "/portfolio/fills": "fills", "/portfolio/settlements": "settlements"}


class ReconciliationError(ValueError):
    pass


def instant(value):
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise ReconciliationError("Timezone required")
    return at


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_journals(root):
    events, hashes = {}, {}
    for cohort in ("nba", "nfl", "spread"):
        raw = (root / f"prod-{cohort}-auto" / "journal.jsonl").read_bytes()
        if len(raw) > 50_000_000 or (raw and not raw.endswith(b"\n")):
            raise ReconciliationError("Incomplete or oversized journal")
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            raise ReconciliationError("Malformed journal")
        events[cohort], hashes[cohort] = rows, hashlib.sha256(raw).hexdigest()
    return events, hashes


def pages(client, path, **params):
    rows, seen, cursor = [], set(), ""
    for _ in range(100):
        data = client._request("GET", path, {**params, "limit": 200, **({"cursor": cursor} if cursor else {})})
        batch = data.get(READ_PATHS[path])
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise ReconciliationError("Incomplete account listing")
        rows.extend(batch)
        cursor = data.get("cursor") or ""
        if not cursor:
            return rows
        if not isinstance(cursor, str) or cursor in seen:
            raise ReconciliationError("Invalid pagination")
        seen.add(cursor)
    raise ReconciliationError("Account listing exceeds page bound")


def capture(client, root, now=None):
    started = now or datetime.now(UTC)
    events, hashes = read_journals(root)
    intents = [e for rows in events.values() for e in rows if e.get("event") == "intent"]
    if not intents:
        raise ReconciliationError("No production intents")
    since = min(instant(e["utc"]) for e in intents) - timedelta(minutes=1)
    before_positions = pages(client, "/portfolio/positions")
    before_orders = pages(client, "/portfolio/orders", status="resting")
    fills = pages(client, "/portfolio/fills", min_ts=int(since.timestamp()))
    settlements = pages(client, "/portfolio/settlements", min_ts=int(since.timestamp()))
    orders = pages(client, "/portfolio/orders", status="resting")
    positions = pages(client, "/portfolio/positions")
    _, after_hashes = read_journals(root)
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    if hashes != after_hashes or canonical(positions) != canonical(before_positions) or canonical(orders) != canonical(before_orders):
        raise ReconciliationError("Account or journal changed during capture")
    return {"schema_version": 1, "source": "signed_exchange_gets", "started_utc": started.isoformat(),
            "finished_utc": (now or datetime.now(UTC)).isoformat(), "history_since_utc": since.isoformat(),
            "journal_sha256": hashes, "journals": events, "positions": positions,
            "resting_orders": orders, "fills": fills, "settlements": settlements,
            "complete_pagination": True, "stable_capture": True, "trading_actions": 0}


def plan(snapshot, now):
    if snapshot.get("source") != "signed_exchange_gets" or snapshot.get("complete_pagination") is not True or snapshot.get("stable_capture") is not True:
        raise ReconciliationError("Complete stable signed capture required")
    started, finished = instant(snapshot["started_utc"]), instant(snapshot["finished_utc"])
    if not started <= finished <= now or (now-started).total_seconds() > 300:
        raise ReconciliationError("Stale or invalid capture")
    owned_orders, owned_tickers = {}, {}
    for cohort, events in snapshot["journals"].items():
        intents = {e["client_order_id"]: e for e in events if e.get("event") == "intent"}
        for event in events:
            if event.get("event") != "accepted":
                continue
            intent = intents.get(event.get("client_order_id"))
            oid = str(event.get("order_id") or "")
            if not intent or not oid or oid in owned_orders:
                raise ReconciliationError("Invalid accepted ownership")
            ticker = intent["ticker"]
            if ticker in owned_tickers and owned_tickers[ticker] != cohort:
                raise ReconciliationError("Overlapping ownership")
            owned_orders[oid], owned_tickers[ticker] = cohort, cohort
    candidates, unrelated, seen = [], [], {}
    for fill in snapshot["fills"]:
        fid = str(fill.get("fill_id") or fill.get("trade_id") or "")
        oid = str(fill.get("order_id") or "")
        ticker = fill.get("ticker") or fill.get("market_ticker")
        if not fid or not oid or not ticker:
            raise ReconciliationError("Fill lacks exchange identity")
        if fid in seen:
            if digest(fill) != seen[fid]:
                raise ReconciliationError("Conflicting duplicate fill")
            continue
        seen[fid] = digest(fill)
        if oid in owned_orders:
            continue
        record = {"fill_id": fid, "order_id": oid, "ticker": ticker, "fill_sha256": digest(fill),
                  "raw_fill": fill, "classification": "unrecognized_fill_requires_review"}
        (candidates if ticker in owned_tickers else unrelated).append(record)
    return {"snapshot_sha256": digest(snapshot), "status": "review_required",
            "candidate_external_fills": candidates, "other_external_fills": unrelated,
            "unowned_resting_orders": [r for r in snapshot["resting_orders"] if str(r.get("order_id")) not in owned_orders],
            "positions_verified": False, "economic_replay_verified": False,
            "safe_to_resume": False, "journal_changes": 0, "trading_actions": 0}


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "plan"))
    parser.add_argument("--root", type=Path, default=Path("/home/trader"))
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "capture":
            from kalshi.trading import TradingClient, TradingError

            class ReadOnlyClient(TradingClient):
                def _request(self, method, path, params=None, body=None):
                    if method != "GET" or path not in READ_PATHS:
                        raise TradingError("Account snapshot GET allowlist only")
                    return super()._request(method, path, params, body)

            client = ReadOnlyClient(dry_run=True, env="prod")
            if not client.can_sign:
                raise ReconciliationError("Server credentials unavailable")
            result = capture(client, args.root)
        else:
            if args.snapshot is None:
                raise ReconciliationError("Snapshot required")
            result = plan(json.loads(args.snapshot.read_text()), datetime.now(UTC))
        write_private(args.out, result)
        print(json.dumps({"status": "private_report_written", "trading_actions": 0, "journal_changes": 0, "safe_to_resume": False}))
    except Exception as error:
        print(json.dumps({"status": "unavailable", "reason_class": type(error).__name__, "safe_to_resume": False}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
