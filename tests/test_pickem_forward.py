"""research/pickem_forward.py: what a pick is, how it is graded, and the bars."""

import re
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from research import pickem_forward as F

ROOT = Path(__file__).resolve().parents[1]
TIP = "2026-11-25T00:10:00Z"


def pull(line, stamp, sides="both", player="Al Pha", stat="points", app="PrizePicks"):
    return {
        "app": app,
        "player": player,
        "player_key": player.lower(),
        "stat": stat,
        "line": line,
        "sides": sides,
        "home": "CHA",
        "away": "MEM",
        "commence_utc": TIP,
        "snapshot_utc": stamp,
    }


def quote(line, p, stamp, n=5, player="al pha", stat="points"):
    return {
        "player_key": player,
        "stat": stat,
        "line": line,
        "p_book": p,
        "book_n": n,
        "snapshot_utc": stamp,
    }


def chosen(pulls, quotes):
    return F.picks(F.price(pd.DataFrame(pulls), pd.DataFrame(quotes)))


def test_a_pick_is_the_stronger_side_at_the_last_priced_pull_before_tip():
    pulls = [
        pull(20.5, "2026-11-24T20:00+00:00"),
        pull(21.5, "2026-11-24T23:50+00:00"),
        pull(22.5, "2026-11-25T00:20+00:00"),  # after tip-off: never a pick
    ]
    quotes = [
        quote(20.5, 0.60, "2026-11-24T19:50+00:00"),
        quote(21.5, 0.44, "2026-11-24T23:45+00:00", n=3),
        quote(21.5, 0.70, "2026-11-24T23:55+00:00"),  # after the pull: not used
        quote(22.5, 0.30, "2026-11-25T00:15+00:00"),
    ]
    out = chosen(pulls, quotes)
    assert len(out) == 1
    row = out.iloc[0]
    assert (row.line, row.side, row.books) == (21.5, "under", 3)
    assert np.isclose(row.p, 0.56)


def test_a_sportsbook_price_older_than_30_minutes_does_not_price_a_pick():
    pulls = [pull(20.5, "2026-11-24T20:00+00:00"), pull(20.5, "2026-11-24T23:00+00:00")]
    quotes = [quote(20.5, 0.57, "2026-11-24T19:45+00:00")]
    out = chosen(pulls, quotes)
    # The 23:00 pull has no fresh price, so the 20:00 one is the last priced.
    assert len(out) == 1 and out.iloc[0].pulled.hour == 20
    assert chosen(pulls[1:], quotes).empty
    assert F.BOOK_WINDOW == pd.Timedelta(minutes=30)


def test_a_whole_number_line_is_priced_from_its_neighbours_ties_aside():
    pulls = [pull(4.0, "2026-11-24T23:00+00:00", stat="assists")]
    quotes = [
        quote(4.5, 0.40, "2026-11-24T22:50+00:00", stat="assists"),  # over 4
        quote(3.5, 0.70, "2026-11-24T22:50+00:00", stat="assists"),  # under 4 = 0.30
    ]
    row = chosen(pulls, quotes).iloc[0]
    assert row.side == "over" and np.isclose(row.p, 0.40 / 0.70)
    # A half-point line with no exact price gets no pick (no floors).
    assert chosen([pull(4.5, "2026-11-24T23:00+00:00")], quotes).empty


def test_only_offered_sides_can_be_picked():
    pulls = [pull(20.5, "2026-11-24T23:00+00:00", sides="over")]
    quotes = [quote(20.5, 0.42, "2026-11-24T22:50+00:00")]
    row = chosen(pulls, quotes).iloc[0]
    assert row.side == "over" and np.isclose(row.p, 0.42)


def box(rows):
    frame = pd.DataFrame(
        rows, columns=["player", "tip_utc", "did_not_play", "minutes", "points"]
    )
    for stat in ("rebounds", "assists", "threes"):
        frame[stat] = 4.0
    return frame


