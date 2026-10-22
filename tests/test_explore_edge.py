"""Offline checks for research/explore_edge.py on synthetic orders."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from research import explore_edge as ee


def test_weighted_difference_matches_means():
    y = np.array([0.5, -0.5, 0.5, 0.5, -0.5, 0.5])
    flag = np.array([1, 1, 0, 0, 0, 1])
    w = np.array([1.0, 1.0, 1.0, 0.0, 1.0, 1.0])
    games = ["a", "a", "b", "b", "c", "c"]
    diff, t = ee.weighted_difference(y, flag, w, games)
    inside = np.average(y[flag == 1], weights=w[flag == 1])
    outside = np.average(y[flag == 0], weights=w[flag == 0])
    assert diff == pytest.approx(inside - outside)
    assert np.isfinite(t)


def _frame(n=4000, seed=1):
    rng = np.random.default_rng(seed)
    days = [dt.date(2026, 1, 1), dt.date(2026, 3, 1)]
    good = rng.random(n) < 0.5
    pnl = np.where(rng.random(n) < 0.5 + 0.2 * good, 0.6, -0.4)
    return pd.DataFrame(
        {
            "game_id": rng.integers(0, 400, n),
            "half": np.where(rng.random(n) < 0.5, "first", "second"),
            "day": [days[i] for i in rng.integers(0, 2, n)],
            "fill_1": np.ones(n),
            "fill_q": np.full(n, 0.5),
            "pnl_c": pnl,
            "group": pd.Categorical(np.where(good, "good", "plain")),
        }
    )


def test_a_clearly_better_bin_is_flagged_and_its_mirror_is_not():
    rows = {r["bin"]: r for r in ee.slice_rows(_frame(), "group")}
    assert rows["good"]["promising"] and rows["good"]["t_vs_rest"] > 2
    assert not rows["plain"]["promising"]
    assert rows["good"]["vs_rest_cents"] == pytest.approx(
        -rows["plain"]["vs_rest_cents"]
    )


def test_small_bins_are_never_promising():
    f = _frame(n=1500)
    rows = {r["bin"]: r for r in ee.slice_rows(f, "group")}
    assert rows["good"]["fills"] < ee.MIN_FILLS
    assert not rows["good"]["promising"]


def test_eligible_applies_the_v5_filter():
    o = pd.DataFrame(
        {"edge": [-0.01, 0.0, 0.15, 0.16, 0.05], "price": [0.5, 0.5, 0.5, 0.5, 0.97]}
    )
    assert ee.eligible(o).index.tolist() == [1, 2]
