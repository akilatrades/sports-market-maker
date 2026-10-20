"""Regression: no blind resubmission or exchange writes after shard rejection."""

from datetime import UTC, datetime, timedelta

import pytest

from kalshi.trading import TradingError
from live.reconciled_attempts import rejected_client_ids
from tools.reconcile_shard_404 import case_to_reconcile, verify

NOW = datetime(2026, 10, 20, 15, 32, tzinfo=UTC)
OLD = "old-rejected-id"
NEW = "new-shard-rejected-id"
TICKER = "KXNBAPTS-26OCT20-TEST"


def events():
    return [
        {
            "event": "intent",
            "client_order_id": OLD,
            "ticker": "KXNBA-OLD",
            "cost": 1.0,
            "utc": (NOW - timedelta(hours=4)).isoformat(),
        },
        {"event": "unknown_outcome", "client_order_id": OLD, "type": "TradingError"},
        {
            "event": "reconciled_rejected",
            "client_order_id": OLD,
            "submission_http_status": 404,
            "utc": (NOW - timedelta(hours=1)).isoformat(),
            "evidence": "signed_get_no_order_fill_position_and_owner_ui",
        },
        {
            "event": "intent",
            "client_order_id": NEW,
            "ticker": TICKER,
            "cost": 2.0,
            "utc": (NOW - timedelta(minutes=26)).isoformat(),
        },
        {"event": "unknown_outcome", "client_order_id": NEW, "type": "TradingError"},
    ]


class Exchange:
    def __init__(self, index=3, shard_cash="0.0000", orders=None):
        self.index = index
        self.shard_cash = shard_cash
        self.orders = orders or []
        self.calls = []

    def _request(self, method, path):
        self.calls.append((method, path))
        assert method == "GET"
        if path == f"/markets/{TICKER}":
            return {"market": {"ticker": TICKER, "exchange_index": self.index}}
        assert path == "/portfolio/balance"
        return {
            "balance_breakdown": [
                {"exchange_index": 0, "balance": "244.8000"},
                {"exchange_index": 3, "balance": self.shard_cash},
            ]
        }

    def pages(self, path, key, **kwargs):
        self.calls.append(("GET", path))
        if path == "/portfolio/orders":
            return self.orders
        return []


def test_second_404_requires_exactly_one_unresolved_attempt():
    cid, intent = case_to_reconcile(events(), NOW)
    assert cid == NEW and intent["ticker"] == TICKER
    assert rejected_client_ids(events()) == {OLD}


def test_known_shard_failure_has_read_only_evidence_and_zero_available():
    exchange = Exchange()
    cid, report = verify(exchange, events(), [], NOW)
    assert cid == NEW
    assert report["market_exchange_index"] == 3
    assert report["shard_available_dollars"] == "0.0000"
    assert not report["shard_funded_for_max_3_dollar_order"]
    assert exchange.calls
    assert all(op == "GET" for op, _ in exchange.calls)


def test_unexpected_order_or_shard_blocks_reconciliation():
    with pytest.raises(TradingError, match="historical exchange order"):
        verify(Exchange(orders=[{"ticker": TICKER}]), events(), [], NOW)
    with pytest.raises(TradingError, match="expected index 3"):
        verify(Exchange(index=0), events(), [], NOW)
    with pytest.raises(TradingError):
        case_to_reconcile(
            events()
            + [
                {
                    "event": "accepted",
                    "client_order_id": NEW,
                    "order_id": "exchange_order",
                }
            ],
            NOW,
        )


def test_append_marker_for_shard_404_is_valid_and_keeps_other_resolution():
    case = events()
    case.append(
        {
            "event": "reconciled_rejected",
            "client_order_id": NEW,
            "submission_http_status": 404,
            "utc": NOW.isoformat(),
            "evidence": "signed_get_no_order_fill_position_and_explicit_shard_404",
        }
    )
    assert rejected_client_ids(case) == {OLD, NEW}
