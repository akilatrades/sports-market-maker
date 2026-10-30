"""Sportsbook fair prices for spread-maker game-winner markets (shadow only).

RESEARCH_LOG.md, 2026-10-30, "Spread maker v5": a fair price from the books
for the series The Odds API covers, recorded beside Kalshi's quotes before
any rule uses it. Nothing here places, cancels or sizes an order.

Only game-winner markets ("Will <team> win?") in leagues whose Odds API key
was checked on 2026-10-30 are mapped. Within one book, the head-to-head
prices are de-vigged proportionally; books are averaged with equal weight.
"""

import re

import numpy as np

from kalshi.books import _get, implied

# Kalshi series -> The Odds API sport key (checked 2026-10-30 against
# https://the-odds-api.com/sports-odds-data/sports-apis.html). Esports and
# NWSL are not covered by the feed.
SPORT_FOR_SERIES = {
    "KXAHLGAME": "icehockey_ahl",
    "KXNCAABBGAME": "basketball_ncaab",
    "KXNCAAWBGAME": "basketball_wncaab",
    "KXPLLGAME": "lacrosse_pll",
    "KXBOXING": "boxing_boxing",
}
MAX_START_GAP_HOURS = 3.0  # Kalshi start vs the feed's commence time
MIN_NAME_SCORE = 0.5  # share of the Kalshi team's name words found in the book's
STOPWORDS = frozenset({"the", "fc", "sc", "university", "of", "state", "st"})


def fetch_h2h(key, sport, regions="us"):
    """Upcoming events with head-to-head prices (costs Odds API credits)."""
    data, usage = _get(
        f"/sports/{sport}/odds",
        {"apiKey": key, "regions": regions, "markets": "h2h", "oddsFormat": "american"},
    )
    return data, usage


def words(name):
    tokens = re.sub(r"[^a-z0-9 ]", " ", str(name).lower()).split()
    return {t for t in tokens if t not in STOPWORDS}


def name_score(kalshi_name, book_name):
    """Share of the Kalshi name's words found in the book's name (0 to 1)."""
    k, b = words(kalshi_name), words(book_name)
    return len(k & b) / len(k) if k else 0.0


def h2h_consensus(event):
    """{outcome name: (fair probability, books)} from one event's bookmakers.

    A book counts only when it prices every outcome it lists (two, or three
    with a draw); its prices are normalised to sum to one.
    """
    per_name = {}
    for book in event.get("bookmakers", []) or []:
        for market in book.get("markets", []) or []:
            if market.get("key") != "h2h":
                continue
            outcomes = [
                o
                for o in market.get("outcomes", []) or []
                if o.get("price") is not None
            ]
            if len(outcomes) < 2:
                continue
            raw = implied([o["price"] for o in outcomes])
            if not np.all(np.isfinite(raw)) or raw.sum() <= 0:
                continue
            for o, p in zip(outcomes, raw / raw.sum()):
                per_name.setdefault(o["name"], []).append(float(p))
    return {name: (float(np.mean(ps)), len(ps)) for name, ps in per_name.items()}


def match(kalshi_team, start_utc, events):
    """(event, outcome name) for the Kalshi team, or (None, reason)."""
    found = []
    for e in events:
        try:
            commence = np.datetime64(str(e.get("commence_time")).replace("Z", ""))
            gap = abs(
                (commence - np.datetime64(start_utc.replace(tzinfo=None)))
                / np.timedelta64(1, "h")
            )
        except (TypeError, ValueError):
            continue
        if gap > MAX_START_GAP_HOURS:
            continue
        for name in (e.get("home_team"), e.get("away_team")):
            score = name_score(kalshi_team, name)
            if score >= MIN_NAME_SCORE:
                found.append((score, e, name))
    if not found:
        return None, "no_match"
    found.sort(key=lambda x: x[0], reverse=True)
    if len(found) > 1 and found[0][0] == found[1][0]:
        return None, "ambiguous"
    return found[0][1], found[0][2]


def fair_yes(market, start_utc, events, min_books=2):
    """Book fair probability that the market's team wins, or None with a reason.

    ``market`` is a Kalshi market dict; its ``yes_sub_title`` names the team.
    """
    team = market.get("yes_sub_title") or ""
    event, name = match(team, start_utc, events)
    if event is None:
        return None, name
    prices = h2h_consensus(event)
    if name not in prices:
        return None, "no_price"
    p, books = prices[name]
    if books < min_books:
        return None, "too_few_books"
    return {
        "p": round(p, 4),
        "books": books,
        "event_id": event.get("id"),
        "book_team": name,
    }, "ok"
