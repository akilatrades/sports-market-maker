"""Offline checks for research/article_tests.py on synthetic orders."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from research import article_tests as at
from research.fill_sizing_replay import Rules, simulate

DAY1, DAY2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)


def _orders():
    return pd.DataFrame(
        {
            "ticker": ["a", "b", "c", "d", "e"],
            "game_id": ["g1", "g1", "g1", "g2", "g3"],
            "team": ["A", "A", "B", "C", "D"],
            "day": [DAY1, DAY1, DAY1, DAY1, DAY2],
            "tip_ts": [100, 100, 100, 200, 300],
            "edge": [0.05, 0.02, 0.10, 0.01, 0.04],
            "price": [0.50, 0.40, 0.60, 0.90, 0.30],
            "through": [10.0, 0.0, 5.0, 3.0, 1.0],
            "pnl_c": [0.50, -0.40, -0.60, 0.10, -0.30],
        }
    )


def test_run_matches_the_existing_replay():
    o = _orders()
    rules = Rules("t", per_game=2, day_usd=1.5, day_stop=0.2)
    placed, nights = at.run(o, rules, at.fill_matrix(o, 1.0, None)[:, 0])
    assert nights.sum() == pytest.approx(simulate(o, rules)["season P&L $"])
    # Two per game (b is the 3rd in g1), then the $1.50 night cap stops d.
    assert set(placed.ticker) == {"a", "c", "e"}


def test_a_losing_night_blocks_the_next_one():
    o = _orders()
    rules = Rules("t", day_stop=0.05)
    _, nights = at.run(o, rules, np.ones(len(o)))
    assert list(nights.index) == [DAY1]  # DAY1 lost 0.40, so DAY2 is skipped


def test_inventory_penalty_asks_later_orders_in_a_game_for_more_edge():
    o = _orders()
    placed, _ = at.run(o, Rules("t"), np.ones(len(o)), penalty=0.04)
    # In g1 (edges 10c, 5c, 2c): the 2nd needs 4c, the 3rd needs 8c.
    assert sorted(placed.ticker[placed.game_id.eq("g1")]) == ["a", "c"]
    placed, _ = at.run(o, Rules("t"), np.ones(len(o)), penalty=0.0)
    assert len(placed) == len(o)


def test_fill_draws_are_shared_and_monotone_in_volume():
    o = pd.DataFrame({"ticker": ["x", "y", "z"], "through": [0.0, 1.0, 50.0]})
    assert at.fill_matrix(o, 1.0, None)[:, 0].tolist() == [0.0, 1.0, 1.0]
    u = at.uniforms(["x", "y", "z"], draws=200)
    low = at.fill_matrix(o, 0.25, u)
    high = at.fill_matrix(o.assign(through=[3.0, 4.0, 60.0]), 0.25, u)
    assert low[0].sum() == 0  # nothing traded through, never filled
    assert (high >= low).all()  # same random numbers: more volume never fills less
    assert low[1].mean() == pytest.approx(0.25, abs=0.08)
    assert low[2].mean() > 0.99


def test_clustered_difference_is_the_difference_in_means():
    y = np.array([1.0, 0.0, 1.0, 0.0, 1.0, 1.0])
    flag = np.array([1, 0, 1, 0, 0, 1])
    games = np.array(["a", "a", "b", "b", "c", "c"])
    diff, t = at.clustered_difference(y, flag, games)
    assert diff == pytest.approx(1.0 - 1 / 3)
    assert np.isfinite(t) and t > 0


def test_quote_prices_join_and_improve():
    frame = pd.DataFrame({"yes_ask": [0.55], "p_model": [0.40], "over": [0.0]})
    join, better = at.quote(frame, 0), at.quote(frame, 1)
    assert join.price.iloc[0] == pytest.approx(0.45)
    assert not join.improved.iloc[0] and better.improved.iloc[0]
    assert better.price.iloc[0] == pytest.approx(0.46)
    assert better.edge.iloc[0] == pytest.approx(0.60 - 0.46)
    assert better.pnl_c.iloc[0] == pytest.approx(1 - 0.46)


def test_rebuild_uses_the_last_candle_before_the_posting_time():
    hour = 3600
    tip = 10 * hour
    base = pd.DataFrame(
        {
            "ticker": ["m"],
            "tip_ts": [tip],
            "p_model": [0.40],
            "over": [1.0],
            "price": [0.0],
        }
    )
    candles = pd.DataFrame(
        {
            "ticker": ["m"] * 3,
            "end_ts": [tip - 6 * hour, tip - 4 * hour, tip - 3 * hour],
            "yes_bid": [0.50, 0.51, 0.60],
            "yes_ask": [0.53, 0.53, 0.61],
            "open_interest": [1.0, 2.0, 3.0],
        }
    )
    stamp = pd.Timestamp(tip - 3.5 * hour, unit="s", tz="UTC").isoformat()
    early = pd.Timestamp(tip - 5 * hour, unit="s", tz="UTC").isoformat()
    trades = pd.DataFrame(
        {
            "ticker": ["m", "m"],
            "created_time": [early, stamp],
            "yes_price": [0.53, 0.53],
            "count": [7.0, 2.0],
            "taker_outcome_side": ["yes", "yes"],
        }
    )
    q = at.rebuild(base, candles, trades, hours=4)
    row = q.iloc[0]
    assert row.end_ts == tip - 4 * hour  # not the later candle 3 hours before
    assert bool(row.improved) and row.price == pytest.approx(0.48)  # 2c spread
    assert row.edge == pytest.approx(0.60 - 0.48)
    assert row.through == 2.0  # only the trade after the order went up
    # A 1c spread joins the NO bid and then needs trades through its price.
    joined = at.rebuild(base, candles.assign(yes_bid=0.52), trades, hours=4).iloc[0]
    assert not bool(joined.improved) and joined.price == pytest.approx(0.47)
    assert joined.through == 0.0


def test_beats_is_sign_safe():
    assert at.beats(110, 100) and not at.beats(109, 100)
    assert at.beats(-90, -100) and not at.beats(-95, -100)
