"""Owner-confirmed, fail-closed repair of a single known API-404 NBA submission.

The only exchange requests are signed GETs. Does not arm timers, place/cancel
orders, reset limits, replace journals, or replay the original client order ID.
A terminal operator must explicitly confirm Kalshi UI history is empty for
that submission AND independently have seen the original order POST's 404.
"""

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kalshi.trading import TradingError
from live.account_dashboard import ReadOnlyClient
from live.prod_nba_auto import write_event
from live.reconciled_attempts import rejected_client_ids
from live.shared_account_risk import journal_events

JOURNAL = Path("/home/trader/prod-nba-auto/journal.jsonl")
TIMERS = (
    "market-maker-prod-nfl-auto.timer",
    "market-maker-prod-nba-auto.timer",
)
SERVICES = (
    "market-maker-prod-nfl-auto.service",
    "market-maker-prod-nba-auto.service",
)


def ensure_paused():
    for unit in (*TIMERS, *SERVICES):
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            check=False,
            timeout=6,
            capture_output=True,
        )
        # 3: inactive/failed, 4: absent. Unexpected responses fail closed.
        if result.returncode not in (3, 4):
            raise TradingError("Workers or timers active or status uncertain: HALT")


def verify(events, orders, fills, positions, now):
    """Reject only after full signed account evidence, never from a 404 alone."""
    if not all(isinstance(rows, list) for rows in (orders, fills, positions)):
        raise TradingError("Unverified exchange response: HALT")
    if rejected_client_ids(events):
        raise TradingError("Rejected order already reconciled")
    intents = [e for e in events if e.get("event") == "intent"]
    unknowns = [e for e in events if e.get("event") == "unknown_outcome"]
    accept_ids = {
        e.get("client_order_id") for e in events if e.get("event") == "accepted"
    }
    if len(unknowns) != 1:
        raise TradingError("Exactly one unknown NBA submission required: HALT")
    case = unknowns[0]
    cid = case.get("client_order_id")
    matches = [e for e in intents if e.get("client_order_id") == cid]
    if len(matches) != 1 or cid in accept_ids or case.get("type") != "TradingError":
        raise TradingError("Unknown outcome is not the audited API-404 case")
    intent = matches[0]
    created = datetime.fromisoformat(intent["utc"])
    if created.tzinfo is None or not (
        timedelta(minutes=10) <= now - created <= timedelta(days=2)
    ):
        raise TradingError("Submission timestamp not within reviewed window")
    ticker = intent.get("ticker")
    if not ticker:
        raise TradingError("Missing journal ticker")
    # An order with any status might have existed and expired immediately.
    # Check both client id and ticker; unknown alternate order is a veto.
    if any(
        o.get("client_order_id") == cid or o.get("ticker") == ticker for o in orders
    ):
        raise TradingError("Matching exchange order exists: HALT")
    if any(
        f.get("order_id") == cid
        or (f.get("ticker") or f.get("market_ticker")) == ticker
        for f in fills
    ):
        raise TradingError("Possible exchange fill exists: HALT")
    if any(
        (p.get("ticker") or p.get("market_ticker")) == ticker
        and float(p.get("position_fp", p.get("position", "nan"))) != 0
        for p in positions
    ):
        raise TradingError("Possible open position exists: HALT")
    return cid


def reconcile(client, now=None):
    now = now or datetime.now(UTC)
    ensure_paused()
    if (
        os.environ.get("KALSHI_ENV") != "prod"
        or client.env != "prod"
        or not client.can_sign
    ):
        raise TradingError("Signed production GET access required")
    if client.base != "https://external-api.kalshi.com":
        raise TradingError("Expected documented production host not deployed")
    nfl = journal_events("nfl")
    nba = journal_events("nba")
    if any(e.get("event") == "unknown_outcome" for e in nfl):
        raise TradingError("Separate NFL ambiguity: HALT")
    times = [
        datetime.fromisoformat(e["utc"]).timestamp()
        for e in nfl + nba
        if e.get("event") == "intent"
    ]
    if not times:
        raise TradingError("Missing attempt history")
    orders = client.pages("/portfolio/orders", "orders")
    fills = client.pages("/portfolio/fills", "fills", min_ts=int(min(times)) - 60)
    positions = client.pages("/portfolio/positions", "market_positions")
    cid = verify(nba, orders, fills, positions, now)
    # Re-read journal and timer state immediately before an irreversible
    # local append. No other process is permitted to alter it while paused.
    ensure_paused()
    if journal_events("nba") != nba:
        raise TradingError("Journal changed during audit: HALT")
    write_event(
        JOURNAL,
        {
            "event": "reconciled_rejected",
            "utc": now.isoformat(),
            "client_order_id": cid,
            "evidence": "signed_get_no_order_fill_position_and_owner_ui",
            "submission_http_status": 404,
            "resolution": "manual_owner_confirmed_old_host_404",
        },
    )
    return {
        "status": "REJECTED_ATTEMPT_RECONCILED_JOURNAL_APPEND_ONLY",
        "trading_timers": "remain_stopped",
        "exchange_writes": 0,
        "repaired_cases": 1,
        "retained_cumulative_attempt_cost": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-kalshi-ui-empty", action="store_true")
    parser.add_argument("--confirm-original-post-http-404", action="store_true")
    args = parser.parse_args()
    if not args.confirm_kalshi_ui_empty or not args.confirm_original_post_http_404:
        parser.error("Both explicit owner evidence confirmations are required.")
    try:
        result = reconcile(ReadOnlyClient())
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "RECONCILIATION_REFUSED_TIMERS_MUST_REMAIN_STOPPED",
                    "reason_type": type(error).__name__,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
