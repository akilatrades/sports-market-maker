"""Read-only Kalshi production-account isolation report for NFL -> NBA handoff.

Shows AGGREGATE counts only (no ticker, order IDs, balances, keys or raw responses).
No order submissions, cancellations or service changes. Must run with the
protected production EnvironmentFile through systemd-run (see project audit).
"""
import json
import math
from collections import Counter
from pathlib import Path

from kalshi.trading import TradingClient, TradingError

ROOT = Path("/home/trader")


class StrictGetClient(TradingClient):
    def _request(self, method, path, params=None, body=None):
        if method != "GET":
            raise TradingError("Isolation audit allows GET only")
        return super()._request(method, path, params=params, body=body)


def journal(path):
    if not path.exists():
        raise ValueError("missing_cohort_journal")
    data = path.read_text()
    if data and not data.endswith("\n"):
        raise ValueError("journal_write_in_progress")
    events = [json.loads(s) for s in data.splitlines() if s.strip()]
    intents = {
        e.get("client_order_id"): e.get("ticker")
        for e in events
        if e.get("event") == "intent" and e.get("client_order_id")
    }
    orders = {
        e.get("order_id"): intents.get(e.get("client_order_id"))
        for e in events
        if e.get("event") == "accepted" and e.get("order_id")
    }
    return {
        "tickers": {v for v in orders.values() if v},
        "orders": {k for k, v in orders.items() if v},
        "accepted_orders": len(orders),
    }


def classify(positions, resting, nfl, nba):
    if not isinstance(positions, list) or not isinstance(resting, list):
        raise ValueError("invalid_exchange_account_collections")
    groups = {"nfl": Counter(), "nba": Counter(), "other": Counter()}
    for p in positions:
        if not isinstance(p, dict):
            raise ValueError("invalid_market_position")
        raw = p.get("position_fp")
        if raw is None:
            raw = p.get("position")
        try:
            qty = float(raw)
        except (TypeError, ValueError) as error:
            raise ValueError("unparseable_exchange_position") from error
        if not math.isfinite(qty):
            raise ValueError("unparseable_exchange_position")
        if abs(qty) < 1e-10:
            continue
        ticker = p.get("market_ticker") or p.get("ticker")
        if ticker in nba["tickers"]:
            label = "nba"
        elif ticker in nfl["tickers"]:
            label = "nfl"
        else:
            label = "other"
        groups[label]["held_markets"] += 1
        groups[label]["absolute_contracts"] += abs(qty)
    for r in resting:
        if not isinstance(r, dict):
            raise ValueError("invalid_resting_order")
        oid = r.get("order_id")
        if oid in nba["orders"]:
            label = "nba"
        elif oid in nfl["orders"]:
            label = "nfl"
        else:
            label = "other"
        groups[label]["resting_orders"] += 1
    return {
        "status": (
            "ACCOUNT_HAS_RISK_DO_NOT_ACTIVATE_NBA"
            if any(sum(groups[g].values()) for g in groups)
            else "NO_RESTING_ORDERS_OR_POSITIONS_AT_THIS_INSTANT"
        ),
        "nfl": dict(groups["nfl"]),
        "nba": dict(groups["nba"]),
        "other_or_unrecognized": dict(groups["other"]),
        "nba_known_accepted_orders": nba["accepted_orders"],
        "nfl_known_accepted_orders": nfl["accepted_orders"],
        "note": (
            "Aggregates only. A matching NFL journal ticker is consistent "
            "with NFL ownership but does not independently prove order/fill "
            "identity. Exchange state can change after this GET. "
            "Do not disable safeguards based on this report."
        ),
    }


def main():
    try:
        nfl = journal(ROOT / "prod-nfl-auto" / "journal.jsonl")
        nba = journal(ROOT / "prod-nba-auto" / "journal.jsonl")
        client = StrictGetClient(dry_run=True, env="prod")
        if not client.can_sign:
            raise ValueError("signed_read_access_unavailable")
        report = classify(client.positions(), client.orders("resting"), nfl, nba)
        print(json.dumps(report, indent=2, sort_keys=True))
    except Exception as error:
        # No raw Kalshi HTTP response/body or account identifiers in output.
        print(json.dumps({
            "status": "AUDIT_UNAVAILABLE_DO_NOT_ACTIVATE",
            "reason_type": type(error).__name__,
        }))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
