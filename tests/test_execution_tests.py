"""Execution tests: placement prices and first-fill replay (no data files)."""

import pandas as pd

from research import execution_tests as E


def test_two_cents_inside_needs_a_wide_enough_spread():
    q = pd.DataFrame({"yes_bid": [0.20, 0.20], "yes_ask": [0.30, 0.22]})
    one, two = E.place(q, 1), E.place(q, 2)
    assert one.price.tolist() == [0.71, 0.79] and two.price.tolist() == [0.72, 0.78]
    assert two.improved.tolist() == [
        True,
        False,
    ]  # a 2c spread cannot be improved by 2c


def test_fill_counts_trades_through_until_tip_off_only():
    q = pd.DataFrame({"ticker": ["T"], "end_ts": [1000], "tip_ts": [5000], "yes_level": [0.30],
                      "improved": [True], "price": [0.70], "result": ["no"], "game": ["G"]})  # fmt: skip
    t = pd.DataFrame({"ticker": ["T", "T", "T"],
                      "created_time": ["1970-01-01T00:20:00Z", "1970-01-01T00:40:00Z", "1970-01-01T02:00:00Z"],
                      "yes_price": [0.31, 0.29, 0.40], "count": [2.0, 9.0, 5.0],
                      "taker_outcome_side": ["yes", "yes", "yes"]})  # fmt: skip
    got = E.first_fill(q, t).iloc[0]
    assert (
        got.traded == 2.0 and got.fill_ts == 1200 and bool(got.filled)
    )  # 29c is below our level
    assert round(got.value, 4) == round(1 - 0.70 - 0.25 * 0.07 * 0.70 * 0.30, 4)
