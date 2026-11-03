"""Log the sportsbooks' NBA prop lines (RESEARCH_LOG.md, 2026-10-16).

Pulls every US book's prop lines from The Odds API (NBA: points, rebounds,
assists, threes, main and alternate; NFL: receiving yards), removes the vig
within each book, averages across books, and writes:

    outputs/books/<sport>_latest.csv       one row per player, stat and line
    outputs/books/<sport>_<day>.csv.gz     every snapshot that day, appended

Two scopes:

- ``full`` (default): every game in the next 36 hours, for the look-ahead.
- ``near`` (``--near``): only games tipping within the next 6.5 hours, the
  window in which the live bot places and keeps orders. Those games' rows in
  ``<sport>_latest.csv`` are replaced; other games keep their older rows,
  whose own timestamps let the bot treat them as stale. When no game is that
  close, nothing is fetched and no credits are spent.

Only the de-vigged consensus is kept (the feed's terms do not allow
redistributing bookmakers' odds). About 8 credits per NBA game, 2 per NFL
game, per refresh. Needs ODDS_API_KEY.
Run: python -m live.log_books [nba|nfl] [--near]
"""

import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from kalshi.books import SPORTS, BooksError, api_key, consensus, props

OUT = Path("outputs/books")
FULL_HOURS = 36
# NBA entries open 6 hours before tip-off and orders rest until tip-off.
NEAR_HOURS = 6.5


def merge_latest(previous, fresh):
    """Fresh games' rows replace their old ones; other games keep theirs."""
    if previous is None or previous.empty or "event_id" not in previous:
        return fresh
    if fresh.empty or "event_id" not in fresh:
        return previous
    keep = previous[~previous.event_id.isin(set(fresh.event_id))]
    return pd.concat([fresh, keep], ignore_index=True)


def read_or_none(path):
    """A previous file, or None if missing, empty or unreadable (a crash
    mid-write must not stop every later run)."""
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return None


def write_atomic(frame, path):
    """Write next to the target and rename, so a reader never sees half a file."""
    path = Path(path)
    # Same suffix (.csv or .csv.gz), so pandas picks the same compression.
    suffix = "".join(path.suffixes)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=suffix)
    os.close(fd)
    try:
        frame.to_csv(name, index=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(sport="nba", scope="full"):
    if scope not in {"full", "near"}:
        raise BooksError(f"unknown scope {scope!r}")
    now = datetime.now(UTC)
    near = scope == "near"
    lines, usage = props(
        api_key(),
        sport=sport,
        hours_ahead=NEAR_HOURS if near else FULL_HOURS,
        started_hours=0 if near else 1,
    )
    if near and lines.empty:
        out = {
            "sport": sport,
            "scope": scope,
            "games": 0,
            "note": "no game within 6.5 h",
        }
        out["credits_remaining"] = usage.get("remaining")
        print("::notice::" + json.dumps(out))
        return
    table = consensus(lines)
    table["snapshot_utc"] = now.isoformat(timespec="minutes")
    if len(lines) and "event_id" in table:
        # consensus() already keeps event_id and commence_utc per line; add teams.
        teams = lines.drop_duplicates("event_id")[["event_id", "home", "away"]]
        table = table.merge(teams, on="event_id", how="left")
    OUT.mkdir(parents=True, exist_ok=True)
    latest_path = OUT / SPORTS[sport][2]
    latest = table
    if near:
        latest = merge_latest(read_or_none(latest_path), table)
    write_atomic(latest, latest_path)
    day = OUT / f"{sport}_{now:%Y-%m-%d}.csv.gz"
    old = read_or_none(day)
    write_atomic(pd.concat([old, table], ignore_index=True), day)
    out = {
        "sport": sport,
        "scope": scope,
        "snapshot_utc": table.snapshot_utc.iloc[0] if len(table) else None,
        "games": int(lines.event_id.nunique()) if len(lines) else 0,
        "books": sorted(lines.book.unique().tolist()) if len(lines) else [],
        "lines_quoted_both_sides": int(len(table)),
        "players": int(table.player_key.nunique()) if len(table) else 0,
        "credits_remaining": usage.get("remaining"),
    }
    print(json.dumps(out))
    print("::notice::" + json.dumps(out))


if __name__ == "__main__":
    args = sys.argv[1:]
    sport = next((a for a in args if not a.startswith("--")), "nba")
    try:
        main(sport, "near" if "--near" in args else "full")
    except BooksError as error:
        print(f"::error::{error}")
        sys.exit(1)
