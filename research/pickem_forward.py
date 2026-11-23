"""Pick'em picks against the sportsbooks: the forward check.

RESEARCH_LOG.md, 2026-11-23, "Pick'em picks against the sportsbooks: the
forward check". Each PrizePicks or Underdog line is priced by the
sportsbooks' de-vigged chance for the same line; this asks, on games from
24 November 2026, whether the stronger side wins as often as that chance
says. It reads files and writes tables. It places nothing.

A pick is one per app, player, stat and game: the stronger side at the last
pull before tip-off that the sportsbooks priced exactly, from a sportsbook
snapshot taken in the 30 minutes before that pull.

    python -m live.fetch_nba_data        # box scores, for grading
    python -m research.pickem_forward    # writes outputs/pickem_forward/
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from markets.nba.kalshi import normalize_name

PICKEM = Path("outputs/pickem")
BOOKS = Path("outputs/books")
BOX = Path("data/player_games.parquet")
OUT = Path("outputs/pickem_forward")
START = pd.Timestamp("2026-11-24", tz="UTC")  # first tip-off counted
SEASON = 2027  # 2026-27, named by the year it ends
BOOK_WINDOW = pd.Timedelta(minutes=30)
TIP_MATCH = pd.Timedelta(minutes=90)  # same teams, same night
BAR = 0.54  # the primary picks
BREAK_EVEN = 0.5421  # 6-pick Flex at PrizePicks' standard payouts, the lowest
FIRST_LOOK, VERDICT = 200, 600
STOP_BELOW = 0.52
MIN_BOOKS_CUT = 3
BUCKETS = [0.0, 0.52, 0.53, 0.54, 0.55, 1.01]
LABELS = ["under 52%", "52 to 53%", "53 to 54%", "54 to 55%", "55% or more"]
STATS = ("points", "rebounds", "assists", "threes")
KEYS = ["app", "player_key", "stat", "home", "away", "commence_utc"]


def read_days(folder):
    """Every day file in ``folder`` as one frame (empty if there are none)."""
    frames = []
    for path in sorted(Path(folder).glob("nba_2*.csv.gz")):
        try:
            frames.append(pd.read_csv(path))
        except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def when(values):
    """UTC times at one resolution, so frames from different files can be joined."""
    return pd.to_datetime(values, utc=True, errors="coerce").astype(
        "datetime64[ns, UTC]"
    )


def text(frame, columns):
    """The join keys as plain strings in every frame."""
    return frame.assign(**{c: frame[c].astype(str).astype(object) for c in columns})


def price(pulls, books):
    """Each app line at each pull with the sportsbooks' chance of the over and
    of the under, from the newest sportsbook snapshot in the 30 minutes before
    the pull. Lines with no exact price are dropped."""
    pulls = text(pulls[pulls.stat.isin(STATS)], ["player_key", "stat"])
    pulls["line"] = pd.to_numeric(pulls.line, errors="coerce").astype(float)
    pulls["pulled"] = when(pulls.snapshot_utc)
    pulls["tip"] = when(pulls.commence_utc)
    pulls = pulls.dropna(subset=["pulled", "tip", "line"])
    pulls = pulls[pulls.pulled < pulls.tip]
    quotes = text(
        books[["player_key", "stat", "line", "p_book", "book_n"]],
        ["player_key", "stat"],
    )
    quotes["quoted"] = when(books.snapshot_utc)
    quotes["line"] = pd.to_numeric(quotes.line, errors="coerce").astype(float)
    quotes["p_book"] = pd.to_numeric(quotes.p_book, errors="coerce")
    quotes["book_n"] = pd.to_numeric(quotes.book_n, errors="coerce")
    quotes = quotes.dropna(subset=["quoted", "p_book", "line"]).sort_values("quoted")
    whole = np.isclose(pulls.line % 1, 0)
    pulls["whole"] = whole
    # A whole-number line ties on the number itself: over 4 is over 4.5 and
    # under 4 is under 3.5.
    pulls["over_line"] = pulls.line + np.where(whole, 0.5, 0.0)
    pulls["under_line"] = pulls.line - np.where(whole, 0.5, 0.0)
    pulls = pulls.sort_values("pulled")
    for side in ("over", "under"):
        side_quotes = quotes.rename(
            columns={
                "line": f"{side}_line",
                "p_book": f"{side}_book",
                "book_n": f"{side}_n",
                "quoted": f"{side}_quoted",
            }
        )
        pulls = pd.merge_asof(
            pulls,
            side_quotes,
            left_on="pulled",
            right_on=f"{side}_quoted",
            by=["player_key", "stat", f"{side}_line"],
            direction="backward",
            tolerance=BOOK_WINDOW,
        )
    pulls["p_over"] = pulls.over_book
    pulls["p_under"] = 1 - pulls.under_book
    offered_over = pulls.sides.ne("under") & pulls.p_over.notna()
    offered_under = pulls.sides.ne("over") & pulls.p_under.notna()
    pulls["p_over"] = pulls.p_over.where(offered_over)
    pulls["p_under"] = pulls.p_under.where(offered_under)
    return pulls[offered_over | offered_under]


def picks(priced):
    """One pick per app, player, stat and game: the stronger side at the last
    priced pull before tip-off."""
    if priced.empty:
        return priced.assign(side="", p=np.nan, books=np.nan)
    last = priced.sort_values("pulled").groupby(KEYS, as_index=False).tail(1).copy()
    over = last.p_over.fillna(-1) >= last.p_under.fillna(-1)
    last["side"] = np.where(over, "over", "under")
    p = np.where(over, last.p_over, last.p_under)
    # With a tie possible the two chances do not add to 1; the stronger side
    # is judged with ties set aside, as on the page.
    total = last.p_over + last.p_under
    both = last.whole & total.notna() & (total > 0) & (total < 1)
    last["p"] = np.where(both, p / total.where(both, 1), p)
    last["books"] = np.where(over, last.over_n, last.under_n)
    return last


def grade(chosen, box):
    """Add ``result`` (win, loss, tie, void or pending) from the box scores."""
    played = box[["player", "tip_utc", "did_not_play", "minutes", *STATS]].copy()
    played["player_key"] = played.player.map(normalize_name).astype(object)
    played["tip_utc"] = when(played.tip_utc)
    played = played.sort_values("tip_utc")
    out = pd.merge_asof(
        chosen.sort_values("tip"),
        played,
        left_on="tip",
        right_on="tip_utc",
        by="player_key",
        direction="nearest",
        tolerance=TIP_MATCH,
    )
    actual = pd.Series(np.nan, index=out.index)
    for stat in STATS:
        actual = actual.where(out.stat != stat, out[stat])
    out["actual"] = actual
    sat = out.did_not_play.fillna(False).astype(bool) | ~(out.minutes > 0)
    over_wins = out.actual > out.line
    won = np.where(out.side == "over", over_wins, out.actual < out.line)
    result = np.where(won, "win", "loss")
    result = np.where(np.isclose(out.actual, out.line), "tie", result)
    result = np.where(sat, "void", result)
    out["result"] = np.where(out.tip_utc.isna(), "pending", result)
    return out


def rate(frame):
    """Graded picks, win rate, stated chance and the calibration t."""
    graded = frame[frame.result.isin(["win", "loss"])]
    n = len(graded)
    if not n:
        return {"picks": 0}
    won = graded.result.eq("win").to_numpy(dtype=float)
    game = graded.commence_utc.astype(str) + graded.home + graded.away
    gap, t = clustered_mean_t(won - graded.p.to_numpy(), game)
    return {
        "picks": n,
        "games": int(game.nunique()),
        "win_rate": round(float(won.mean()), 4),
        "stated_chance": round(float(graded.p.mean()), 4),
        "won_less_stated": round(float(gap), 4) if n > 1 else None,
        "t": round(float(t), 2) if n > 1 and np.isfinite(t) else None,
    }


def primary(frame, min_books=0):
    """Picks at BAR or more: win rate against the break-even, and the status."""
    chosen = frame[(frame.p >= BAR) & (frame.books >= min_books)]
    graded = chosen[chosen.result.isin(["win", "loss"])]
    n = len(graded)
    out = {"picks": n, "bar": BAR, "break_even": BREAK_EVEN}
    if n < 2:
        return {**out, "status": f"waiting for the first look ({n} of {FIRST_LOOK})"}
    graded = graded.sort_values("tip")  # the first look is the first 200 by tip-off
    won = graded.result.eq("win").to_numpy(dtype=float)
    game = graded.commence_utc.astype(str) + graded.home + graded.away
    edge, t = clustered_mean_t(won - BREAK_EVEN, game)
    out.update(
        win_rate=round(float(won.mean()), 4),
        over_break_even=round(float(edge), 4),
        t=round(float(t), 2) if np.isfinite(t) else None,
    )
    if n < FIRST_LOOK:
        out["status"] = f"waiting for the first look ({n} of {FIRST_LOOK})"
    elif n < VERDICT:
        early = won[:FIRST_LOOK].mean() < STOP_BELOW
        out["status"] = (
            "stopped at the first look"
            if early
            else f"first look done ({n} of {VERDICT})"
        )
    else:
        passed = edge > 0 and np.isfinite(t) and t >= 2.0
        out["status"] = (
            "passed at the verdict" if passed else "not shown at the verdict"
        )
    return out


def summarise(frame):
    counted = frame[frame.tip >= START]
    before = frame[frame.tip < START]
    bucket = pd.cut(counted.p, BUCKETS, labels=LABELS, right=False)
    return {
        "status": "forward check; live lines, public results; not a forecast",
        "counted_from": str(START.date()),
        "picks_made": len(counted),
        "picks_made_at_the_bar": int((counted.p >= BAR).sum()),
        "results": counted.result.value_counts().to_dict(),
        "primary": primary(counted),
        f"primary_{MIN_BOOKS_CUT}_or_more_books": primary(counted, MIN_BOOKS_CUT),
        "calibration_all_picks": rate(counted),
        "by_stated_chance": {label: rate(counted[bucket == label]) for label in LABELS},
        "by_app": {app: rate(group) for app, group in counted.groupby("app")},
        "before_the_plan_not_tested": rate(before),
    }


def main():
    pulls, books = read_days(PICKEM), read_days(BOOKS)
    OUT.mkdir(parents=True, exist_ok=True)
    if pulls.empty or books.empty:
        summary = {"status": "no pick'em or sportsbook files yet", "picks_made": 0}
    else:
        chosen = picks(price(pulls, books))
        box = pd.read_parquet(BOX) if BOX.exists() else None
        if box is None:
            graded = chosen.assign(result="pending")
        else:
            graded = grade(chosen, box[box.season >= SEASON])
        summary = summarise(graded)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
