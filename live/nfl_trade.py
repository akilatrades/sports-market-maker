"""NFL prop markets for the live trader (RESEARCH_LOG.md, 2026-10-16).

Builds the priced frame the trader's rules take (the same columns the NBA
projection run writes) from Kalshi's open anytime-touchdown and
receiving-yards markets: fresh quotes, kickoff from a verified nflverse
scheduled game (never Kalshi's market occurrence timestamp), the NFL model's
has one, and the sportsbooks' consensus where they quote the line.

Run through the trader: TRADE_MARKET=nfl python -m live.nba_trade
"""

from datetime import UTC, datetime
from pathlib import Path
import json

import numpy as np
import pandas as pd

from kalshi.api import fetch_markets
from kalshi.books import attach_latest
from markets.nfl.data import load_injuries, load_schedule
from markets.nfl.roster_guard import (
    availability,
    current_rosters,
    event_teams,
    verified_kickoff,
)
from markets.nfl.kalshi import parse
from markets.nfl.paper import MAX_MODEL_AGE_HOURS, MODEL_SERIES, model_estimates

SERIES = sorted(MODEL_SERIES)  # KXNFLANYTD, KXNFLRECYDS
BOOKS = Path("outputs/books/nfl_latest.csv")
COLUMNS = [
    "snapshot_utc",
    "tip_utc",
    "event_ticker",
    "ticker",
    "player",
    "player_id",
    "team",
    "stat",
    "line",
    "p_model",
    "yes_bid_dollars",
    "yes_ask_dollars",
    "hours_to_tip",
    "injury_status",
    "game_id",
]


def priced_frame(markets, p_model, now):
    """Open markets as one priced frame; ``p_model`` maps ticker to P(over)."""
    m = pd.DataFrame(markets)
    if m.empty:
        return pd.DataFrame(columns=COLUMNS)
    m["series"] = m.ticker.str.split("-").str[0]
    m = parse(m)
    # Kalshi occurrence_datetime is NOT a reliable kickoff timestamp.
    # Candidate selection can only set time after verifying the NFL schedule.
    m["tip_utc"] = pd.NaT
    m["hours_to_tip"] = np.nan
    m["team"] = ""  # Set only after a verified roster/team/schedule match.
    m["game_id"] = m.event_ticker.str.split("-").str[1]  # e.g. 26OCT18CHIATL
    m["player_id"] = -1  # no roster ids here; the injury filter is NBA-only
    m["p_model"] = m.ticker.map(p_model).astype(float)
    m["injury_status"] = (
        "UNVERIFIED"  # Never treat missing NFL availability as healthy.
    )
    m["snapshot_utc"] = pd.Timestamp(now).isoformat(timespec="minutes")
    m = m[COLUMNS]
    m["line"] = pd.to_numeric(m.line, errors="coerce")
    return m


def candidates(now):
    """Priced NFL prop markets with model and book probabilities attached."""
    print("NFL INPUT: fetching open markets", flush=True)
    markets = []
    for series in SERIES:
        markets += fetch_markets(series, status="open", historical=False)
    if not markets:
        print("No open NFL prop markets")
        return pd.DataFrame(columns=COLUMNS)
    try:
        print("NFL INPUT: loading schedule and saved probabilities", flush=True)
        games = load_schedule()
        estimates = model_estimates(
            markets, games, now, max_age_hours=MAX_MODEL_AGE_HOURS
        )
        p_model = {ticker: e["probability"] for ticker, e in estimates.items()}
    except (OSError, ValueError, KeyError) as error:
        print(f"NFL model unavailable ({error}); all NFL entries blocked")
        games = None
        p_model = {}
        estimates = {}

    priced = priced_frame(markets, p_model, now)
    priced["model_made_utc"] = priced.ticker.map(
        {ticker: e["made_utc"] for ticker, e in estimates.items()}
    )
    priced["p_model"] = pd.to_numeric(priced.p_model, errors="coerce")

    # Unverified kickoffs never inherit Kalshi occurrence_datetime. Fail closed.
    try:
        if games is None:
            raise ValueError("NFL schedule unavailable")
        retrieved = json.loads(Path("data/nfl/retrieval.json").read_text())
        stamp = datetime.fromisoformat(retrieved["retrieved"]).replace(tzinfo=UTC)
        if not (
            0 <= (pd.Timestamp(now) - pd.Timestamp(stamp)).total_seconds() <= 48 * 3600
        ):
            raise ValueError("NFL schedule/injury snapshot is stale")

        event_dates = pd.to_datetime(
            priced.event_ticker.str.split("-").str[1].str[:7],
            format="%y%b%d",
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
        matchups = {}
        times = {}
        for ticker, date in zip(priced.event_ticker, event_dates, strict=True):
            if ticker in matchups:
                continue
            game = event_teams(ticker, date, games)
            matchups[ticker] = game
            times[ticker] = verified_kickoff(game, date, games)
        # Availability only examines these exact fixture weeks. Avoid repeatedly
        # normalizing years of irrelevant injury records for every open market.
        weeks = {game[2:] for game in matchups.values() if game is not None}
        injuries = load_injuries()
        week_index = pd.MultiIndex.from_frame(injuries[["season", "week"]])
        injuries = injuries.loc[week_index.isin(weeks)]
        print(
            f"NFL INPUT: verifying rosters with {len(injuries)} relevant injury rows",
            flush=True,
        )
        priced["tip_utc"] = pd.to_datetime(
            priced.event_ticker.map(times), utc=True, errors="coerce"
        )
        priced["hours_to_tip"] = (
            priced.tip_utc - pd.Timestamp(now)
        ).dt.total_seconds() / 3600

        needed = {
            team
            for ticker, game in matchups.items()
            if game is not None and times.get(ticker) is not None
            for team in game[:2]
        }
        rosters = current_rosters(needed, now=pd.Timestamp(now).to_pydatetime())
        checks = []
        for row in priced.itertuples():
            game = matchups.get(row.event_ticker)
            if game is None or times.get(row.event_ticker) is None:
                checks.append(("", "unverified-kickoff-or-game"))
            else:
                checks.append(availability(row.player, game, rosters, injuries))
        priced["team"] = [t or "" for t, _ in checks]
        priced["injury_status"] = [reason for _, reason in checks]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        print(
            f"::warning::NFL kickoff/roster check unavailable ({error}); no new orders"
        )
        priced["tip_utc"] = pd.NaT
        priced["hours_to_tip"] = np.nan
        priced["injury_status"] = "UNVERIFIED"

    # Books must join against the verified scheduled kickoff, not the market
    # occurrence timestamp. A sportsbook quote is never a roster substitute.
    priced = attach_latest(priced, path=BOOKS)

    # Keep missing/non-finite model probabilities and suspect kickoffs out.
    missing_model = ~np.isfinite(priced.p_model)
    priced.loc[missing_model, "injury_status"] = "UNVERIFIED_MODEL"
    good = int(priced.injury_status.eq("").sum())
    print(
        f"NFL: {len(priced)} open markets, {int(priced.p_model.notna().sum())} model-priced, "
        f"{int(priced.p_book.notna().sum())} with a book line, "
        f"{good} verified for kickoff/roster/injury/model"
    )
    return priced
