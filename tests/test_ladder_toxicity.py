"""Ladder and toxicity studies: fees, curve residuals, fills, gaps (no data files)."""

import numpy as np
import pandas as pd

from research import ladder as L
from research import toxicity as X


def test_taker_fee_rounds_up_to_the_cent():
    assert L.taker_fee(np.array([0.5]))[0] == 0.02  # 0.0175 -> 2c
    assert L.taker_fee(np.array([0.05]))[0] == 0.01


def test_a_kinked_strike_gets_a_positive_residual():
    strikes = [9.5, 14.5, 19.5, 24.5, 29.5]
    mids = [0.90, 0.75, 0.58, 0.30, 0.12]  # 19.5 sits above a smooth curve
    c = pd.DataFrame({"ladder": "L", "end_ts": 0, "floor_strike": strikes, "mid": mids})
    r = L.residuals(c).set_index("floor_strike").resid
    assert r.idxmax() == 19.5 and r[19.5] > 0.03


def test_fills_read_trade_times_in_any_unit():
    o = pd.DataFrame({"ticker": ["T"], "end_ts": [1_763_488_800], "yes_level": [0.40],
                      "improved": [True]})  # fmt: skip
    t = pd.DataFrame({"ticker": ["T", "T", "T"],
                      "created_time": ["2025-11-18T18:30:00.123456Z", "2025-11-18T18:40:00Z",
                                       "2025-11-18T20:00:01Z"],
                      "yes_price": [0.41, 0.40, 0.45], "count": [3.0, 2.0, 9.0],
                      "taker_outcome_side": ["yes", "yes", "yes"]})  # fmt: skip
    assert L.traded_through(o, t)["T"] == 5.0  # the third trade is after the hour


def test_game_codes_match_box_score_keys():
    assert L.game_key("25DEC01PHXLAL") == "25DEC01|LAL"
    assert L.game_key("26JUN13NYKSAS") == "26JUN13|SA"


def test_toxicity_gap_is_filled_minus_unfilled():
    rows = [{"series": "S", "result": "no", "pnl": 0.30 if i < 40 else -0.10,
             "traded": 0 if i < 40 else 10} for i in range(80)]  # fmt: skip
    g = X.gaps(pd.DataFrame(rows))
    assert round(float(g.loc["S", "gap"]), 2) == -0.40
