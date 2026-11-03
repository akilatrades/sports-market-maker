"""This server's own NBA feed, so the NBA bot no longer waits on GitHub's scheduler.

Owner request, 2026-11-03 (deploy/NBA_SERVER_FEED.md). GitHub ran its
20-minute sportsbook job 3 times between 14:00 and 04:00 UTC on 2 November,
so resting NBA orders were cancelled on stale prices. Two jobs, each run by
its own systemd timer as the trader user, both working only inside FEED (never
inside the trading checkout, whose tracked files must stay clean for deploys):

    python -m live.nba_feed books        every 20 minutes: the sportsbooks' NBA
                                         prop lines for games within 6.5 hours
                                         (live.log_books, near scope); needs
                                         ODDS_API_KEY
    python -m live.nba_feed projections  a few times a day (optional): box-score
                                         history at most once every 20 hours,
                                         then the model's prices for every open
                                         market, checked as the GitHub
                                         publisher checks them

Files land under FEED with the same relative layout the GitHub workflows use
(data/, outputs/books/, outputs/projections/); a projection pair is copied to
FEED/published/ only after it passes the publish check. The bot's input sync
(live.nba_inputs.sync) takes the newer valid copy: this one or GitHub's. Only
public GET requests; no order, credential or risk file is touched.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

FEED = Path(os.environ.get("NBA_FEED_DIR", "/home/trader/nba-feed"))
HISTORY_MAX_AGE_HOURS = 20  # box scores change once a night
KEEP_DAYS = 14  # daily book logs and projection ladders older than this are deleted
PRUNE = ("outputs/books/nba_*.csv.gz", "outputs/projections/ladders/*.csv")
PUBLISHED = Path("published")  # checked projection pair the bot reads


def enter(feed=FEED):
    """Work inside the feed folder; relative paths in the jobs resolve there."""
    feed = Path(feed)
    feed.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chdir(feed)
    return feed


def prune(feed, now=None, keep_days=KEEP_DAYS):
    """Delete this feed's own dated files older than keep_days (the disk is small)."""
    now = (now or datetime.now(UTC)).timestamp()
    gone = 0
    for pattern in PRUNE:
        for path in Path(feed).glob(pattern):
            if path.is_file() and now - path.stat().st_mtime > keep_days * 86400:
                path.unlink()
                gone += 1
    return gone


def books(feed=FEED):
    from live import log_books

    feed = enter(feed)
    log_books.main("nba", "near")
    prune(feed)


def history_age_hours(feed, now):
    try:
        retrieval = json.loads((Path(feed) / "data" / "retrieval.json").read_text())
        stamp = datetime.fromisoformat(retrieval["retrieved"].replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if stamp.tzinfo is None:
        return None
    return (now - stamp).total_seconds() / 3600


def refresh_history(feed):
    """Box-score download in its own process, so its memory is returned before
    the model runs (the server is small)."""
    code_root = str(Path(__file__).resolve().parents[1])
    env = {**os.environ, "PYTHONPATH": code_root, "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run(
        [sys.executable, "-m", "live.fetch_nba_data"], cwd=feed, env=env, check=True
    )


def projections(feed=FEED, now=None):
    from live import nba_projections
    from live.nba_inputs import atomic_write
    from live.nba_publish_check import inspect

    feed = enter(feed)
    now = now or datetime.now(UTC)
    age = history_age_hours(feed, now)
    have = (feed / "data" / "player_games.parquet").exists()
    if not have or age is None or not 0 <= age <= HISTORY_MAX_AGE_HOURS:
        refresh_history(feed)
    nba_projections.main()
    staged = feed / "outputs" / "projections"
    data = (staged / "latest.csv").read_bytes()
    meta = json.loads((staged / "latest_meta.json").read_text())
    report = inspect(data, meta, datetime.now(UTC))  # raises on a bad pair
    # Only a checked pair reaches the folder the bot reads, as on GitHub.
    atomic_write(feed / PUBLISHED / "latest.csv", data)
    atomic_write(
        feed / PUBLISHED / "latest_meta.json",
        (json.dumps(meta, indent=2) + "\n").encode(),
    )
    prune(feed)
    print("NBA FEED PROJECTIONS: " + json.dumps(report, sort_keys=True), flush=True)
    return report


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv not in (["books"], ["projections"]):
        raise SystemExit("usage: python -m live.nba_feed books|projections")
    (books if argv[0] == "books" else projections)()


if __name__ == "__main__":
    main()
