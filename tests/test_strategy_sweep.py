"""Offline checks for research/strategy_sweep.py on synthetic rows."""

import pandas as pd
import pytest

from research import strategy_sweep as sw


def _rows():
    base = {
        "event_ticker": "e",
        "series": "KXTEST",
        "category": "sports",
        "half": "earlier",
    }
    rows = [
        # market a, hour 1: spread 10c, both sides fill -> locked 8c
        {
            "ticker": "a",
            "end_ts": 1,
            "side": "yes",
            "price": 0.41,
            "fill": 1.0,
            "pnl": -0.41,
            "spread": 0.10,
        },
        {
            "ticker": "a",
            "end_ts": 1,
            "side": "no",
            "price": 0.51,
            "fill": 1.0,
            "pnl": 0.49,
            "spread": 0.10,
        },
        # market b, hour 1: spread 2c, only NO fills and loses
        {
            "ticker": "b",
            "end_ts": 1,
            "side": "yes",
            "price": 0.49,
            "fill": 0.0,
            "pnl": 0.51,
            "spread": 0.02,
        },
        {
            "ticker": "b",
            "end_ts": 1,
            "side": "no",
            "price": 0.50,
            "fill": 1.0,
            "pnl": -0.50,
            "spread": 0.02,
        },
    ]
    return pd.DataFrame([base | r for r in rows])


def test_two_sided_pairs_both_orders_of_an_hour():
    j = sw.two_sided(_rows()).set_index("ticker")
    assert j.loc["a", "contracts"] == 2 and j.loc["a", "pnl_row"] == pytest.approx(0.08)
    assert j.loc["b", "contracts"] == 1 and j.loc["b", "pnl_row"] == pytest.approx(
        -0.50
    )
    wide = sw.two_sided(_rows(), wide_only=True)
    assert wide.ticker.tolist() == ["a"]


def test_profit_factor_and_cents_per_contract():
    j = sw.two_sided(_rows())
    j["event_ticker"] = ["e1", "e2"]
    s = sw.stats(j, "pnl_row", "contracts")
    assert s["fills"] == 3
    assert s["total_usd"] == pytest.approx(0.08 - 0.50)
    assert s["profit_factor"] == pytest.approx(0.08 / 0.50)
    assert s["cents"] == pytest.approx(100 * (0.08 - 0.50) / 3)
