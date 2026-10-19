"""Offline isolation classifier tests; never contact Kalshi."""

import json

import pytest

from tools.check_account_isolation import classify, journal


def cohort(tmp_path, prefix, ticker, order_id):
    p = tmp_path / f"{prefix}.jsonl"
    events = [
        {"event": "intent", "client_order_id": prefix, "ticker": ticker},
        {"event": "accepted", "client_order_id": prefix, "order_id": order_id},
    ]
    p.write_text("".join(json.dumps(e) + "\n" for e in events))
    return journal(p)


def test_known_nfl_positions_block_nba_not_mislabeled_as_manual(tmp_path):
    nfl = cohort(tmp_path, "n", "NFL-PROP", "n-order")
    nba = cohort(tmp_path, "b", "NBA-PROP", "b-order")
    result = classify(
        [
            {"ticker": "NFL-PROP", "position_fp": "-5.00"},
            {"ticker": "NFL-PROP", "position_fp": "0.00"},
        ],
        [{"order_id": "n-order"}],
        nfl,
        nba,
    )
    assert result["status"] == "ACCOUNT_HAS_RISK_DO_NOT_ACTIVATE_NBA"
    assert result["nfl"] == {
        "held_markets": 1,
        "absolute_contracts": 5,
        "resting_orders": 1,
    }
    assert result["other_or_unrecognized"] == {}
    assert "NFL-PROP" not in str(result)


def test_unrecognized_position_is_not_assumed_nfl(tmp_path):
    nfl = cohort(tmp_path, "n", "NFL-PROP", "n-order")
    nba = cohort(tmp_path, "b", "NBA-PROP", "b-order")
    result = classify([{"ticker": "MANUAL", "position": 2}], [], nfl, nba)
    assert result["other_or_unrecognized"]["held_markets"] == 1


def test_empty_exchange_reads_are_not_evidence_of_future_isolation(tmp_path):
    nfl = cohort(tmp_path, "n", "NFL-PROP", "n-order")
    nba = cohort(tmp_path, "b", "NBA-PROP", "b-order")
    result = classify([], [], nfl, nba)
    assert result["status"] == "NO_RESTING_ORDERS_OR_POSITIONS_AT_THIS_INSTANT"


def test_invalid_exchange_position_fails_closed(tmp_path):
    nfl = cohort(tmp_path, "n", "NFL-PROP", "n-order")
    nba = cohort(tmp_path, "b", "NBA-PROP", "b-order")
    with pytest.raises(ValueError, match="unparseable"):
        classify([{"ticker": "NFL-PROP", "position_fp": "broken"}], [], nfl, nba)


def test_incomplete_private_journal_is_not_trusted(tmp_path):
    p = tmp_path / "journal.jsonl"
    p.write_text('{"event":"accepted"')
    with pytest.raises(ValueError, match="journal_write_in_progress"):
        journal(p)
