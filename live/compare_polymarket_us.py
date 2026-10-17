"""Read-only price discovery: Polymarket US vs public Kalshi prop markets.

This module NEVER authenticates, places or cancels orders. Research candidate
matches require independent human verification of settlement terms and fees.
Run: python -m live.compare_polymarket_us
"""

import json
import math
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from kalshi.api import fetch_markets
from markets.nba.kalshi import SERIES as NBA_SERIES
from markets.nfl.kalshi import SERIES as NFL_SERIES

OUT = Path("outputs/cross_exchange")
API = "https://gateway.polymarket.us"
LEAGUES = ("nba", "nfl")
SERIES = {
    "nba": NBA_SERIES,
    "nfl": {k: NFL_SERIES[k] for k in ("KXNFLANYTD", "KXNFLRECYDS")},
}
MAX_EVENT_PAGES = 6
PAGE_LIMIT = 100
MAX_BBOS = 80

STAT_TERMS = (
    ("receiving_yards", r"(?:receiving yards?|rec yds?)"),
    ("passing_yards", r"(?:passing yards?|pass yds?)"),
    ("rushing_yards", r"(?:rushing yards?|rush yds?)"),
    ("points", r"(?:points?|pts)"),
    ("rebounds", r"(?:rebounds?|rebs?)"),
    ("assists", r"(?:assists?|asts?)"),
    ("threes", r"(?:three.pointers?|3.pointers?|threes?)"),
    ("skill_tds", r"(?:anytime touchdown|to score a touchdown)"),
)


