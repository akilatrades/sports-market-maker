"""Regression tests for fail-closed production journal acceptance indexing."""

import pytest
from live.prod_nba_auto import TradingError, records


def test_records_reject_duplicate_acceptance_client_id():
    events = [
        {"event": "intent", "client_order_id": "a"},
        {"event": "accepted", "client_order_id": "a", "order_id": "one"},
        {"event": "accepted", "client_order_id": "a", "order_id": "two"},
    ]
    with pytest.raises(TradingError, match="Duplicate exchange acceptance"):
        records(events)


def test_records_reject_reused_exchange_order_id():
    events = [
        {"event": "intent", "client_order_id": "a"},
        {"event": "intent", "client_order_id": "b"},
        {"event": "accepted", "client_order_id": "a", "order_id": "one"},
        {"event": "accepted", "client_order_id": "b", "order_id": "one"},
    ]
    with pytest.raises(TradingError, match="Duplicate exchange acceptance"):
        records(events)


@pytest.mark.parametrize("missing", ["client_order_id", "order_id"])
def test_records_reject_malformed_acceptance(missing):
    event = {"event": "accepted", "client_order_id": "a", "order_id": "one"}
    del event[missing]
    with pytest.raises(TradingError, match="Malformed exchange acceptance"):
        records([event])


def test_records_preserve_valid_acceptance():
    attempts, accepted = records(
        [
            {"event": "intent", "client_order_id": "a"},
            {"event": "accepted", "client_order_id": "a", "order_id": "one"},
        ]
    )
    assert len(attempts) == 1
    assert accepted["a"]["order_id"] == "one"
