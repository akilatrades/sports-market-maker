"""Offline checks for research/explore_markets.py on synthetic order rows."""

import numpy as np
import pandas as pd
import pytest

from kalshi.stats import clustered_mean_t
from research import explore_markets as em


def _rows(series, days, pnl, per_market=1, traded=5.0, price=0.5):
    """One market per entry of ``days`` (its own event), ``per_market`` orders each."""
    out = []
    for i, (day, value) in enumerate(zip(days, pnl)):
        for k in range(per_market):
            out.append(
                {
                    "series": series,
                    "ticker": f"{series}-E{i}-M",
                    "event_ticker": f"{series}-E{i}",
                    "end_ts": 1_000_000 + 3600 * k,
                    "date": str(pd.Timestamp("2026-01-01") + pd.Timedelta(days=day))[:10],
                    "side": "no",
                    "price": price,
                    "traded": traded,
                    "won": float(value + price > 0.5),
                    "pnl": value,
                }
            )
    return pd.DataFrame(out)


def test_fill_flags_floor_the_contracts_traded_through():
    o = em.prepare(_rows("A", [0, 1, 2], [0.1, 0.2, 0.3]).assign(traded=[0.6, 1, 3]))
    assert o.fill_1.tolist() == [0.0, 1.0, 1.0]
    assert o.fill_q.to_numpy() == pytest.approx([0.0, 0.25, 1 - 0.75**3])


def test_later_half_splits_each_series_at_its_median_market_date():
    a = _rows("A", [0, 1, 2, 3], [0.1] * 4)
    # Many hourly orders on the first market must not move A's split.
    a = pd.concat([a, _rows("A", [0], [0.1], per_market=9).assign(ticker="A-E0-M")])
    b = _rows("B", [10, 20, 30], [0.1] * 3)
    o = em.prepare(pd.concat([a, b], ignore_index=True))
    later = pd.Series(em.later_half(o), index=o.index)
    by_market = later.groupby(o.ticker).first()
    # A: market days 0, 1, 2, 3 -> median 1.5; B: 10, 20, 30 -> median 20 (later).
    assert by_market.to_dict() == {
        "A-E0-M": False,
        "A-E1-M": False,
        "A-E2-M": True,
        "A-E3-M": True,
        "B-E0-M": False,
        "B-E1-M": True,
        "B-E2-M": True,
    }


def test_score_matches_kalshi_stats_and_ignores_unfilled_orders():
    rng = np.random.default_rng(0)
    o = em.prepare(_rows("A", range(40), rng.normal(0.02, 0.4, 40)))
    o.loc[o.index[:5], "traded"] = 0.0
    o = em.prepare(o)
    s = em.score(o)
    filled = o[o.fill_1 > 0]
    mean, t = clustered_mean_t(filled.pnl, filled.event_ticker)
    assert s["fills"] == 35 and s["orders"] == 40 and s["events"] == 35
    assert s["cents"] == pytest.approx(100 * mean)
    assert s["t"] == pytest.approx(t)
    assert s["cents_per_100_orders"] == pytest.approx(100 * 100 * filled.pnl.sum() / 40)


def test_weighted_score_with_unit_weights_equals_the_unweighted_one():
    rng = np.random.default_rng(1)
    o = em.prepare(_rows("A", range(30), rng.normal(0.0, 0.4, 30)))
    o["fill_q"] = o.fill_1
    assert em.score(o, weight="fill_q")["t"] == pytest.approx(em.score(o)["t"])


def test_duplicates_inside_an_event_add_no_information():
    rng = np.random.default_rng(2)
    values = rng.normal(0.05, 0.4, 25)
    one = em.prepare(_rows("A", range(25), values))
    # The same orders twice: once in the same event, once as separate events.
    same = em.prepare(pd.concat([one, one], ignore_index=True))
    split = same.copy()
    split["event_ticker"] = [f"x{i}" for i in range(len(split))]
    t_one, t_same, t_split = (em.score(x)["t"] for x in (one, same, split))
    assert t_same == pytest.approx(t_one)
    assert t_split == pytest.approx(t_one * np.sqrt(2), rel=0.05)


