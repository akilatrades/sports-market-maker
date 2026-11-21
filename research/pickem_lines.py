"""The lines PrizePicks and Underdog post on tonight's NBA player props.

For the player-pool page's "Pick'em apps" tab, which sets each app's line
beside the sportsbooks' consensus for the same line. Read only: The Odds
API's pick'em group ("us_dfs"), the four main markets, games tipping off
within the next 18 hours. It places nothing and reads no account.

Writes outputs/pickem/nba_latest.csv, one row per app, player, stat and
line, and appends the same rows to that day's outputs/pickem/nba_<day>.csv.gz:

    app, player, player_key, stat, line, sides, home, away,
    commence_utc, updated_utc, snapshot_utc

What is kept and what is not (owner's decision, 2026-11-21, RESEARCH_LOG.md):

- Only the line each app posts and which sides it offers. The feed's price
  for a pick'em line is indicative only and is not stored.
- Nothing here touches outputs/books/. That consensus is what the live NBA
  bot prices from, and a pick'em line must never enter it.

Cost: up to 4 Odds API credits a game per pull (one per market). Whatever
starts this job, a pull is skipped while the last one is under
MIN_HOURS_BETWEEN old (about four pulls a day) and whenever fewer than
MIN_CREDITS_LEFT credits remain, so the page can never use up the credits
the bot's odds depend on.

    python -m research.pickem_lines --due     # "due" or "not due"
    python -m research.pickem_lines           # needs ODDS_API_KEY
    python -m research.pickem_lines --force   # ignore the gap, not the floor

``--due`` needs no installed packages (the workflow asks before it installs
anything), so this file imports only the standard library at the top.
"""

import argparse
import csv
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT = Path("outputs/pickem")
LATEST = OUT / "nba_latest.csv"
# The feed's group for pick'em apps. One group costs the same as one region.
REGION = "us_dfs"
# The feed's key -> the name the page shows. The group also carries other
# apps; only these two are kept.
APPS = {"prizepicks": "PrizePicks", "underdog": "Underdog"}
# Main markets only: each app's standard line. The "_alternate" markets hold
# the lines with changed payouts (PrizePicks' demons and goblins).
MARKETS = {
    "player_points": "points",
    "player_rebounds": "rebounds",
    "player_assists": "assists",
    "player_threes": "threes",
}
COLUMNS = [
    "app",
    "player",
    "player_key",
    "stat",
    "line",
    "sides",
    "home",
    "away",
    "commence_utc",
    "updated_utc",
    "snapshot_utc",
]
HOURS_AHEAD = 18  # tonight's games, not tomorrow's
MIN_HOURS_BETWEEN = 5  # about four pulls a day
MIN_CREDITS_LEFT = 15_000  # of the plan's 100,000 a month; the bot comes first
TIME_BUDGET_SECONDS = 90


def last_pull(path=None):
    """When the latest file was written (its newest snapshot_utc), or None."""
    try:
        with open(path or LATEST, newline="", encoding="utf-8") as handle:
            stamps = [row.get("snapshot_utc") for row in csv.DictReader(handle)]
    except OSError:
        return None
    times = []
    for stamp in stamps:
        try:
            when = datetime.fromisoformat(stamp or "")
        except ValueError:
            continue
        if when.tzinfo is not None:
            times.append(when)
    return max(times) if times else None


def due(now, path=None, min_hours=MIN_HOURS_BETWEEN):
    """True when there is no earlier pull, or it is at least ``min_hours`` old."""
    last = last_pull(path)
    return last is None or now - last >= timedelta(hours=min_hours)


def credits(usage):
    """Credits left on the plan as a number, or None if the feed did not say."""
    try:
        return int(float(usage.get("remaining")))
    except (AttributeError, TypeError, ValueError):
        return None


def app_lines(odds, now):
    """One row per app, player, stat and line from one event-odds reply."""
    import pandas as pd

    from kalshi.books import parse_event

    quotes = parse_event(odds, markets=MARKETS)
    quotes = quotes[quotes.book.isin(APPS)]
    rows = []
    if not quotes.empty:
        quotes = quotes.assign(side=quotes.side.astype(str).str.lower())
        grouped = quotes.groupby(["book", "player_key", "stat", "line"], sort=True)
        for (book, player_key, stat, line), group in grouped:
            sides = set(group.side) & {"over", "under"}
            if not sides:
                continue
            first = group.iloc[0]
            seen = pd.to_datetime(group.snapshot_utc, utc=True, errors="coerce")
            seen = seen.dropna()
            rows.append(
                {
                    "app": APPS[book],
                    "player": first.player,
                    "player_key": player_key,
                    "stat": stat,
                    "line": float(line),
                    "sides": "both" if len(sides) == 2 else sides.pop(),
                    "home": first.home,
                    "away": first.away,
                    "commence_utc": first.commence_utc,
                    "updated_utc": (
                        seen.min().isoformat(timespec="seconds") if len(seen) else ""
                    ),
                    "snapshot_utc": now.isoformat(timespec="minutes"),
                }
            )
    # No price column: the feed's pick'em prices are indicative and not kept.
    return pd.DataFrame(rows, columns=COLUMNS)


def pull(now, key, clock=time.monotonic):
    """Tonight's lines from both apps: (frame, summary). Spends credits."""
    import pandas as pd

    from kalshi.books import SPORT, event_odds, events

    listed, usage = events(key, sport=SPORT)  # this call is free
    summary = {"games": 0, "credits_remaining": usage.get("remaining")}
    left = credits(usage)
    if left is not None and left < MIN_CREDITS_LEFT:
        summary["note"] = f"skipped: fewer than {MIN_CREDITS_LEFT} credits left"
        return pd.DataFrame(columns=COLUMNS), summary
    start, frames = clock(), []
    for event in listed:
        tip = pd.Timestamp(event["commence_time"])
        if not now < tip <= now + timedelta(hours=HOURS_AHEAD):
            continue
        if clock() - start > TIME_BUDGET_SECONDS:
            summary["note"] = "stopped early: out of time"
            break
        odds, usage = event_odds(
            key, event["id"], sport=SPORT, markets=MARKETS, regions=REGION
        )
        frames.append(app_lines(odds, now))
        summary["games"] += 1
    summary["credits_remaining"] = usage.get("remaining")
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=COLUMNS), summary
    return pd.concat(frames, ignore_index=True), summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--due", action="store_true", help="say whether a pull is due, then stop"
    )
    parser.add_argument(
        "--force", action="store_true", help="pull even if the last one is recent"
    )
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    is_due = args.force or due(now)
    if args.due:
        print("due" if is_due else "not due")
        return 0
    if not is_due:
        print("::notice::" + json.dumps({"pickem": "not due"}))
        return 0

    import pandas as pd

    from kalshi.books import BooksError, api_key
    from live.log_books import read_or_none, write_atomic

    try:
        frame, summary = pull(now, api_key())
    except BooksError as error:
        print(f"::error::pick'em lines: {error}")
        return 1
    if frame.empty:
        # Nothing posted yet (or the pull was skipped): the last file stands.
        summary.setdefault("note", "no app lines returned")
        print("::notice::" + json.dumps(summary))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    write_atomic(frame, LATEST)
    day = OUT / f"nba_{now:%Y-%m-%d}.csv.gz"
    write_atomic(pd.concat([read_or_none(day), frame], ignore_index=True), day)
    summary["snapshot_utc"] = now.isoformat(timespec="minutes")
    summary["lines"] = {app: int(n) for app, n in frame.app.value_counts().items()}
    summary["players"] = int(frame.player_key.nunique())
    print(json.dumps(summary))
    print("::notice::" + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
