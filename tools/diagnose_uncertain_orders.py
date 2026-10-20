"""Read-only evidence for an uncertain production submission.

This cannot resolve an ambiguous order or authorize restarting live trading.
It never sends exchange writes, changes journals, or exposes order identifiers.
Launch via the protected production EnvironmentFile under systemd-run.
"""

import json
from datetime import datetime
import math
from pathlib import Path

from live.account_dashboard import ReadOnlyClient
from live.shared_account_risk import journal_events

ROOT = Path("/home/trader")


def numeric_quantity(position):
    raw = position.get("position_fp", position.get("position"))
    if raw is None:
        raise ValueError("position_quantity_unavailable")
    n = float(raw)
    if not math.isfinite(n):
        raise ValueError("position_quantity_nonfinite")
    return n


def inspect(events, orders, fills, positions):
    """Require exact client-order identity; ticker presence is only a warning."""
    if not all(isinstance(items, list) for items in (orders, fills, positions)):
        raise ValueError("unavailable_exchange_collection")
    intents = {
        e.get("client_order_id"): e
        for e in events
        if e.get("event") == "intent" and e.get("client_order_id")
    }
    uncertain = [e for e in events if e.get("event") == "unknown_outcome"]
    prior_acceptances = {
        e.get("client_order_id") for e in events if e.get("event") == "accepted"
    }
    reports = []
    for item in uncertain:
        cid = item.get("client_order_id")
        attempt = intents.get(cid)
        if not cid or not attempt:
            raise ValueError("unmatched_uncertain_journal_entry")
        ticker = attempt.get("ticker")
        exact = [o for o in orders if o.get("client_order_id") == cid]
        if len(exact) == 1 and exact[0].get("ticker") != ticker:
            classification = "EXACT_ID_BUT_TICKER_MISMATCH_HALT"
        elif len(exact) == 1 and exact[0].get("order_id"):
            classification = "EXACT_EXCHANGE_ORDER_FOUND_KEEP_HALTED_FOR_REPAIR"
        elif exact:
            classification = "DUPLICATE_OR_INCOMPLETE_EXCHANGE_MATCH_HALT"
        else:
            classification = "NO_EXACT_MATCH_NOT_PROOF_OF_REJECTION"
        exact_ids = {str(o.get("order_id")) for o in exact if o.get("order_id")}
        same_ticker_fills = [
            f for f in fills if (f.get("ticker") or f.get("market_ticker")) == ticker
        ]
        held_qty = [
            numeric_quantity(p)
            for p in positions
            if (p.get("ticker") or p.get("market_ticker")) == ticker
        ]
        reports.append(
            {
                "classification": classification,
                "journal_error_type": item.get("type", "unknown"),
                "attempt_utc": attempt.get("utc"),
                "exchange_exact_matches": len(exact),
                "exchange_status": str(exact[0].get("status", "unknown"))
                if len(exact) == 1
                else None,
                "exact_order_fill_records": sum(
                    str(f.get("order_id")) in exact_ids for f in fills
                ),
                "same_ticker_fill_records": len(same_ticker_fills),
                "same_ticker_nonzero_position_records": sum(
                    abs(n) > 1e-9 for n in held_qty
                ),
                "already_accepted_in_journal": cid in prior_acceptances,
            }
        )
    return reports


def collect(client, journals):
    unknowns = [
        e
        for group in journals.values()
        for e in group
        if e.get("event") == "unknown_outcome"
    ]
    if not unknowns:
        return {
            "status": "NO_UNKNOWN_OUTCOME_EVENT",
            "ready_to_trade": False,
            "cases": [],
        }
    times = [
        datetime.fromisoformat(e["utc"]).timestamp()
        for group in journals.values()
        for e in group
        if e.get("event") == "intent"
    ]
    if not times:
        raise ValueError("missing_submission_time")
    # Orders: all statuses, not merely resting. An accepted order might
    # have already expired, filled, or canceled.
    orders = client.pages("/portfolio/orders", "orders")
    fills = client.pages("/portfolio/fills", "fills", min_ts=int(min(times)) - 60)
    positions = client.pages("/portfolio/positions", "market_positions")
    cases = []
    for sport, events in journals.items():
        for row in inspect(events, orders, fills, positions):
            cases.append({"cohort": sport, **row})
    return {
        "status": "MANUAL_RECONCILIATION_REQUIRED",
        "ready_to_trade": False,
        "exchange_reads": "SIGNED_GET_ONLY",
        "exchange_orders_count": len(orders),
        "exchange_fills_count": len(fills),
        "cases": cases,
        "note": "No order or key identifiers included. No journal or exchange writes. Even no exact match does not prove an order was rejected.",
    }


def main():
    try:
        journals = {sport: journal_events(sport) for sport in ("nfl", "nba")}
        client = ReadOnlyClient()
        print(json.dumps(collect(client, journals), indent=2, sort_keys=True))
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "AUDIT_FAILED_LEAVE_BOTH_TIMERS_STOPPED",
                    "ready_to_trade": False,
                    "reason_type": type(error).__name__,
                }
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
