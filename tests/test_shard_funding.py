"""No exchange writes when a market's matching engine has no collateral."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from kalshi.shard_funding import (
    require_funded_shard,
    shard_balance,
    verify_market_shard,
)
from kalshi.trading import Order, TradingError


class GETClient:
    def __init__(self, balance="0.0000", shard=3):
        self.calls = []
        self.balance = balance
        self.shard = shard

    def _request(self, method, path):
        self.calls.append((method, path))
        assert method == "GET"  # never post or mutate account
        if path.startswith("/markets/"):
            return {
                "market": {
                    "ticker": "KXNBAPTS-TEST",
                    "exchange_index": self.shard,
                }
            }
        assert path == "/portfolio/balance"
        return {
            "balance_dollars": "244.8000",
            "balance_breakdown": [
                {"exchange_index": 0, "balance": "244.8000"},
                {"exchange_index": 3, "balance": self.balance},
            ],
        }


def test_missing_basketball_collateral_blocks_even_with_aggregate_cash():
    client = GETClient(balance="0.0000")
    with pytest.raises(TradingError, match="SHARD_UNFUNDED_3"):
        require_funded_shard(client, "KXNBAPTS-TEST", 3.30)
    assert len(client.calls) == 2
    assert all(method == "GET" for method, _ in client.calls)


def test_funded_basketball_routes_to_verified_shard_three():
    client = GETClient(balance="20.0000")
    shard = require_funded_shard(client, "KXNBAPTS-TEST", 3.30)
    assert shard == 3
    order = Order("KXNBAPTS-TEST", "no", 2, 40, exchange_index=shard)
    assert order.body()["exchange_index"] == 3
    assert order.body()["side"] == "ask"


def test_balance_breakdown_missing_is_unverifiable():
    with pytest.raises(TradingError, match="Missing shard"):
        shard_balance({"balance_dollars": "244.80"}, 3)
    assert (
        shard_balance(
            {"balance_breakdown": [{"exchange_index": 0, "balance": "244.80"}]},
            3,
        )
        == Decimal("0")
    )


def test_unknown_or_conflicting_shard_must_halt():
    with pytest.raises(TradingError, match="missing or invalid"):
        verify_market_shard({"market": {"exchange_index": None}})
    with pytest.raises(TradingError, match="Duplicate"):
        shard_balance(
            {
                "balance_breakdown": [
                    {"exchange_index": 3, "balance": "1"},
                    {"exchange_index": 3, "balance": "2"},
                ]
            },
            3,
        )
    with pytest.raises(TradingError, match="mismatch"):
        require_funded_shard(SimpleNamespace(_request=lambda *args: {"market": {"ticker": "OTHER", "exchange_index": 3}}), "KXNBAPTS-TEST", 1)
