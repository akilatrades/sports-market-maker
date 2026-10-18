"""NFL prop markets for the live trader (RESEARCH_LOG.md, 2026-10-16).

Builds the priced frame the trader's rules take (the same columns the NBA
projection run writes) from Kalshi's open anytime-touchdown and
receiving-yards markets: fresh quotes, kickoff from the market's
occurrence time, the NFL model's over-probability where the latest ladder
has one, and the sportsbooks' consensus where they quote the line.

Run through the trader: TRADE_MARKET=nfl python -m live.nba_trade
"""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.api import fetch_markets
from kalshi.books import attach_latest
from markets.nfl.data import load as load_nfl
from markets.nfl.data import load_injuries
from markets.nfl.roster_guard import availability, current_rosters, event_teams
from markets.nfl.kalshi import parse
from markets.nfl.paper import MODEL_SERIES, model_probabilities

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
    m["tip_utc"] = pd.to_datetime(
        m.occurrence_datetime, utc=True, format="ISO8601", errors="coerce"
    )
    m = m[m.tip_utc.notna()].copy()
    m["hours_to_tip"] = (m.tip_utc - pd.Timestamp(now)).dt.total_seconds() / 3600
    m["team"] = ""  # Set only after a verified roster/team/schedule match.
    m["game_id"] = m.event_ticker.str.split("-").str[1]  # e.g. 26OCT18CHIATL
    m["player_id"] = -1  # no roster ids here; the injury filter is NBA-only
    m["p_model"] = m.ticker.map(p_model).astype(float)
    m["injury_status"] = "UNVERIFIED"  # Never treat missing NFL availability as healthy.
    m["snapshot_utc"] = pd.Timestamp(now).isoformat(timespec="minutes")
    m = m[COLUMNS]
    m["line"] = pd.to_numeric(m.line, errors="coerce")
    return m


def candidates(now):
    """Priced NFL prop markets with model and book probabilities attached."""
    markets = []
    for series in SERIES:
        markets += fetch_markets(series, status="open", historical=False)
    if not markets:
        print("No open NFL prop markets")
        return pd.DataFrame(columns=COLUMNS)
    try:
        games, _ = load_nfl()
        p_model = model_probabilities(markets, games, now)
    except (OSError, ValueError, KeyError) as error:
        print(f"NFL model unavailable ({error}); all NFL entries blocked")
        p_model = {}
    priced = priced_frame(markets, p_model, now)
    priced = attach_latest(priced, path=BOOKS)
    priced["p_model"] = pd.to_numeric(priced.p_model, errors="coerce")

    # Fail closed for missing, stale or inconsistent game/roster/injury data.
    # ESPN's current roster cannot confirm official 90-minute inactives, so
    # questionable/out/doubtful and all unverified cases are excluded.
    try:
        import json
        from pathlib import Path

        retrieved = json.loads(Path("data/nfl/retrieval.json").read_text())
        stamp = datetime.fromisoformat(retrieved["retrieved"]).replace(tzinfo=UTC)
        if not (0 <= (pd.Timestamp(now) - pd.Timestamp(stamp)).total_seconds() <= 48 * 3600):
            raise ValueError("NFL injury report snapshot is stale")

        injuries = load_injuries()
        games, _ = load_nfl()
        matchups = {
            ticker: event_teams(ticker, date, games)
            for ticker, date in zip(
                priced.event_ticker,
                pd.to_datetime(priced.tip_utc, utc=True).dt.tz_convert(
                    "America/New_York"
                ).dt.strftime("%Y-%m-%d"),
                strict=True,
            )
        }
        needed = {
            team
            for game in matchups.values() if game is not None
            for team in game[:2]
        }
        rosters = current_rosters(needed, now=pd.Timestamp(now).to_pydatetime())
        checks = []
        for row in priced.itertuples():
            game = matchups.get(row.event_ticker)
            if game is None:
                checks.append(("", "unverified-game"))
            else:
                checks.append(availability(row.player, game, rosters, injuries))
        priced["team"] = [t or "" for t, _ in checks]
        priced["injury_status"] = [reason for _, reason in checks]
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"::warning::NFL roster check unavailable ({error}); no new orders")
        priced["injury_status"] = "UNVERIFIED"

    # A sportsbook quote is not a replacement for a missing projection.
    # Keep all unmatched and non-finite NFL model probabilities out of trading.
    missing_model = ~np.isfinite(priced.p_model)
    priced.loc[missing_model, "injury_status"] = "UNVERIFIED_MODEL"
    good = int(priced.injury_status.eq("").sum())
    print(
        f"NFL: {len(priced)} open markets, {int(priced.p_model.notna().sum())} model-priced, "
        f"{int(priced.p_book.notna().sum())} with a book line, "
        f"{good} roster/injury/model-verified"
    )
    return priced
