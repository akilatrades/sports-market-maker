"""Offline checks for research/two_strategies*.py on synthetic data."""

import numpy as np
import pandas as pd
import pytest

from research import two_strategies as ts
from research import two_strategies_ladder as tl


def test_matchups_split_on_known_codes():
    codes = {"LAL": "LAL", "DEN": "DEN", "NOP": "NO", "SAS": "SA", "OKC": "OKC"}
    assert ts.split_matchup("LALDEN", codes) == ("LAL", "DEN")
    assert ts.split_matchup("NOPSAS", codes) == ("NOP", "SAS")
    assert ts.split_matchup("XXXYYY", codes) == (None, None)


def test_p_over_counts_whole_number_finals():
    resid = np.array([-1.5, 0.5, 2.5])
    # Line 200.5, strike 200: over when the residual is above -0.5.
    got = ts.p_over([200], [200.5], "empirical", resid)
    assert got[0] == pytest.approx((2 + 0.5) / (3 + 1))
    sym = np.array([-10.0, 10.0] * 500)
    mid = ts.p_over([220], [220.0], "normal", sym)[0]
    assert mid < 0.5  # final > 220 needs 221 or more
    assert ts.p_over([200], [220.0], "normal", sym)[0] > 0.9


def test_one_contract_per_market_in_time_order():
    no = pd.DataFrame(
        {
            "ticker": ["m", "m", "n"],
            "end_ts": [1, 2, 1],
            "price": [0.50, 0.50, 0.40],
            "traded": [3.0, 5.0, 0.0],
            "won": [1.0, 1.0, 0.0],
            "game_id": [1, 1, 2],
            "day": [pd.Timestamp("2026-01-01").date()] * 3,
        }
    )
    fair = np.array([0.45, 0.45, 0.55])  # edges 5c, 5c, 5c
    q = ts.replay_totals(no, fair, 1.0, 0.0)
    assert q.fill.tolist() == [1.0, 0.0, 0.0]  # the second hour cannot fill again
    q = ts.replay_totals(no, fair, 0.25, 0.0)
    first = 1 - 0.75**3
    assert q.fill.iloc[0] == pytest.approx(first)
    assert q.fill.iloc[1] == pytest.approx((1 - first) * (1 - 0.75**5))
    q = ts.replay_totals(no, fair, 1.0, 0.01)
    assert q.pnl_c.iloc[0] == pytest.approx(1 - 0.50 - 0.01)


def test_model_filter_keeps_edges_between_0_and_15_cents():
    no = pd.DataFrame(
        {
            "ticker": ["a", "b", "c"],
            "end_ts": [1, 1, 1],
            "price": [0.50, 0.50, 0.50],
            "traded": [1.0, 1.0, 1.0],
            "won": [1.0, 1.0, 1.0],
            "game_id": [1, 2, 3],
            "day": [pd.Timestamp("2026-01-01").date()] * 3,
        }
    )
    q = ts.replay_totals(no, np.array([0.52, 0.45, 0.30]), 1.0, 0.0)
    assert q.ticker.tolist() == ["b"]  # -2c and +20c are skipped


def test_nearest_book_line_uses_the_same_ladder():
    keys = {"game_id": 1, "snap_ts": 10, "player_key": "p", "stat": "points"}
    book = pd.DataFrame([keys | {"line": 19.5}, keys | {"line": 24.5}])
    rungs = pd.DataFrame(
        [keys | {"line": 22.5}, keys | {"line": 29.5}, keys | {"line": 24.5}]
    )
    assert tl.nearest_book_line(rungs, book).tolist() == [2.0, 5.0, 0.0]
