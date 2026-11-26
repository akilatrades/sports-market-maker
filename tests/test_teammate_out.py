"""Teammate-out study: names, regulars and the game-day label (no data files)."""

import pandas as pd

from research import teammate_out as T


def test_names_join_initials_and_nicknames():
    assert T.key("a j green") == T.key("aj green") == "aj green"
    assert T.key("herb jones") == "herbert jones"
    assert T.key("al horford") == "al horford"


def _box(minutes_by_game):
    rows = []
    for i, minutes in enumerate(minutes_by_game):
        tip = pd.Timestamp("2026-11-01", tz="UTC") + pd.Timedelta(days=i)
        rows.append({"game_id": i, "team": "NY", "tip": tip, "player_key": "star",
                     "minutes": minutes})  # fmt: skip
        rows.append({"game_id": i, "team": "NY", "tip": tip, "player_key": "mate",
                     "minutes": 20})  # fmt: skip
    return pd.DataFrame(rows)


def test_a_regular_with_no_minutes_is_out():
    out = T.regulars_out(_box([30, 32, 35, 31, 33, 0]))
    assert out.to_dict("records") == [
        {"game_id": 5, "team": "NY", "player_key": "star"}
    ]
    assert T.regulars_out(_box([30, 32, 35, 31, 0])).empty  # fewer than 5 prior games


def test_props_pulled_during_the_day_mean_same_day():
    tip = pd.Timestamp("2026-11-06T00:00", tz="UTC")
    snap = [tip - pd.Timedelta(hours=h) for h in (10, 10, 1)]
    s = pd.DataFrame({"event_id": "e", "player_key": ["star", "mate", "mate"],
                      "snap": snap, "stat": "points"})  # fmt: skip
    events = pd.DataFrame(
        {"game_id": [5], "tip": [tip]}, index=pd.Index(["e"], name="event_id")
    )
    outs = pd.DataFrame([{"game_id": 5, "team": "NY", "player_key": "star"}])
    labels, _ = T.classify(s, outs, events)
    assert labels.label.tolist() == ["same_day"]
    s.loc[2, "player_key"] = "star"  # still priced an hour before tip
    assert T.classify(s, outs, events)[0].label.tolist() == ["late_unpriced"]
