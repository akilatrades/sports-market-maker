"""NBA pilot tracker reports real outcomes, never fills invented from missing data."""

from datetime import UTC, datetime, timedelta

import pytest

from kalshi.trading import TradingError
from live.nba_validation import NBA_LIFETIME_RESERVE, summarize_nba_validation

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def entries():
    return [
        {
            "event": "intent",
            "client_order_id": "a",
            "ticker": "KXNBA-ONE",
            "game_id": "game-1",
            "cost": 2.0,
            "utc": (NOW - timedelta(days=1)).isoformat(),
        },
        {
            "event": "accepted",
            "client_order_id": "a",
            "order_id": "id-a",
            "utc": (NOW - timedelta(days=1)).isoformat(),
        },
        {
            "event": "intent",
            "client_order_id": "rejected",
            "ticker": "KXNBA-REJECT",
            "game_id": "game-1",
            "cost": 1.0,
            "utc": (NOW - timedelta(hours=12)).isoformat(),
        },
        {
            "event": "unknown_outcome",
            "client_order_id": "rejected",
            "utc": NOW.isoformat(),
        },
    ]


def audit(state="fully_filled", count=4, maker=4):
    return {
        "status": "verified_snapshot",
        "orders": [
            {
                "order_id": "id-a",
                "state": state,
                "filled_contracts": count,
                "maker_filled_contracts": maker,
            }
        ],
    }


def test_one_real_fill_not_edge_proof():
    report = summarize_nba_validation(
        entries(),
        audit(),
        {"status": "awaiting_settlement"},
        NOW,
    )
    assert report["status"] == "collecting_live_outcomes"
    assert report["attempted_orders"] == 2
    assert report["accepted_orders"] == 1
    assert report["independent_games_accepted"] == 1
    assert report["independent_games_filled"] == 1
    assert report["closed_order_fill_rate"] == 1
    assert report["filled_contracts"] == 4
    assert report["maker_share"] == 1.0
    assert report["settled_profit_dollars"] is None
    assert report["proof_of_edge"] is False
    assert report["reserved_submissions_dollars"] > 3
    assert report["lifetime_limit_dollars"] == NBA_LIFETIME_RESERVE
    assert report["lifetime_allowance_remaining_dollars"] < NBA_LIFETIME_RESERVE - 3


def test_confirmed_no_fill_counts_as_order_not_fill():
    report = summarize_nba_validation(
        entries(),
        audit("confirmed_unfilled", 0, None),
        {"status": "verified", "settled_profit_dollars": -1.0},
        NOW,
    )
    assert report["confirmed_zero_fill_orders"] == 1
    assert report["closed_known_orders"] == 1
    assert report["closed_order_fill_rate"] == 0
    assert report["independent_games_filled"] == 0
    assert report["settled_profit_dollars"] == -1.0


def test_missing_exchange_order_keeps_outcomes_unknown():
    report = summarize_nba_validation(
        entries(),
        {"status": "unavailable", "orders": []},
        {"status": "incomplete_settlement"},
        NOW,
    )
    assert report["status"] == "awaiting_exchange_audit"
    assert report["filled_contracts"] is None
    assert report["closed_order_fill_rate"] is None
    missing = summarize_nba_validation(
        entries(), {"status": "verified_snapshot", "orders": []}, {}, NOW
    )
    assert missing["status"] == "incomplete_exchange_order_history"


def test_partial_resting_not_misreported_as_closed():
    report = summarize_nba_validation(
        entries(), audit("partially_filled_resting", 2, 2), {}, NOW
    )
    assert report["open_orders"] == 1
    assert report["closed_known_orders"] == 0
    assert report["filled_contracts"] == 2
    assert report["closed_order_fill_rate"] is None


def test_day_30_review_is_not_statistical_proof():
    report = summarize_nba_validation(
        entries(), audit(), {"status": "awaiting_settlement"}, NOW + timedelta(days=30)
    )
    assert report["status"] == "30_day_review_due"
    assert report["proof_of_edge"] is False


def test_missing_fill_fields_are_unknown_not_zero():
    report = summarize_nba_validation(entries(), audit(count=None, maker=None), {}, NOW)
    assert report["status"] == "needs_exchange_reconciliation"
    assert report["filled_contracts"] is None
    assert report["unknown_orders"] == 1


def test_duplicate_intent_rejected():
    events = entries()
    with pytest.raises(TradingError):
        summarize_nba_validation(events + [events[0]], audit(), {}, NOW)
