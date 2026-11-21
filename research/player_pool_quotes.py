"""Kalshi's current bid and ask for every open NBA player prop.

For the player-pool page (research/nba_player_pool_dashboard.html), which
reads this file while it is open so its Kalshi prices stay current. Read
only: Kalshi's public market data, with no keys, no account and no orders.

One pass reads the four NBA prop series and writes
outputs/player_pool/kalshi_quotes.json:

    {"updated_utc": "...", "quotes": {"<ticker>": [yes bid, yes ask], ...}}

Prices are in dollars; null means that side has no quote. The player-pool
workflow runs a pass every few minutes on game days and publishes the file.

    python -m research.player_pool_quotes

Exit status 3 means no listed game is still ahead, so the workflow can stop.
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from kalshi.api import snapshot
from markets.nba.kalshi import SERIES

OUT = Path("outputs/player_pool/kalshi_quotes.json")
# Kalshi dates each prop about three hours after its game tips off.
GAME_LENGTH = timedelta(hours=3)
NO_GAMES_AHEAD = 3


def _price(value):
    """A quote in dollars, or None when that side of the book is empty."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return round(price, 4) if 0 < price < 1 else None


def quote_file(frame, now):
    quotes = {}
    for row in frame.itertuples(index=False):
        ticker = str(row.ticker or "")
        if ticker:
            quotes[ticker] = [_price(row.yes_bid_dollars), _price(row.yes_ask_dollars)]
    return {"updated_utc": now.isoformat(timespec="seconds"), "quotes": quotes}


def games_ahead(frame, now):
    """True while any listed prop belongs to a game that has not tipped off."""
    if frame.empty:
        return False
    ends = pd.to_datetime(frame.occurrence_datetime, utc=True, errors="coerce")
    return bool((ends - GAME_LENGTH > pd.Timestamp(now)).any())


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    now = datetime.now(UTC)
    frame = snapshot(SERIES, now=now)
    payload = quote_file(frame, now)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, allow_nan=False, separators=(",", ":"))
    path.write_text(text + "\n", "utf-8")
    ahead = games_ahead(frame, now)
    print(
        f"{len(payload['quotes'])} quotes at {payload['updated_utc']}; games ahead: {ahead}"
    )
    sys.exit(0 if ahead else NO_GAMES_AHEAD)


if __name__ == "__main__":
    main()