def test_benjamini_hochberg_adjusted_p_values():
    q = em.bh_qvalues([0.01, 0.04, 0.03, 0.005])
    assert q == pytest.approx([0.02, 0.04, 0.04, 0.02])
    # Step-up: a larger p can rescue a smaller one ranked before it.
    q = em.bh_qvalues([0.02, 0.025, 0.9])
    assert q == pytest.approx([0.0375, 0.0375, 0.9])
    assert len(em.bh_qvalues([])) == 0


def test_one_sided_p_uses_events_minus_one_degrees_of_freedom():
    assert em.one_sided_p([0.0], [10])[0] == pytest.approx(0.5)
    assert em.one_sided_p([2.0], [10])[0] > em.one_sided_p([2.0], [1000])[0]


def _holdout_frame():
    n, rng = 40, np.random.default_rng(3)
    noise = rng.normal(0, 0.05, 2 * n)
    days = list(range(2 * n))
    good_then_bad = np.r_[np.full(n, 0.20), np.full(n, -0.10)] + noise
    bad_then_good = np.r_[np.full(n, -0.10), np.full(n, 0.30)] + noise
    small_early = np.r_[np.full(n, 0.50), np.full(n, 0.0)] + noise
    tiny = _rows("TINY", days, small_early)
    tiny.loc[: n - 15, "traded"] = 0.0  # 14 earlier-half fills: too few to rank
    return em.prepare(
        pd.concat(
            [
                _rows("EARLY", days, good_then_bad),
                _rows("LATE", days, bad_then_good),
                tiny,
            ],
            ignore_index=True,
        )
    )


def test_holdout_ranks_on_the_earlier_half_only():
    o = _holdout_frame()
    table = em.series_table(o)
    pool = em.holdout_pool(table)
    assert set(pool.series) == {"EARLY", "LATE"}  # TINY has 14 earlier fills
    top = em.pick_top(pool, top=1)
    assert top.series.tolist() == ["EARLY"]
    row = table.set_index("series").loc["EARLY"]
    assert row.early_cents == pytest.approx(20, abs=2)
    assert row.late_cents == pytest.approx(-10, abs=2)
    h = em.holdout(o, table)
    assert h["later_positive"] == 1  # LATE is positive later, EARLY is not
    assert h["pooled_later"]["fills"] == 80


def test_series_table_flags_eligibility_and_q_values():
    table = em.series_table(_holdout_frame())
    assert table.eligible.all()
    assert table.q_bh.between(0, 1).all()


def test_combo_rows_take_the_game_day_from_the_event_ticker():
    o = em.prepare(_rows("KXNBA3D", [0, 1], [0.1, -0.2]))
    o["event_ticker"] = ["KXNBA3D-26FEB08DENLAL", "KXNBA3D-26FEB09DENLAL"]
    c = em.combo_rows(o)
    assert c.game_day.dt.strftime("%Y-%m-%d").tolist() == ["2026-02-08", "2026-02-09"]
    block = em.combo_block(c, "pnl_no_fee")["flow_1.0"]
    assert block["before_2026_02_09"]["fills"] == 1
    assert block["from_2026_02_09"]["fills"] == 1
    assert (c.pnl_no_fee - c.pnl_one_cent).to_numpy() == pytest.approx([0.01, 0.01])


def test_load_scan_skips_unreadable_files(tmp_path):
    rows = _rows("A", [0, 1], [0.1, 0.2])
    rows.assign(side="yes").pipe(lambda x: pd.concat([rows, x])).to_csv(
        tmp_path / "orders_A.csv.gz", index=False
    )
    (tmp_path / "orders_B.csv.gz").write_bytes(b"\x1f\x8b broken")
    o, bad = em.load_scan(tmp_path)
    assert bad == ["orders_B.csv.gz"]
    assert len(o) == 2 and set(o.side) == {"no"}
