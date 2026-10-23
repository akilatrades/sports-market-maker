"""The pre-registered spread start-time study's building blocks (synthetic data)."""

import json

import numpy as np
import pandas as pd

import research.spread_start_window as W

H = 3600


def events():
    # Ticker-timed esports events (start 22:00 UTC), a milestone 5 minutes
    # early on each; untimed basketball events whose expiry is 3 h after start.
    rows = []
    for i in range(25):
        rows.append(
            {
                "event_ticker": f"KXCS2GAME-26OCT{10 + i % 9:02d}1800E{i}",
                "expiry": f"2026-10-{11 + i % 9:02d}T02:00:00Z",  # 4 h after start
                "milestones": json.dumps(
                    [
                        {
                            "start": f"2026-10-{10 + i % 9:02d}T21:55:00Z",
                            "type": "esports_game",
                        }
                    ]
                ),
            }
        )
    for i in range(12):
        rows.append(
            {
                "event_ticker": f"KXNCAAWBGAME-26MAR{10 + i:02d}B{i}",
                "expiry": f"2026-03-{10 + i:02d}T03:00:00Z",
                "milestones": json.dumps([]),
            }
        )
    return pd.DataFrame(rows)


def test_start_sources_s1_s2_s3(tmp_path):
    events().to_csv(tmp_path / "events_X.csv.gz", index=False)
    e = W.load_events(tmp_path)
    by_type = W.milestone_by_type(e)
    types = W.trusted_types(e, by_type)
    assert types["esports_game"]["events"] == 25 and types["esports_game"]["trusted"]
    s1, _ = W.starts(e, ("S1",), by_type, types)
    assert len(s1) == 25  # only ticker-timed events
    s12, _ = W.starts(e, ("S1", "S2"), by_type, types)
    assert len(s12) == 25  # S1 wins where both exist; untimed events have no milestone
    # S3 needs a usable per-series offset: the basketball series has no known
    # starts at all here, so nothing is added for it.
    s123, offsets = W.starts(e, ("S1", "S2", "S3"), by_type, types)
    assert len(s123) == 25 and offsets["KXCS2GAME"]["usable"]


def test_s3_uses_a_consistent_series_offset_with_a_margin():
    e = pd.DataFrame(
        {
            "event_ticker": [f"KXA-{i}" for i in range(12)],
            "series": ["KXA"] * 12,
            "expiry": [1_000_000.0 + i * 86400 for i in range(12)],
            "s1": [np.nan] * 12,
            "milestones": [[] for _ in range(12)],
        }
    )
    known = {f"KXA-{i}": 1_000_000.0 + i * 86400 - 3 * H for i in range(10)}
    offsets = W.series_offsets(e, known)
    assert offsets["KXA"]["usable"] and offsets["KXA"]["median_s"] == 3 * H
    # Two more events get start = expiry - 3 h - 30 min.
    by_type, types = {}, {}
    e.loc[:9, "s1"] = [known[f"KXA-{i}"] for i in range(10)]
    got, _ = W.starts(e, ("S1", "S3"), by_type, types)
    assert got["KXA-11"] == e.expiry[11] - 3 * H - W.OFFSET_MARGIN


def test_pregame_selection_and_the_bar():
    r = pd.DataFrame(
        {
            "ticker": ["T-a", "T-a", "T-b"],
            "event_ticker": ["E1", "E1", "E2"],
            "end_ts": [0, 2 * H, 0],
            "side": ["yes", "yes", "no"],
            "hours_before_expiry": [10.0, 6.0, 20.0],
        }
    )
    known = {"E1": 3 * H, "E2": 10 * H}
    # 7->4: only the 6-hour row, and it is 60 min before the start: too close.
    assert W.select(r, known, 7).empty
    # 12->4: the 10-hour row, 180 min ahead, qualifies.
    assert list(W.select(r, known, 12).end_ts) == [0]
    assert len(W.select(r, known, 24)) == 2
    checks, _, _ = W.judge(
        {"fills": 10},
        6,
        pd.DataFrame(columns=["pnl", "series", "event_ticker", "half"]),
        [0.0],
    )
    assert not any(checks.values())
