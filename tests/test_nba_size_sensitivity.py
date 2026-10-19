"""Risk-budget arithmetic and historical NBA replay invariants (no trading)."""

import pandas as pd

from research.nba_size_sensitivity import (
    POLICIES,
    fee_per_contract,
    max_contracts,
    prepare,
    replay,
)


def sample_game():
    return {
        "game_id": 10,
        "ticker": "KXNBA-TEST-A",
        "price": 0.6,
        "book_edge": 0.07,
        "book_n": 2,
        "hours_before": 3.5,
        "pnl_no_fee": 0.4,
        "filled_contracts": 20,
        "tip_utc": "2026-01-12T20:00:00Z",
    }


def test_price_and_reserve_correctly_shrink_order_size():
    assert max_contracts(0.6, 3, 5) == 4
    assert max_contracts(0.6, 4.5, 8) == 6
    assert max_contracts(0.6, 15, 25) == 22
    assert max_contracts(0.6, 0, 5) == 0
    assert max_contracts(1.01, 3, 5) == 0
    assert fee_per_contract(0.6) == 0.01


def test_250_cash_with_same_caps_does_not_increase_risk_or_profit():
    source = [sample_game()]
    a = replay(source, POLICIES[0])
    b = replay(source, POLICIES[1])
    assert a == b
    assert a["reserve"] == 2.64
    assert a["contracts"] == 4
    assert a["profit"] == 1.56
    larger = replay(source, POLICIES[3])
    assert larger["contracts"] == 20  # Limited by available print volume.


def test_reserved_lifetime_cost_never_recycles_on_unfilled_orders():
    row = sample_game()
    low = replay([row, {**row, "game_id": 11, "tip_utc": "2026-01-13T20:00:00Z"}],
                 POLICIES[0], fill_capture=0)
    assert low["profit"] == 0
    assert low["filled"] == 0
    assert low["reserve"] == 5.28
    assert low["placed"] == 2


def test_prepare_enforces_book_sources_price_and_2_to_6_hour_window():
    r = sample_game()
    lines = [
        r,
        {**r, "ticker": "KXNBA-TEST-B", "book_edge": 0.09},
        {**r, "ticker": "KXNBA-TEST-C", "game_id": 11, "book_n": 1},
        {**r, "ticker": "KXNBA-TEST-D", "game_id": 12, "hours_before": 1.0},
    ]
    chosen, count = prepare(pd.DataFrame(lines))
    assert count["two_book_possible_fill_rows"] == 3
    assert count["within_2_to_6_hours_possible_fill_rows"] == 2
    assert len(chosen) == 1
    assert chosen.iloc[0].ticker == "KXNBA-TEST-B"


def test_one_trade_per_game_not_multiple_correlated_thresholds():
    r = sample_game()
    a = {**r, "ticker": "KXNBA-TEST-B", "book_edge": 0.08}
    chosen, _ = prepare(pd.DataFrame([r, a]))
    assert chosen.game_id.nunique() == 1
    assert replay(chosen.to_dict("records"), POLICIES[0])["placed"] == 1
