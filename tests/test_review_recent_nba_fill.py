"""The NBA first-fill audit must not expose trading identities in CI logs."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tools.review_recent_nba_fill import read_events, summarize


NOW = datetime(2026, 10, 21, 3, 35, tzinfo=UTC)
CID = "private-cid-not-for-GitHub"
OID = "private-order-id"
TICKER = "KXNBAPTS-private-ticker"


def fixture(first_filled=True, fresh=True):
    posted = NOW - timedelta(hours=3)
    fill = NOW - timedelta(hours=2, minutes=10)
    tip = NOW + timedelta(hours=1, minutes=30)
    events = [
        {
            "event": "intent",
            "utc": posted.isoformat(),
            "client_order_id": CID,
            "ticker": TICKER,
            "cost": 1.02,
            "count": 2,
            "price_cents": 51,
            "game_id": "secret-game-id",
            "tip_utc": tip.isoformat(),
            "expiration_ts": int(tip.timestamp()),
            "net_edge_after_fee_bound": 0.054,
            "probability_source": "sportsbook",
            "book_n": 3,
            "model_generated_utc": (posted - timedelta(minutes=28)).isoformat(),
        },
        {
            "event": "accepted",
            "client_order_id": CID,
            "order_id": OID,
            "utc": (posted + timedelta(seconds=3)).isoformat(),
        },
    ]
    rows = []
    if first_filled:
        rows.append(
            {
                "order_id": OID,
                "ticker": TICKER,
                "submitted_utc": posted.isoformat(),
                "first_fill_utc": fill.isoformat(),
                "state": "fully_filled",
                "exchange_status": "executed",
                "filled_contracts": 2.0,
                "ordered_contracts": 2,
                "vwap_no_price_dollars": 0.51,
                "fill_fees_dollars": 0.0,
                "maker_filled_contracts": 2,
                "queue_ahead_initial": 7,
                "queue_ahead_latest": 0,
            }
        )
    return (
        {
            "status": "ok",
            "updated_utc": (
                NOW - timedelta(minutes=1 if fresh else 12)
            ).isoformat(),
            "account": {"cash_dollars": 1000000, "equity_dollars": 999999},
            "order_audit": {
                "nba": {
                    "status": "verified_snapshot",
                    "orders": rows,
                    "accepted_orders": 1,
                    "fill_records": 1 if first_filled else 0,
                    "unknown_or_unreconciled": 0,
                }
            },
            "live_pnl": {
                "nba": {
                    "status": "verified",
                    "settled_markets": 0,
                    "settled_profit_dollars": None,
                }
            },
            "nba_validation": {"status": "collecting_live_outcomes"},
        },
        events,
    )


def test_trade_is_correlated_to_journal_without_exposing_identities():
    snap, events = fixture()
    data = summarize(snap, events, NOW)
    assert data["exchange_nba_filled_orders"] == 1
    r = data["latest_fills"][0]
    assert r["filled_contracts"] == 2
    assert r["maker_classification"] == "all_maker"
    assert r["exchange_expiry_matches_scheduled_tip"] is True
    assert r["model_estimated_net_edge_cents_at_post"] == 5.4
    assert r["sportsbook_count_at_post"] == 3
    assert r["lineup_confirmation_at_post"] == "not_recorded_in_original_intent"
    assert r["projected_minutes_at_post"] == "not_recorded_in_original_intent"
    safe = json.dumps(data)
    for forbidden in (OID, CID, TICKER, "secret-game-id", "equity_dollars", "999999"):
        assert forbidden not in safe


def test_stale_snapshot_must_not_be_reported_as_exchange_verified():
    snap, events = fixture(fresh=False)
    with pytest.raises(ValueError, match="stale"):
        summarize(snap, events, NOW)


def test_no_fill_is_not_inferred_profitable():
    snap, events = fixture(first_filled=False)
    out = summarize(snap, events, NOW)
    assert out["no_filled_owned_orders"]
    assert out["latest_fills"] == []
    assert out["cohort_realized_pnl"]["total_net_dollars"] is None


def test_unknown_exchange_fill_owner_is_rejected():
    snap, events = fixture()
    events.pop()
    with pytest.raises(ValueError, match="matching"):
        summarize(snap, events, NOW)


def test_journal_partial_append_is_rejected():
    with TemporaryDirectory() as dirname:
        path = Path(dirname) / "journal.jsonl"
        path.write_text('{"event": "intent"}')
        with pytest.raises(ValueError, match="append"):
            read_events(path)


def test_missing_dashboard_audit_is_not_mistaken_for_zero_fills():
    snap, events = fixture()
    snap["order_audit"]["nba"]["status"] = "unavailable"
    with pytest.raises(ValueError, match="unavailable"):
        summarize(snap, events, NOW)