def test_grading_win_loss_tie_void_and_pending():
    def graded(line, side_quote, rows, stat="points"):
        picks = chosen(
            [pull(line, "2026-11-24T23:00+00:00", stat=stat)],
            [
                quote(
                    line + (0.5 if line % 1 == 0 else 0),
                    side_quote,
                    "2026-11-24T22:50+00:00",
                    stat=stat,
                ),
                quote(
                    line - (0.5 if line % 1 == 0 else 0),
                    side_quote,
                    "2026-11-24T22:50+00:00",
                    stat=stat,
                ),
            ],
        )
        return F.grade(picks, box(rows)).iloc[0].result

    played = lambda points, dnp=False, minutes=30.0: [  # noqa: E731
        ("Al Pha", "2026-11-25T00:12:00Z", dnp, minutes, points)
    ]
    assert graded(20.5, 0.60, played(25.0)) == "win"  # over
    assert graded(20.5, 0.60, played(18.0)) == "loss"
    assert graded(20.5, 0.40, played(18.0)) == "win"  # under
    assert graded(4.0, 0.40, played(0.0), stat="assists") == "tie"  # 4 assists
    assert graded(20.5, 0.60, played(0.0, dnp=True, minutes=0.0)) == "void"
    assert graded(20.5, 0.60, played(0.0, minutes=0.0)) == "void"
    assert graded(20.5, 0.60, []) == "pending"
    # Another night's game for the same player is not his result.
    other = [("Al Pha", "2026-11-26T00:10:00Z", False, 30.0, 40.0)]
    assert graded(20.5, 0.60, other) == "pending"


def picks_frame(n, wins, p=0.55, books=5, day="2026-11-25"):
    return pd.DataFrame(
        {
            "p": p,
            "books": books,
            "result": ["win"] * wins + ["loss"] * (n - wins),
            "commence_utc": [f"{day}T00:{i % 60:02d}:00Z" for i in range(n)],
            "home": [f"H{i}" for i in range(n)],
            "away": "A",
            "tip": pd.Timestamp(day, tz="UTC") + pd.to_timedelta(range(n), unit="min"),
            "app": "PrizePicks",
        }
    )


def test_the_primary_bars_are_the_ones_written_down():
    assert (F.BAR, F.FIRST_LOOK, F.VERDICT, F.STOP_BELOW) == (0.54, 200, 600, 0.52)
    assert F.primary(picks_frame(50, 30))["status"].startswith("waiting")
    assert F.primary(picks_frame(250, 150))["status"].startswith("first look done")
    assert F.primary(picks_frame(250, 100))["status"] == "stopped at the first look"
    assert F.primary(picks_frame(600, 360))["status"] == "passed at the verdict"
    assert F.primary(picks_frame(600, 330))["status"] == "not shown at the verdict"
    # Under the bar, or priced by too few books for the extra cut: not counted.
    assert F.primary(picks_frame(250, 150, p=0.53))["picks"] == 0
    assert F.primary(picks_frame(250, 150, books=2), F.MIN_BOOKS_CUT)["picks"] == 0


def test_the_break_even_is_the_six_pick_flex_at_the_published_payouts():
    pays = {6: 25, 5: 2, 4: 0.4}
    value = lambda p: sum(  # noqa: E731
        m * comb(6, k) * p**k * (1 - p) ** (6 - k) for k, m in pays.items()
    )
    assert abs(brentq(lambda p: value(p) - 1, 0.4, 0.7) - F.BREAK_EVEN) < 0.0002
    # The page's entry builder uses the same payout table.
    page = (ROOT / "research/nba_player_pool_dashboard.template.html").read_text(
        "utf-8"
    )
    assert '{picks: 6, type: "Flex", pays: {6: 25, 5: 2, 4: 0.4}}' in page
    assert '{picks: 6, type: "Power", pays: {6: 37.5}}' in page
    assert len(re.findall(r'\{picks: \d, type: "(?:Power|Flex)"', page)) == 10
    assert "Untested and not a forecast." in page


def test_only_games_from_the_start_date_are_counted():
    early = picks_frame(10, 6, day="2026-11-22")
    late = picks_frame(10, 5, day="2026-11-25")
    summary = F.summarise(pd.concat([early, late], ignore_index=True))
    assert summary["picks_made"] == 10
    assert summary["calibration_all_picks"]["win_rate"] == 0.5
    assert summary["before_the_plan_not_tested"]["win_rate"] == 0.6
    assert str(F.START.date()) == "2026-11-24"
