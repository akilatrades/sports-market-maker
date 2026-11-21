"""The stand-in input for the NBA stat model (research only): what it is,
that it never looks ahead, and that the test stays the one written down."""

import numpy as np
import pandas as pd
import pytest

from markets.nba.features import build_features
from markets.nba.marginals import STATS
from research import returning_regular as R

REGULAR, STAND_IN, STEADY = 1, 2, 3  # player ids on team AAA
OUT_GAMES = {5, 6, 7}  # the regular misses these and returns in game 8


def season(changes=None):
    """Two teams, 12 games. AAA's regular (30 minutes) misses games 5-7; his
    stand-in plays 15 minutes before, 28 while he is out. Everyone else
    plays 25. ``changes`` overrides (game, player) minutes."""
    changes = changes or {}
    rows, games = [], []
    for game in range(12):
        tip = pd.Timestamp("2026-10-20 00:00", tz="UTC") + pd.Timedelta(days=2 * game)
        games.append(
            {
                "game_id": 100 + game,
                "season": 2027,
                "season_type": "regular",
                "tip_utc": tip,
                "home": "AAA",
                "away": "BBB",
                "home_score": 110,
                "away_score": 105,
                "completed": True,
                "home_spread": -3.5,
                "total": 225.5,
            }
        )
        for team, opp, home, base in (
            ("AAA", "BBB", True, 0),
            ("BBB", "AAA", False, 10),
        ):
            for n in range(1, 8):
                player = base + n
                minutes = 25.0
                if player == REGULAR:
                    minutes = 30.0
                if player == STAND_IN:
                    minutes = 28.0 if game in OUT_GAMES else 15.0
                minutes = changes.get((game, player), minutes)
                sat = player == REGULAR and game in OUT_GAMES
                rows.append(
                    {
                        "game_id": 100 + game,
                        "season": 2027,
                        "season_type": "regular",
                        "tip_utc": tip,
                        "game_date": tip.date(),
                        "team": team,
                        "opp": opp,
                        "home": home,
                        "player_id": player,
                        "player": f"Player {player}",
                        "position": "G" if n <= 3 else "F",
                        "starter": n <= 5,
                        "did_not_play": sat,
                        "reason": "injury" if sat else None,
                        "team_score": 110,
                        "opp_score": 105,
                        "minutes": np.nan if sat else minutes,
                        "points": np.nan if sat else minutes / 2,
                        "rebounds": np.nan if sat else minutes / 6,
                        "oreb": np.nan if sat else 1.0,
                        "dreb": np.nan if sat else 3.0,
                        "assists": np.nan if sat else minutes / 8,
                        "threes": np.nan if sat else 1.0,
                        "fg3a": np.nan if sat else 3.0,
                        "fgm": np.nan if sat else 5.0,
                        "fga": np.nan if sat else 10.0,
                        "ftm": np.nan if sat else 2.0,
                        "fta": np.nan if sat else 3.0,
                        "tov": np.nan if sat else 1.0,
                        "steals": np.nan if sat else 1.0,
                        "blocks": np.nan if sat else 0.0,
                        "fouls": np.nan if sat else 2.0,
                    }
                )
    return pd.DataFrame(rows), pd.DataFrame(games)


def inputs(players, games, min_missed=1):
    built = build_features(players, games)
    frame = built[["game_id", "team", "player_id", "ew_minutes"]].join(
        R.revert_inputs(built, players, min_missed)
    )
    return frame.set_index(["game_id", "player_id"])


def test_only_the_stand_in_is_marked_and_only_when_the_regular_returns():
    players, games = season()
    frame = inputs(players, games)
    back = frame.xs(108, level="game_id")
    # 15 minutes going into the stretch, 28 a game during it.
    assert back.at[STAND_IN, "revert"] == pytest.approx(np.log(16 / 29))
    # A teammate whose minutes did not move, the regular himself, the other team.
    assert back.at[STEADY, "revert"] == 0
    assert back.at[REGULAR, "revert"] == 0
    assert (back[back.team == "BBB"].revert == 0).all()
    # No other game has a regular returning.
    others = frame[frame.index.get_level_values("game_id") != 108]
    assert (others.revert == 0).all()
    # The input can only lower a projection, and the split adds up.
    assert (frame.revert <= 0).all()
    assert np.allclose(frame.revert, frame.revert_same + frame.revert_other)
    # Both are guards, so it lands in the same-position input.
    assert back.at[STAND_IN, "revert_same"] == back.at[STAND_IN, "revert"]


def test_it_uses_nothing_from_the_game_it_predicts_or_later():
    players, games = season()
    later = {(game, STAND_IN): 40.0 for game in range(8, 12)}
    later |= {(game, REGULAR): 5.0 for game in range(8, 12)}
    changed, _ = season(later)
    a, b = inputs(players, games), inputs(changed, games)
    assert a.xs(108, level="game_id").revert.equals(b.xs(108, level="game_id").revert)


