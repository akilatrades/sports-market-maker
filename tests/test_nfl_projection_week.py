"""A fresh model timestamp must never relabel an already completed NFL slate."""

import pandas as pd
import pytest

from live.nfl_projections import next_week


def test_delayed_monday_score_does_not_publish_old_week():
    games = pd.DataFrame([
        {"gameday": "2026-10-19", "season": 2026, "week": 6, "home_score": None, "total_line": 47},
        {"gameday": "2026-10-22", "season": 2026, "week": 7, "home_score": None, "total_line": 45},
        {"gameday": "2026-10-25", "season": 2026, "week": 7, "home_score": None, "total_line": 48},
    ])
    assert next_week(games, pd.Timestamp("2026-10-20T02:15:00Z")) == (2026, 6)
    assert next_week(games, pd.Timestamp("2026-10-20T14:15:00Z")) == (2026, 7)
    assert next_week(games, pd.Timestamp("2026-10-23T14:15:00Z")) == (2026, 7)
    assert next_week(games, pd.Timestamp("2026-10-27T14:15:00Z")) is None


def test_next_week_rejects_naive_clock():
    games = pd.DataFrame({"gameday": ["2026-10-22"], "season": [2026],
                          "week": [7], "home_score": [None], "total_line": [44]})
    with pytest.raises(ValueError, match="aware"):
        next_week(games, pd.Timestamp("2026-10-20T12:00:00"))
