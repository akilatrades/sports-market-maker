"""Offline checks for research/explore_ladder.py on synthetic sportsbook ladders."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from research import explore_ladder as el

EARLY, LATE = "2025-12-01T19:00:00Z", "2026-03-01T19:00:00Z"
EARLY_TS = int(pd.Timestamp(EARLY).timestamp())


def test_nb_over_is_the_probability_of_reaching_the_next_whole_number():
    # 24.5 means 25+: P(X >= 25) = 1 - P(X <= 24).
    want = 1 - stats.nbinom.cdf(24, 5, 5 / (5 + 20))
    assert el.nb_over(24.5, 20.0, 5.0) == pytest.approx(want)


def test_normal_over_puts_the_continuity_boundary_at_the_half():
    assert el.normal_over(24.5, 24.5, 3.0) == pytest.approx(0.5)
    assert el.normal_over(21.5, 24.5, 3.0) == pytest.approx(stats.norm.sf(-1.0))


def test_a_negative_binomial_ladder_is_recovered():
    lines = np.arange(10.5, 33.0, 3.0)
    p = el.nb_over(lines, 21.7, 9.0)
    weights = np.array([1, 1, 3, 7, 3, 1, 1, 1])
    fit = el.fit_ladder(lines, p, weights, "nb")
    assert fit["mean"] == pytest.approx(21.7, abs=0.02)
    assert fit["shape"] == pytest.approx(9.0, rel=0.02)
    assert not fit["at_bound"]


def test_a_normal_ladder_is_recovered():
    lines = np.array([3.5, 5.5, 6.5, 7.5, 9.5])
    p = el.normal_over(lines, 6.8, 2.4)
    fit = el.fit_ladder(lines, p, np.ones(len(lines)), "normal")
    assert fit["mean"] == pytest.approx(6.8, abs=0.01)
    assert fit["shape"] == pytest.approx(2.4, rel=0.01)


def test_a_single_line_keeps_the_fixed_shape_and_reproduces_the_book():
    nb = el.fit_ladder([24.5], [0.40], [3], "nb", fixed_shape=9.0)
    assert nb["shape"] == 9.0
    assert el.nb_over(24.5, nb["mean"], 9.0) == pytest.approx(0.40, abs=1e-6)
    n = el.fit_ladder([24.5], [0.40], [3], "normal", fixed_shape=0.3)
    assert n["shape"] == pytest.approx(0.3 * n["mean"])  # sd = ratio x mean
    assert el.normal_over(24.5, n["mean"], n["shape"]) == pytest.approx(0.40, abs=1e-6)


def _ladder(game, player, stat, lines, p, snapshot, book_n=2):
    return pd.DataFrame(
        {
            "player_key": player,
            "stat": stat,
            "line": lines,
            "p_book": p,
            "book_n": book_n,
            "game_id": game,
            "snapshot_utc": snapshot,
        }
    )


def _book(tmp_path):
    lines = np.array([15.5, 20.5, 25.5])
    frame = pd.concat(
        [
            # First half, size 5: the only ladder the pooled shape may use.
            _ladder(1, "a", "points", lines, el.nb_over(lines, 20, 5), EARLY),
            # Second half, size 50: must not leak into the pooled shape.
            _ladder(2, "b", "points", lines, el.nb_over(lines, 20, 50), LATE),
            # First half but only two lines: not used for the pooled shape.
            _ladder(1, "c", "points", [9.5, 12.5], [0.6, 0.3], EARLY),
            _ladder(2, "d", "points", [24.5], [0.45], LATE, book_n=1),
        ],
        ignore_index=True,
    )
    path = tmp_path / "book.csv"
    frame.to_csv(path, index=False)
    return el.load_books(path)


def test_pooled_shape_uses_only_first_half_ladders_with_three_lines(tmp_path):
    fits, shapes = el.fit_all(_book(tmp_path))
    assert shapes["nb"]["points"]["ladders"] == 1
    assert shapes["nb"]["points"]["shape"] == pytest.approx(5.0, rel=0.02)
    single = fits[fits.player_key.eq("d")].iloc[0]
    assert single.n_lines == 1
    assert single.nb_shape == pytest.approx(shapes["nb"]["points"]["shape"])
    assert el.nb_over(24.5, single.nb_mean, single.nb_shape) == pytest.approx(0.45)


def _orders():
    return pd.DataFrame(
        {
            "ticker": ["early", "exact", "rung", "nobook"],
            "game_id": [1, 1, 1, 1],
            "player_key": ["a", "a", "a", "z"],
            "stat": ["points"] * 4,
            "line": [20.5, 20.5, 22.5, 20.5],
            # "early" was posted an hour before the only snapshot of game 1.
            "end_ts": [EARLY_TS - 3600, EARLY_TS + 60, EARLY_TS + 60, EARLY_TS + 60],
            "yes_bid": [0.40, 0.40, 0.30, 0.40],
            "yes_ask": [0.42, 0.42, 0.32, 0.42],
            "p_model": [0.30, 0.30, 0.20, 0.30],
            "day": [dt.date(2025, 12, 1)] * 4,
            "over": [0.0, 0.0, 1.0, 0.0],
            "price": [0.58, 0.58, 0.68, 0.58],
            "through": [0.0, 3.0, 1.0, 0.0],
            "pnl_c": [0.42, 0.42, -0.68, 0.42],
        }
    )


def test_rungs_use_only_snapshots_at_or_before_posting(tmp_path):
    book = _book(tmp_path)
    fits, _ = el.fit_all(book)
    rungs, counts = el.price_rungs(_orders(), book, fits)
    assert counts["posted_before_snapshot"] == 1
    assert counts["no_book_line_for_player_stat"] == 1
    assert sorted(rungs.ticker) == ["exact", "rung"]
    exact = rungs[rungs.ticker.eq("exact")].iloc[0]
    assert exact.book_n == 2 and exact.exact2
    assert exact.live == pytest.approx(exact.p_book)  # two books: the book wins
    rung = rungs[rungs.ticker.eq("rung")].iloc[0]
    assert rung.book_n == 0 and not rung.exact2
    assert rung.live == pytest.approx(0.20)  # no exact line: the model
    assert rung.ladder_nb == pytest.approx(el.nb_over(22.5, 20, 5), abs=1e-3)


def test_the_latest_earlier_snapshot_is_chosen():
    book = pd.DataFrame({"game_id": [1, 1, 1], "snap_ts": [100, 200, 300]})
    orders = pd.DataFrame({"game_id": [1, 1, 1], "end_ts": [50.0, 250.0, 300.0]})
    out = el.match_snapshot(orders, book).sort_values("end_ts")
    assert out.snap_ts.isna().tolist() == [True, False, False]
    assert out.snap_ts.iloc[1:].tolist() == [200, 300]


def test_live_rule_needs_two_books():
    got = el.live_rule([0.4, 0.4, np.nan], [2, 1, 0], [0.3, 0.3, 0.3])
    assert got.tolist() == pytest.approx([0.4, 0.3, 0.3])


def test_fill_amount_at_both_flow_shares():
    through = [0.0, 0.9, 1.0, 3.7]
    assert el.fill_amount(through, 1.0).tolist() == [0, 0, 1, 1]
    want = [0, 0, 0.25, 1 - 0.75**3]
    assert el.fill_amount(through, 0.25).tolist() == pytest.approx(want)


def test_eligibility_uses_the_edge_and_price_band():
    r = pd.DataFrame(
        {
            "fair": [0.40, 0.40, 0.30, 0.97, 0.50],
            "price": [0.60, 0.61, 0.54, 0.02, 0.45],
        }
    )
    ok, edge = el.eligible(r, "fair")
    # edge 0 (in), -1c (out), 16c (out), 1c but NO price 2c (out), 5c (in)
    assert ok.tolist() == [True, False, False, False, True]
    assert edge == pytest.approx([0.0, -0.01, 0.16, 0.01, 0.05])


def test_replay_counts_fills_and_profit_per_eligible_order():
    r = pd.DataFrame(
        {
            "fair": [0.40, 0.40, 0.40, 0.40],
            "price": [0.55, 0.55, 0.55, 0.55],
            "through": [2.0, 0.0, 1.0, 5.0],
            "pnl_c": [0.45, 0.45, -0.55, 0.45],
            "game_id": [1, 1, 2, 3],
        }
    )
    row = el.replay_one(r, "fair", 1.0)
    assert row["eligible"] == 4 and row["fills"] == 3
    assert row["cents_per_fill"] == pytest.approx(
        100 * (0.45 - 0.55 + 0.45) / 3, abs=0.01
    )
    assert row["usd_per_100_eligible"] == pytest.approx(100 * 0.35 / 4, abs=0.01)
    assert row["stated_edge_cents"] == pytest.approx(5.0)
