"""Offline checks for research/fill_sizing_replay.py on synthetic orders."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from kalshi.stats import clustered_mean_t as repeated_rows_mean_t
from research.fill_sizing_replay import Rules, clustered_mean_t, select, simulate

DAY1, DAY2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)


def _orders():
    return pd.DataFrame(
        {
            "game_id": ["g1", "g1", "g1", "g2", "g3"],
            "team": ["A", "A", "B", "C", "D"],
            "day": [DAY1, DAY1, DAY1, DAY1, DAY2],
            "tip_ts": [100, 100, 100, 200, 300],
            "edge": [0.05, 0.02, 0.20, 0.01, 0.04],
            "price": [0.50, 0.40, 0.60, 0.95, 0.30],
            "through": [10.0, 0.0, 5.0, 3.0, 1.0],
            "pnl_c": [0.50, 0.60, -0.60, 0.05, -0.30],
        }
    )


def test_weighted_t_matches_the_repeated_row_version():
    values = np.array([0.5, -0.4, 0.6, -0.3])
    weights = np.array([2, 1, 3, 1])
    clusters = np.array(["a", "a", "b", "c"])
    got = clustered_mean_t(values, weights, clusters)
    want = repeated_rows_mean_t(
        np.repeat(values, weights), np.repeat(clusters, weights)
    )
    assert got == pytest.approx(want)


def test_select_applies_filters_and_caps_in_edge_order():
    rules = Rules("t", min_edge=0.0, edge_cap=0.15, band=(0.10, 0.90), per_game=1)
    picked = select(_orders(), rules)
    # 0.20 edge is over the cap, the 95c order is outside the band, and only
    # the best-edge order in g1 fits the one-per-game limit.
    assert sorted(picked.edge) == [0.04, 0.05]


def test_simulate_fills_up_to_traded_volume_and_honours_the_loss_stop():
    rules = Rules("t", contracts=2, band=(0.10, 0.90), edge_cap=None)
    result = simulate(_orders(), rules)
    # g1: 2 x 0.50, 0 fills, 2 x -0.60; g3 on day 2: 1 x -0.30.
    assert result["season P&L $"] == pytest.approx(1.0 - 1.2 - 0.3)
    assert result["contracts filled"] == 5
    stopped = simulate(_orders(), Rules("t", contracts=2, edge_cap=None, cum_stop=0.1))
    assert stopped["loss stop hit"]
    assert stopped["season P&L $"] == pytest.approx(-0.2)


def test_lifetime_allowance_skips_orders_that_no_longer_fit():
    rules = Rules("t", contracts=2, edge_cap=None, life_usd=1.2)
    result = simulate(_orders(), rules)
    # Only the 50c order (reserve $1.10) fits; every later one would pass $1.20.
    assert result["placed, lifetime $"] == pytest.approx(1.1)
    assert result["season P&L $"] == pytest.approx(1.0)


def test_a_losing_night_over_the_daily_stop_blocks_the_next_night():
    rules = Rules("t", contracts=2, edge_cap=None, day_stop=0.1)
    result = simulate(_orders(), rules)
    assert result["nights with orders"] == 1
    assert result["season P&L $"] == pytest.approx(-0.2)
