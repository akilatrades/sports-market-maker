"""Offline checks for research/explore_strategies.py on synthetic markets."""

import numpy as np
import pandas as pd
import pytest

from research import explore_strategies as es


def _markets():
    return pd.DataFrame(
        {
            "series": ["KXCPIYOY", "KXNBAGAME", "KXRAINNYC", "KXFOO"],
            "event_ticker": ["e1", "e2", "e3", "e4"],
            "yes_bid": [0.88, 0.05, 0.40, 0.30],
            "yes_ask": [0.90, 0.07, 0.95, 0.32],
            "yes_bid_last": [0.90, 0.12, 0.40, 0.30],
            "yes_ask_last": [0.91, 0.14, 0.95, 0.32],
            "yes": [1.0, 0.0, 1.0, 0.0],
        }
    ).assign(
        mid=lambda d: (d.yes_bid + d.yes_ask) / 2,
        mid_last=lambda d: (d.yes_bid_last + d.yes_ask_last) / 2,
    )


def test_categories_by_series_name():
    assert es.category("KXCPIYOY") == "economics"
    assert es.category("KXNBAGAME") == "sports"
    assert es.category("KXTEMPNYCH") == "weather"
    assert es.category("KXTRUMPMENTION") == "mentions"


def test_taker_fee_rounds_up_for_one_contract():
    assert es.taker_fee(0.5) == pytest.approx(0.0175)
    assert es.taker_fee(0.5, rounded=True) == pytest.approx(0.02)
    assert es.taker_fee(0.95, rounded=True) == pytest.approx(0.01)


def test_wide_spread_is_not_a_favourite_by_mid():
    m = _markets()
    raw = es.trades_s1(m, 0.90)  # the planned rule: the 95¢ ask counts
    assert "e3" in set(raw.event_ticker)
    t = es.trades_s1_mid(m, 0.80)  # the extra variant: by mid, tight spread
    assert set(t.event_ticker) == {"e1", "e2"}
    row = t.set_index("event_ticker")
    assert row.loc["e1", "price"] == pytest.approx(0.90)  # buys YES at the ask
    assert row.loc["e2", "price"] == pytest.approx(0.95)  # buys NO at 1 - bid
    assert row.loc["e2", "won"] == 1.0


def test_momentum_buys_the_direction_of_the_move():
    m = _markets()
    up = es.trades_s2(m, True).set_index("event_ticker")
    assert set(up.index) == {"e2"}  # mid 6c -> 13c
    assert up.loc["e2", "price"] == pytest.approx(0.14) and up.loc["e2", "won"] == 0.0
    down = es.trades_s2(m, False).set_index("event_ticker")
    assert down.loc["e2", "price"] == pytest.approx(1 - 0.12)
    assert np.isclose(down.loc["e2", "won"], 1.0)
