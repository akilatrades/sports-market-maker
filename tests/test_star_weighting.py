"""Offline checks for research/star_weighting.py."""

import numpy as np
import pandas as pd
import pytest

from research.star_weighting import clustered_difference, star_s1


def test_difference_is_the_gap_between_weighted_group_means():
    values = np.array([0.5, 0.1, -0.2, 0.4, 0.3, -0.1])
    weights = np.array([1, 2, 1, 3, 1, 2])
    star = np.array([True, True, False, False, True, False])
    games = np.array(["a", "b", "a", "c", "c", "b"])
    diff, t = clustered_difference(values, weights, star, games)
    s, o = star, ~star
    want = np.average(values[s], weights=weights[s]) - np.average(
        values[o], weights=weights[o]
    )
    assert diff == pytest.approx(want)
    assert np.isfinite(t)


def test_star_s1_uses_projected_points_and_needs_a_points_market():
    orders = pd.DataFrame(
        {
            "game_id": [1, 1, 1, 2],
            "player_id": [10, 10, 20, 30],
            "stat": ["points", "rebounds", "points", "rebounds"],
            "model_mean": [24.0, 9.0, 12.0, 8.0],
        }
    )
    # Player 10 projects 24 points: both his props count; player 20 projects
    # 12; player 30 has no points market that game.
    assert star_s1(orders).tolist() == [True, True, False, False]
