"""research/player_types.py: grouping without lookahead, and the difference t."""

import numpy as np
import pandas as pd

from research import player_types as T


def box(rows):
    frame = pd.DataFrame(
        rows, columns=["player_id", "tip_utc", "minutes", "points", "fg3a", "fga"]
    )
    frame["tip_utc"] = pd.to_datetime(frame.tip_utc, utc=True)
    frame["season"] = 2026
    frame["did_not_play"] = False
    frame["rebounds"] = 4.0
    frame["assists"] = 2.0
    return frame


def test_features_use_only_games_before_the_cutoff():
    rows = [(1, "2025-11-01", 36.0, 20.0, 4.0, 10.0)] * 3
    rows += [(1, "2025-12-01", 36.0, 90.0, 4.0, 10.0)]  # after: must not count
    rows += [(2, "2025-11-01", 36.0, 10.0, 0.0, 0.0)] * 3  # no shots: left out
    out = T.player_features(box(rows), pd.Timestamp("2025-11-18", tz="UTC"), 3)
    assert list(out.index) == [1]
    assert out.games[1] == 3 and out.pts36[1] == 20.0
    assert out.three_share[1] == 0.4
    assert T.player_features(box(rows), pd.Timestamp("2025-11-18", tz="UTC"), 4).empty


def test_types_are_numbered_by_scoring_whatever_kmeans_calls_them():
    rng = np.random.default_rng(0)
    features = pd.DataFrame(rng.normal(size=(40, len(T.FEATURES))), columns=T.FEATURES)
    features["pts36"] = np.r_[np.full(20, 25.0), np.full(20, 10.0)] + features.pts36
    labels = T.assign_types(features, 2)
    assert set(labels) == {1, 2}
    means = features.pts36.groupby(labels).mean()
    assert means[1] > means[2]
    assert labels.equals(T.assign_types(features, 2))  # fixed seed


def test_difference_t_matches_the_means_and_respects_clusters():
    values = np.r_[np.full(50, 0.10), np.full(50, 0.00)] + np.tile([0.01, -0.01], 50)
    inside = np.r_[np.ones(50, bool), np.zeros(50, bool)]
    mean_in, mean_out, diff, t = T.difference_t(values, inside, np.arange(100))
    assert np.isclose(mean_in, 0.10) and np.isclose(mean_out, 0.0)
    assert np.isclose(diff, 0.10) and t > 10
    # Rows that share a game's shock carry less information than they seem to.
    rng = np.random.default_rng(1)
    games = np.repeat(np.arange(20), 10)
    noisy = np.repeat(rng.normal(0, 0.3, 20), 10) + rng.normal(0, 0.05, 200)
    half = np.tile([True, False], 100)
    noisy = noisy + 0.02 * half
    alone = T.difference_t(noisy, half, np.arange(200))[3]
    by_game = T.difference_t(noisy, half, games)[3]
    assert np.isfinite(by_game) and by_game != alone
    half_games = games < 10  # the type sits in whole games: far less certain
    assert abs(T.difference_t(noisy, half_games, games)[3]) < abs(
        T.difference_t(noisy, half_games, np.arange(200))[3]
    )
    assert np.isnan(T.difference_t(values, np.zeros(100, bool), np.arange(100))[3])


def test_a_lead_needs_t_of_3_matching_signs_and_both_halves():
    def table(t, overpay, first, second):
        rows = []
        for measure, diff in (
            ("fills", 2.0),
            ("fills_v9", 2.0),
            ("yes_overpay", overpay),
        ):
            rows.append(
                {
                    "measure": measure,
                    "type": 1,
                    "diff_cents": diff,
                    "t": t,
                    "diff_first_half_cents": first,
                    "diff_second_half_cents": second,
                }
            )
        return pd.DataFrame(rows)

    assert T.leads(table(3.2, 1.0, 1.0, 3.0)) == [1]
    assert T.leads(table(2.9, 1.0, 1.0, 3.0)) == []
    assert T.leads(table(3.2, -1.0, 1.0, 3.0)) == []
    assert T.leads(table(3.2, 1.0, -1.0, 3.0)) == []
    assert T.LEAD_T >= 3 and T.TYPES == 5 and T.SENSITIVITY == (4, 6)
