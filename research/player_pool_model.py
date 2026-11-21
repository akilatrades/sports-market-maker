"""The stat model's price for every open Kalshi NBA prop, for the player-pool page.

The projections job prices the props a few times a day, hours apart. The
page wants the same numbers more often, so the player-pool workflow runs
this every quarter of an hour while its price watcher is up.

It calls the projections job's own pricing function
(live.nba_projections.price_markets) on the same public inputs: box scores,
Kalshi's open markets, and ESPN's schedule, betting lines and injury report.
It writes one file, outputs/player_pool/model.json, and nothing the
projections job writes: no projections file, no paper ledger, no bet card.
No keys, no account, no orders.

    python -m live.fetch_nba_data
    python -m research.player_pool_model
"""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from kalshi.api import snapshot
from live.nba_projections import price_markets
from markets.nba.kalshi import SERIES, normalize_name, parse
from markets.nba.live import injuries, scoreboard
from research.nba_player_pool_dashboard import SLATE_COLUMNS, slate_file

OUT = Path("outputs/player_pool/model.json")
DAYS_AHEAD = 3  # today and the next two days, as the projections job reads


def price_now(now, players, games):
    """Every open prop on a game still ahead, priced by the stat model."""
    players = players[players.tip_utc < now].copy()
    season = now.year + 1 if now.month >= 8 else now.year
    eastern = pd.Timestamp(now).tz_convert("America/New_York")
    days = [(eastern + timedelta(days=i)).date() for i in range(DAYS_AHEAD)]
    schedule = pd.concat(
        [scoreboard(f"{day:%Y%m%d}", season) for day in days], ignore_index=True
    )
    schedule["tip_utc"] = pd.to_datetime(schedule.tip_utc, utc=True)
    schedule = schedule[~schedule.completed & (schedule.tip_utc > now)]
    markets = parse(snapshot(SERIES, now=now))
    if schedule.empty or markets.empty:
        return pd.DataFrame()
    priced, _ = price_markets(players, games, schedule, markets, injuries(), now=now)
    return priced


def model_file(priced, now):
    """The priced props in the shape the page reads its price file in."""
    stamp = pd.Timestamp(now).isoformat(timespec="seconds")
    if priced.empty:
        return {"snapshot_utc": stamp, "columns": SLATE_COLUMNS, "rows": []}
    frame = priced.copy()
    frame["player_key"] = frame.player.map(normalize_name)
    frame["tip_utc"] = pd.to_datetime(frame.tip_utc, utc=True).map(str)
    frame["snapshot_utc"] = stamp
    blank = frame.injury_status.isna() | frame.injury_status.astype(str).eq("")
    frame["injury_status"] = frame.injury_status.where(~blank, None)
    return slate_file(frame)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--players", default="data/player_games.parquet")
    parser.add_argument("--games", default="data/games.parquet")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    now = datetime.now(UTC)
    players = pd.read_parquet(args.players)
    games = pd.read_parquet(args.games)
    payload = model_file(price_now(now, players, games), now)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    path.write_text(text + "\n", "utf-8")
    print(f"{len(payload['rows'])} props priced at {payload['snapshot_utc']}")


if __name__ == "__main__":
    main()
