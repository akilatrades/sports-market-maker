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
# Research only (RESEARCH_LOG.md, 2026-11-24, "Which sportsbooks to trust").
# When this environment variable names a folder, each book's own de-vigged
# price is also appended there, one file a day. Unset (the default, and on
# the trading server): nothing changes. The GitHub job sets it to a git-ignored
# folder kept in an Actions cache, because raw per-book odds are licensed and
# are never committed.
PER_BOOK_ENV = "BOOKS_PER_BOOK_DIR"
PER_BOOK_COLUMNS = [
    "event_id", "commence_utc", "book", "player_key", "stat", "line",
    "p_over", "updated_utc", "snapshot_utc",
]  # fmt: skip
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


def per_book(lines, snapshot_utc):
    """Each book's de-vigged chance of the over, for lines it quotes on both
    sides: the same arithmetic as consensus(), before the books are averaged."""
    if lines is None or lines.empty:
        return pd.DataFrame(columns=PER_BOOK_COLUMNS)
    from kalshi.books import implied

    q = lines.copy()
    q["p_raw"] = implied(q.odds)
    q["side"] = q.side.str.lower()
    for column in ("event_id", "commence_utc"):
        if column not in q:
            q[column] = ""
        q[column] = q[column].fillna("")
    keys = ["event_id", "commence_utc", "book", "player_key", "stat", "line"]
    q = q.drop_duplicates(keys + ["side"])
    wide = q.pivot_table(index=keys, columns="side", values="p_raw", aggfunc="first")
    if "over" not in wide or "under" not in wide:
        return pd.DataFrame(columns=PER_BOOK_COLUMNS)
    both = wide.dropna(subset=["over", "under"]).reset_index()
    both["p_over"] = (both.over / (both.over + both.under)).round(4)
    if "snapshot_utc" in q:
        seen = q.groupby(keys).snapshot_utc.min().rename("updated_utc").reset_index()
        both = both.merge(seen, on=keys, how="left")
    else:
        both["updated_utc"] = ""
    both["snapshot_utc"] = snapshot_utc
    return both[PER_BOOK_COLUMNS]


def save_per_book(lines, sport, now, folder=None):
    """Append per-book prices to ``folder`` (from BOOKS_PER_BOOK_DIR when not
    given). Never raises: this is research and must not stop the feed."""
    folder = folder or os.environ.get(PER_BOOK_ENV)
    if not folder:
        return 0
    try:
        rows = per_book(lines, now.isoformat(timespec="minutes"))
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        day = folder / f"{sport}_{now:%Y-%m-%d}.csv.gz"
        write_atomic(pd.concat([read_or_none(day), rows], ignore_index=True), day)
        return len(rows)
    except Exception as error:  # research must never break the odds feed
        print(f"::warning::per-book prices not saved ({type(error).__name__})")
        return 0


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
    per_book_rows = save_per_book(lines, sport, now)
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
    if per_book_rows:
        out["per_book_rows"] = per_book_rows
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
