"""The NBA first-fill audit must not expose trading identities in CI logs."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tools.review_recent_nba_fill import public_summary, read_events, summarize


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
            "updated_utc": (NOW - timedelta(minutes=1 if fresh else 12)).isoformat(),
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


def test_public_ci_report_never_contains_unique_trade_details():
    snap, events = fixture()
    private = summarize(snap, events, NOW)
    printed = json.dumps(public_summary(private))
    for forbidden in (
        OID,
        CID,
        TICKER,
        "secret-game-id",
        "2026-10",
        "51.0",
        "5.4",
        "1000000",
        "999999",
        "fill_time_utc",
        "actual_fill_NO_cents",
        "no_price_dollars",
        "fill_fees_dollars",
        "model_generated_utc",
        "quote",
    ):
        assert forbidden not in printed
    assert public_summary(private)["individual_fills"][0]["maker_status"] == "all_maker"
    assert public_summary(private)["individual_fills"][0]["expiry_matched_tip"] is True


def test_absent_markouts_never_appear_as_profitable():
    snap, events = fixture()
    result = summarize(snap, events, NOW)
    result["latest_fills"][0]["model_estimated_net_edge_cents_at_post"] = None
    result["latest_fills"][0]["markouts_observed"] = {
        "5m": {
            "NO_mid_move_cents_before_fees": None,
            "NO_executable_bid_move_cents_before_fees": None,
            "observation_issue": "quote_unavailable",
        }
    }
    public = public_summary(result)
    row = public["individual_fills"][0]
    assert row["pretrade_edge_sign"] == "unknown"
    assert row["postfill_observations"]["5m"]["mid_direction"] == "unknown"


def test_expiration_gap_is_bucketed_without_exact_time():
    snap, events = fixture()
    events[0]["expiration_ts"] -= 3600
    private = summarize(snap, events, NOW)
    public = public_summary(private)
    row = public["individual_fills"][0]
    assert row["expiry_matched_tip"] is False
    assert row["journal_expiry_gap"] == "before_tip_1h_to_2h"
    assert row["intent_strategy_generation"] == "earlier_or_unknown"
    assert "expiry_delta_seconds" not in json.dumps(public)
