"""research/replay_vs_live.py: the gap and its range, on made-up fills."""

import json

import numpy as np
import pandas as pd

from research import replay_vs_live as R


def fills(n_games, per_game, fair, win_rate, cents=80, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        for _ in range(per_game):
            rows.append(
                {
                    "game": f"g{g}",
                    "cents": cents,
                    "fair_no": fair,
                    "no_won": float(rng.random() < win_rate),
                }
            )
    return pd.DataFrame(rows)


def test_gap_and_difference_have_the_right_sign_and_size():
    replay = fills(200, 10, 0.80, 0.82, seed=1)  # fills beat the books by ~2
    live = fills(200, 4, 0.80, 0.77, seed=2)  # fills trail the books by ~3
    out = R.compare(replay, live)["all"]
    assert 0.5 < out["replay_simulated"]["gap_points"] < 3.5
    assert -5 < out["live"]["gap_points"] < -1
    assert -8 < out["live_minus_replay_points"] < -2
    low, high = out["range_90_points"]
    assert low < out["live_minus_replay_points"] < high < 0
    assert out["live"]["games"] == 200 and out["live"]["fills"] == 800
    json.dumps(out)  # plain numbers only


def test_bands_split_by_price_and_an_empty_band_is_reported_empty():
    replay = fills(50, 5, 0.6, 0.6, cents=55)
    live = fills(50, 5, 0.6, 0.6, cents=55)
    out = R.compare(replay, live)
    assert out["NO 65-95c"]["live"] == {"fills": 0, "games": 0}
    assert "live_minus_replay_points" not in out["NO 65-95c"]
    assert out["NO under 65c"]["live"]["fills"] == 250


def test_live_fills_use_only_book_priced_settled_fills(tmp_path):
    base = {
        "status": "accepted",
        "filled_contracts": 1,
        "game_id": 1,
        "p_yes": 0.2,
        "avg_fill_no_price": 0.8,
    }
    rows = [
        {
            **base,
            "strategy_version": "nba-no-v9-longshots",
            "market_settlement_net_profit_dollars": 0.2,
        },
        {
            **base,
            "strategy_version": "nba-no-v9-longshots",
            "market_settlement_net_profit_dollars": -0.8,
        },
        {
            **base,
            "strategy_version": "nba-no-v6-three-contracts",
            "market_settlement_net_profit_dollars": 0.2,
        },
        {
            **base,
            "strategy_version": "nba-no-v9-longshots",
            "market_settlement_net_profit_dollars": None,
        },
        {
            **base,
            "strategy_version": "nba-no-v9-longshots",
            "filled_contracts": 0,
            "market_settlement_net_profit_dollars": None,
        },
    ]
    pd.DataFrame(rows).to_csv(tmp_path / "2026-11-20.csv", index=False)
    live = R.live_fills(tmp_path)
    assert len(live) == 2 and live.no_won.tolist() == [1.0, 0.0]
    assert live.fair_no.round(2).tolist() == [0.8, 0.8] and live.cents.tolist() == [
        80,
        80,
    ]