def test_variant_two_counts_only_absences_of_three_games():
    # The steady teammate sits out game 9 only, and returns in game 10.
    players, games = season()
    sat = (players.game_id == 109) & (players.player_id == STEADY)
    players.loc[sat, "did_not_play"] = True
    players.loc[sat, ["minutes", "points", "rebounds", "assists", "threes"]] = np.nan
    # The stand-in plays more that night, so he has something to give back.
    players.loc[
        (players.game_id == 109) & (players.player_id == STAND_IN), "minutes"
    ] = 30.0
    one = inputs(players, games, min_missed=1)
    three = inputs(players, games, min_missed=3)
    assert one.at[(110, STAND_IN), "revert"] < 0
    assert three.at[(110, STAND_IN), "revert"] == 0
    # The three-game absence still counts in both.
    assert one.at[(108, STAND_IN), "revert"] == three.at[(108, STAND_IN), "revert"]


def test_the_stand_in_definition_is_the_one_the_bias_was_measured_with():
    players, _ = season()
    flags = R.stand_ins(players, [2027])
    assert list(map(tuple, flags.to_numpy())) == [(108, STAND_IN)]
    assert (R.RETURN_MISSED, R.RETURN_MINUTES, R.STAND_IN_GAIN) == (3, 24.0, 5.0)
    # A two-game absence is not a "return" by that definition.
    players.loc[
        (players.game_id == 105) & (players.player_id == REGULAR), "did_not_play"
    ] = False
    players.loc[
        (players.game_id == 105) & (players.player_id == REGULAR), "minutes"
    ] = 30.0
    assert R.stand_ins(players, [2027]).empty


def test_the_candidate_is_the_production_features_plus_the_input():
    players, games = season()
    built = build_features(players, games)
    built = built.join(R.revert_inputs(built, players))
    rows = built[built.ew_minutes.notna() & built.implied_points.notna() & built.played]
    spec = STATS["points"]
    one = R.candidate_spec(spec, ["revert"])
    two = R.candidate_spec(spec, ["revert_same", "revert_other"])
    base = spec.features(rows)
    assert one.features(rows).shape[1] == base.shape[1] + 1
    assert two.features(rows).shape[1] == base.shape[1] + 2
    assert np.array_equal(one.features(rows)[:, :-1], base)
    assert one.feature_names == spec.feature_names + ["revert"]
    assert STATS["points"].features is spec.features  # production is untouched


def test_the_test_is_the_one_written_down():
    # Three variants, design and confirmation seasons apart, nothing live.
    assert sorted(R.VARIANTS) == [1, 2, 3]
    assert R.VARIANTS[2]["min_missed"] == 3 and R.VARIANTS[1]["min_missed"] == 1
    assert R.VARIANTS[3]["columns"] == ["revert_same", "revert_other"]
    assert not set(R.DESIGN_SEASONS) & set(R.CONFIRM_SEASONS)
    assert R.DESIGN_SEASONS == [2023, 2024, 2025] and R.CONFIRM_SEASONS == [2026, 2027]
    source = open(R.__file__, encoding="utf-8").read()
    for live in ("from live", "import live", "prod_nba", "nba_inputs"):
        assert live not in source


def test_scoring_compares_the_two_models_on_the_same_rows():
    results = pd.DataFrame(
        {
            "game_id": [1, 1, 2, 2],
            "player_id": [10, 11, 10, 11],
            "stat": "points",
            "actual": [9.0, 20.0, 11.0, 22.0],
            "mean_production": [12.0, 20.0, 12.0, 22.0],
            "mean_v1": [10.0, 20.0, 10.0, 22.0],
            "loss_production": [1.0, 1.0, 1.0, 1.0],
            "loss_v1": [0.9, 1.0, 0.9, 1.0],
        }
    )
    flags = pd.DataFrame({"game_id": [1, 2], "player_id": [10, 10]})
    out = R.score(results, flags, "v1")["points"]
    assert out["stand_in_rows"] == 2 and out["stand_in_games"] == 2
    assert out["production"]["stand_in_ratio"] == pytest.approx(20 / 24)
    assert out["v1"]["stand_in_ratio"] == pytest.approx(1.0)
    assert out["v1"]["rest_ratio"] == pytest.approx(1.0)
    assert out["v1"]["stand_in_mse"] == pytest.approx(1.0)
    assert out["production"]["stand_in_mse"] == pytest.approx(5.0)
    assert out["mse_change"] == pytest.approx(-4.0)
    assert out["v1"]["log_loss"] == pytest.approx(0.95)