def get_json(path, params=None, timeout=18):
    """Only public GETs against the documented Polymarket US gateway."""
    if not path.startswith(("/v2/leagues/", "/v1/markets/")):
        raise ValueError("unsupported read-only path")
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(
        url, headers={"User-Agent": "sports-props-research/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def normalize_name(name):
    ascii_name = unicodedata.normalize("NFKD", str(name)).encode(
        "ascii", "ignore"
    ).decode()
    words = re.sub(r"[^a-z ]", " ", ascii_name.lower()).split()
    return " ".join(
        w for w in words if w not in {"jr", "sr", "ii", "iii", "iv", "v"}
    )


def east_date(timestamp):
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None  # fail closed on ambiguous event dates
        return dt.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except ValueError:
        return None


def market_stat(text):
    s = str(text).lower()
    for stat, pattern in STAT_TERMS:
        if re.search(pattern, s):
            return stat
    return None


def threshold_from_question(question, stat):
    """Only exact over/at-least semantics. No assumptions about unders."""
    s = str(question).lower().replace(",", "")
    if stat == "skill_tds":
        return 0.5 if re.search(r"anytime touchdown|score a touchdown", s) else None
    if not stat:
        return None
    # "30+ points" or "at least 30 points", both mean OVER 29.5.
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*\+\s*(?:points?|rebounds?|assists?|threes?|3.pointers?|receiving yards?|passing yards?)",
        s,
    )
    if m:
        return float(m.group(1)) - 0.5
    m = re.search(r"at least\s+(\d+(?:\.\d+)?)", s)
    if m:
        return float(m.group(1)) - 0.5
    m = re.search(r"(?:over|more than)\s+(\d+(?:\.\d+)?)", s)
    if m:
        return float(m.group(1))
    return None


def poly_player(market):
    subject = market.get("subject") or {}
    if isinstance(subject, dict):
        who = subject.get("name") or subject.get("displayName")
        if who:
            return normalize_name(who)
    # Only accept explicit "Player: 25+ points" syntax, not a vague keyword.
    q = str(market.get("question") or market.get("title") or "")
    match = re.match(r"^\s*([A-Za-zÀ-ÿ.'\- ]{4,60}):\s*", q)
    return normalize_name(match.group(1)) if match else ""


def poly_key(market, league, event):
    if market.get("active") is False or market.get("closed") is True:
        return None
    if market.get("sportsMarketTypeV2") != "SPORTS_MARKET_TYPE_PROP":
        return None
    question = market.get("question") or market.get("title") or ""
    stat = market_stat(question)
    player = poly_player(market)
    line = threshold_from_question(question, stat)
    date = east_date(
        market.get("gameStartTime")
        or event.get("startTime")
        or event.get("eventDate")
    )
    if not (stat and player and date and line is not None):
        return None
    return (league, date, player, stat, line)


def kalshi_key(market, league, series_stat):
    ticker = market.get("event_ticker", "").split("-")
    if len(ticker) < 2:
        return None
    try:
        date = datetime.strptime(ticker[1][:7], "%y%b%d").date().isoformat()
    except ValueError:
        return None
    subtitle = market.get("yes_sub_title") or market.get("title") or ""
    name = str(subtitle).split(":")[0].split(" records ")[0]
    player = normalize_name(name)
    strike = market.get("floor_strike")
    try:
        line = float(strike)
        if not math.isfinite(line):
            return None
    except (TypeError, ValueError):
        if series_stat == "skill_tds":
            line = 0.5
        else:
            plus = re.search(r"(\d+)\+\s*$", str(subtitle))
            if not plus:
                return None
            line = float(plus.group(1)) - 0.5
    return (league, date, player, series_stat, line) if player else None


def fetch_polymarket_events(league, get=get_json):
    events = []
    complete = False
    for page in range(MAX_EVENT_PAGES):
        result = get(
            f"/v2/leagues/{league}/events",
            {"limit": PAGE_LIMIT, "offset": page * PAGE_LIMIT},
        )
        if not isinstance(result, dict) or not isinstance(result.get("events"), list):
            raise ValueError(f"Unexpected Polymarket US {league} response")
        batch = result["events"]
        events.extend(batch)
        if len(batch) < PAGE_LIMIT:
            complete = True
            break
    return events, complete


def extract_poly(events, league):
    output = {}
    considered = 0
    for event in events:
        if not isinstance(event, dict) or event.get("closed") is True:
            continue
        for market in event.get("markets") or []:
            if not isinstance(market, dict):
                continue
            considered += 1
            key = poly_key(market, league, event)
            if key and market.get("slug"):
                output.setdefault(key, []).append(market)
    return output, considered


def extract_kalshi(league, fetch=fetch_markets):
    keyed, total = {}, 0
    for series, stat in SERIES[league].items():
        markets = fetch(series, status="open", historical=False)
        total += len(markets)
        for market in markets:
            key = kalshi_key(market, league, stat)
            if key:
                keyed.setdefault(key, []).append(market)
    return keyed, total


def maybe_price(value):
    if isinstance(value, dict):
        value = value.get("value")
    try:
        price = float(value)
        if math.isfinite(price) and 0 <= price <= 1:
            return price
    except (TypeError, ValueError):
        pass
    return None


def compare(kalshi, poly, get=get_json, max_bbos=MAX_BBOS):
    keys = sorted(set(kalshi) & set(poly))
    results, queried = [], 0
    for key in keys:
        if len(kalshi[key]) != 1 or len(poly[key]) != 1:
            continue  # ambiguous mapping; never choose a favorable price
        km, pm = kalshi[key][0], poly[key][0]
        slug = pm["slug"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,180}", str(slug)):
            continue
        if queried >= max_bbos:
            break
        bbo = get(f"/v1/markets/{urllib.parse.quote(slug, safe='')}/bbo")
        queried += 1
        md = bbo.get("marketData", {}) if isinstance(bbo, dict) else {}
        kb, ka = maybe_price(km.get("yes_bid_dollars")), maybe_price(
            km.get("yes_ask_dollars")
        )
        pb, pa = maybe_price(md.get("bestBid")), maybe_price(md.get("bestAsk"))
        if None in (kb, ka, pb, pa) or not (0 < kb <= ka < 1 and 0 < pb <= pa < 1):
            continue
        results.append({
            "league": key[0],
            "game_date_eastern": key[1],
            "player": key[2],
            "stat": key[3],
            "line": key[4],
            "kalshi_ticker": km["ticker"],
            "polymarket_us_slug": slug,
            "kalshi_yes_bid": kb,
            "kalshi_yes_ask": ka,
            "polymarket_yes_bid": pb,
            "polymarket_yes_ask": pa,
            # Midprice divergence is NOT an executable cross-exchange arbitrage.
            "mid_gap_cents": round(100 * ((pb + pa) / 2 - (kb + ka) / 2), 2),
            "manual_rules_review_required": True,
            "fee_adjusted_edge": None,
            "executable_arbitrage": False,
        })
    return results, len(keys), queried


def run(poly_get=get_json, kalshi_fetch=fetch_markets):
    if os.environ.get("KALSHI_ENV", "prod").lower() != "prod":
        raise RuntimeError("Read-only comparison requires public Kalshi PROD quotes")
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    pairs, coverage = [], {}
    for league in LEAGUES:
        events, complete = fetch_polymarket_events(league, get=poly_get)
        poly, observed = extract_poly(events, league)
        kalshi, ktotal = extract_kalshi(league, fetch=kalshi_fetch)
        matches, intersect, fetched = compare(kalshi, poly, get=poly_get)
        pairs.extend(matches)
        coverage[league] = {
            "polymarket_us_events_scanned": len(events),
            "polymarket_us_market_rows_scanned": observed,
            "polymarket_us_strict_prop_markets": sum(map(len, poly.values())),
            "kalshi_markets_scanned": ktotal,
            "strict_candidate_keys": intersect,
            "bbo_requests": fetched,
            "priced_pairs_needing_rules_review": len(matches),
            "pagination_complete": complete,
            "bbo_scan_capped": fetched == MAX_BBOS and intersect > MAX_BBOS,
        }
    return {
        "updated_utc": stamp,
        "status": "research_only_no_order_access",
        "venue": "polymarket_us",
        "reference_venue": "kalshi_public_production",
        "comparison": "YES best bid/ask; mid gaps only, NOT arbitrage or net edge",
        "manual_contract_equivalence_verified": False,
        "fees_verified": False,
        "coverage": coverage,
        "candidates": sorted(
            pairs, key=lambda x: abs(x["mid_gap_cents"]), reverse=True
        )[:30],
    }


def main():
    result = run()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(result, indent=2) + "\n")
    with (OUT / "history.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "updated_utc": result["updated_utc"],
                    "coverage": result["coverage"],
                    "candidate_count": len(result["candidates"]),
                }
            )
            + "\n"
        )
    # Keep a rolling 7-day / 42-run observation window without growing GitHub
    # forever. Each entry is an observation, not an execution.
    path = OUT / "history.jsonl"
    path.write_text("\n".join(path.read_text().splitlines()[-42:]) + "\n")
    print(
        json.dumps(
            {"updated_utc": result["updated_utc"], "coverage": result["coverage"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
