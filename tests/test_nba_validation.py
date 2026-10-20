"""NBA pilot tracker reports real outcomes, never fills invented from missing data."""

from datetime import UTC, datetime, timedelta

import pytest

from kalshi.trading import TradingError
from live.nba_validation import summarize_nba_validation

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
        {
            "event": "reconciled_rejected",
            "client_order_id": "rejected",
            "utc": NOW.isoformat(),
            "submission_http_status": 404,
            "evidence": "signed_get_no_order_fill_position_and_owner_ui",
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
    assert report["lifetime_allowance_remaining_dollars"] < 47


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


def test_unresolved_attempt_flags_private_validation_even_with_valid_fills():
    events = [e for e in entries() if e["event"] != "reconciled_rejected"]
    report = summarize_nba_validation(events, audit(), {}, NOW)
    assert report["status"] == "needs_submission_reconciliation"
    assert report["unresolved_submission_attempts"] == 1
    assert report["reserved_submissions_dollars"] > 3
    assert report["proof_of_edge"] is False


def test_unresolved_attempt_before_first_acceptance_is_not_a_clean_wait():
    events = [
        e for e in entries() if e["event"] == "intent" and e["client_order_id"] == "a"
    ]
    report = summarize_nba_validation(events, {"status": "unavailable"}, {}, NOW)
    assert report["status"] == "needs_submission_reconciliation"
    assert report["accepted_orders"] == 0


def test_reject_duplicate_acceptance_for_same_client_id():
    events = entries() + [
        {
            "event": "accepted",
            "client_order_id": "a",
            "order_id": "id-b",
            "utc": NOW.isoformat(),
        }
    ]
    with pytest.raises(TradingError, match="Unreconciled NBA acceptance"):
        summarize_nba_validation(events, audit(), {}, NOW)


@pytest.mark.parametrize(
    "state, count, maker",
    [
        ("confirmed_unfilled", 2, None),
        ("resting_no_fill", 1, None),
        ("fully_filled", 3, 4),
    ],
)
def test_impossible_exchange_fill_state_requires_reconciliation(state, count, maker):
    report = summarize_nba_validation(entries(), audit(state, count, maker), {}, NOW)
    assert report["status"] == "needs_exchange_reconciliation"
    assert report["unknown_orders"] == 1
    assert report["filled_contracts"] is None
