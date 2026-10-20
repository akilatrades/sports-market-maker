"""Recover an explicitly rejected NBA shard-3 POST without touching Kalshi funds.

GET-only verification of all order statuses/fills/positions. The optional
reconciliation appends one event to the NBA journal after checking that both
production workers are paused. It never sends orders, transfers, cancels,
changes risk caps, or enables live timers.
"""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kalshi.shard_funding import shard_balance, verify_market_shard
from kalshi.trading import TradingError
from live.account_dashboard import ReadOnlyClient
from live.prod_nba_auto import write_event
from live.reconciled_attempts import rejected_client_ids
from live.shared_account_risk import journal_events
from tools.reconcile_rejected_nba import ensure_paused

NBA_JOURNAL = Path("/home/trader/prod-nba-auto/journal.jsonl")
BACKUP = Path("/home/trader/prod-nba-auto/journal.before-shard-recovery.20261020.jsonl")


def case_to_reconcile(events, now):
    resolved = rejected_client_ids(events)
    unknowns = [
        e
        for e in events
        if e.get("event") == "unknown_outcome"
        and e.get("client_order_id") not in resolved
    ]
    if len(unknowns) != 1 or unknowns[0].get("type") != "TradingError":
        raise TradingError("Expected exactly one remaining TradingError submission")
    cid = unknowns[0].get("client_order_id")
    intents = [
        e
        for e in events
        if e.get("event") == "intent" and e.get("client_order_id") == cid
    ]
    if len(intents) != 1 or any(
        e.get("event") == "accepted" and e.get("client_order_id") == cid for e in events
    ):
        raise TradingError("Submitted order has unknown/accepted journal identity")
    submitted = datetime.fromisoformat(intents[0]["utc"])
    if submitted.tzinfo is None or not (
        timedelta(minutes=1) <= now - submitted <= timedelta(days=2)
    ):
        raise TradingError("Rejected submission timestamp outside incident window")
    return cid, intents[0]


def verify(client, nba_events, nfl_events, now):
    if any(
        e.get("event") == "unknown_outcome"
        and e.get("client_order_id") not in rejected_client_ids(nfl_events)
        for e in nfl_events
    ):
        raise TradingError("Unresolved separate NFL submission")
    cid, attempt = case_to_reconcile(nba_events, now)
    ticker = attempt["ticker"]
    # Fresh public market provides the authoritative exchange_index.
    market = client._request("GET", f"/markets/{ticker}")
    index = verify_market_shard(market)
    if market["market"].get("ticker") != ticker or index != 3:
        raise TradingError("Basketball market shard is not the expected index 3")
    balance = client._request("GET", "/portfolio/balance")
    available = shard_balance(balance, index)
    # All-status authenticated orders, not just resting.
    orders = client.pages("/portfolio/orders", "orders")
    since = min(
        datetime.fromisoformat(e["utc"]).timestamp()
        for e in nfl_events + nba_events
        if e.get("event") == "intent"
    )
    fills = client.pages("/portfolio/fills", "fills", min_ts=int(since) - 60)
    positions = client.pages("/portfolio/positions", "market_positions")
    if any(
        o.get("client_order_id") == cid or o.get("ticker") == ticker for o in orders
    ):
        raise TradingError("Matching historical exchange order exists")
    if any((f.get("ticker") or f.get("market_ticker")) == ticker for f in fills):
        raise TradingError("Matching exchange fill exists")
    if any((p.get("ticker") or p.get("market_ticker")) == ticker for p in positions):
        raise TradingError("Matching exchange position exists")
    return cid, {
        "market_exchange_index": index,
        "shard_available_dollars": str(available),
        "shard_funded_for_max_3_dollar_order": available >= 3.30,
        "account_order_and_fill_match": False,
        "route": "explicit_exchange_index_3",
    }


def reconcile(client, now=None):
    now = now or datetime.now(UTC)
    ensure_paused()
    if client.env != "prod" or not client.can_sign:
        raise TradingError("Production signed GET read required")
    nfl_events = journal_events("nfl")
    nba_events = journal_events("nba")
    cid, report = verify(client, nba_events, nfl_events, now)
    ensure_paused()
    if journal_events("nba") != nba_events:
        raise TradingError("NBA journal changed during validation")
    # Never erase original events or budgets. Preserve an immutable local
    # incident backup before appending an explanatory resolution.
    import os

    if BACKUP.exists():
        raise TradingError("Incident backup already exists; do not overwrite")
    descriptor = os.open(BACKUP, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as out:
            out.write(NBA_JOURNAL.read_bytes())
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        raise
    write_event(
        NBA_JOURNAL,
        {
            "event": "reconciled_rejected",
            "utc": now.isoformat(),
            "client_order_id": cid,
            "evidence": "signed_get_no_order_fill_position_and_explicit_shard_404",
            "submission_http_status": 404,
            "resolution": "exchange_insufficient_shard_balance",
        },
    )
    return {
        "status": "SHARD_404_RECONCILED_BOTH_TIMERS_STILL_OFF",
        "original_attempt_still_counts_against_budget": True,
        **report,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-shard-404", action="store_true")
    args = parser.parse_args()
    if not args.confirm_shard_404:
        parser.error(
            "Owner must confirm the original HTTP 404 insufficient_shard_balance"
        )
    try:
        print(json.dumps(reconcile(ReadOnlyClient()), sort_keys=True, indent=2))
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "SHARD_RECONCILIATION_REFUSED_KEEP_TIMERS_STOPPED",
                    "reason_type": type(error).__name__,
                }
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
