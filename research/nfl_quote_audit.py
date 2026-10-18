"""Read-only Kalshi Demo vs production NFL quote audit.

No authentication, no private data, no order placement. Designed for
GitHub Actions as well as local use.
"""
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

HOSTS = {
    "demo": "https://demo-api.kalshi.co/trade-api/v2",
    "prod": "https://external-api.kalshi.com/trade-api/v2",
}
SERIES = ("KXNFLRECYDS", "KXNFLANYTD")


def request(host, path, params=None):
    url = HOSTS[host] + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "smm-public-quote-diagnostic/1.0"}
            )
            with urllib.request.urlopen(req, timeout=18) as response:
                return json.load(response)
        except (OSError, ValueError) as err:
            if attempt:
                raise RuntimeError(f"{host} public GET {path}: {err}") from err
            time.sleep(1)
    raise RuntimeError("Unreachable")


def amount(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def classify(m):
    bid = amount(m.get("yes_bid_dollars"))
    ask = amount(m.get("yes_ask_dollars"))
    nbid = amount(m.get("no_bid_dollars"))
    nask = amount(m.get("no_ask_dollars"))
    if bid is None or ask is None:
        return "missing_unparseable"
    if (bid < 0 or ask > 1 or ask < 0 or bid > 1):
        return "invalid_bounds"
    if bid > 0 and ask < 1 and bid < ask:
        return "two_sided"
    if bid > 0 and ask < 1 and bid >= ask:
        return "crossed_or_locked"
    if bid > 0:
        return "yes_bid_only"
    if ask < 1:
        return "yes_ask_only"
    if nbid is not None and nbid > 0:
        return "missing_yes_ask_but_no_bid"
    if nask is not None and nask > 0:
        return "missing_yes_bid_but_no_ask"
    return "neither_side"


def collection(host, series, max_pages=4):
    rows, cursor = [], ""
    for _ in range(max_pages):
        query = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            query["cursor"] = cursor
        payload = request(host, "/markets", query)
        data = payload.get("markets")
        if not isinstance(data, list):
            raise RuntimeError(f"{host} unexpected markets schema")
        rows.extend(data)
        cursor = payload.get("cursor") or ""
        if not cursor or not data:
            return rows, False
    return rows, bool(cursor)


def best(levels):
    prices = [
        amount(row[0])
        for row in levels or []
        if isinstance(row, list) and len(row) >= 2 and (amount(row[1]) or 0) > 0
    ]
    return max((p for p in prices if p is not None), default=None)


def orderbook_check(host, market):
    ticker = market["ticker"]
    result = request(host, f"/markets/{urllib.parse.quote(ticker, safe='')}/orderbook")
    book = result.get("orderbook_fp") or result.get("orderbook") or {}
    y = best(book.get("yes_dollars") or book.get("yes"))
    n = best(book.get("no_dollars") or book.get("no"))
    raw_bid = amount(market.get("yes_bid_dollars"))
    raw_ask = amount(market.get("yes_ask_dollars"))
    derived_ask = round(1 - n, 4) if n is not None else None
    # A missing ask is often represented by 1.0000 rather than null.
    print(
        f"  BOOK {host} {ticker}: yes_bid_raw={raw_bid}, yes_bid_from_book={y},"
        f" yes_ask_raw={raw_ask}, yes_ask_from_no_bid={derived_ask},"
        f" yes_levels={len(book.get('yes_dollars') or book.get('yes') or [])},"
        f" no_levels={len(book.get('no_dollars') or book.get('no') or [])}"
    )
    if y is not None and raw_bid is not None and abs(raw_bid-y) > .011:
        print("  WARNING: YES bid differs from depth!")
    if derived_ask is not None and raw_ask is not None and abs(raw_ask-derived_ask) > .011:
        print("  WARNING: YES ask differs from NO bid depth!")


def audit():
    print("UTC", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for env in ("demo", "prod"):
        all_rows = []
        for series in SERIES:
            markets, truncated = collection(env, series)
            all_rows.extend(markets)
            print(f"{env} {series}: {len(markets)} active markets, truncated={truncated}")
        cats = Counter(classify(row) for row in all_rows)
        volumes = [amount(x.get("volume_fp")) or 0 for x in all_rows]
        bidded = [x for x in all_rows if (amount(x.get("yes_bid_dollars")) or 0) > 0]
        askable = [x for x in all_rows if (amount(x.get("yes_ask_dollars")) or 1) < 1]
        traded = [x for x in all_rows if (amount(x.get("volume_fp")) or 0) > 0]
        by_event = Counter(
            x.get("event_ticker") for x in all_rows if classify(x) == "two_sided"
        )
        ask_values = Counter(str(x.get("yes_ask_dollars")) for x in all_rows)
        bid_values = Counter(str(x.get("yes_bid_dollars")) for x in all_rows)
        print(f"{env} TOTAL: {len(all_rows)} CLASSIFICATIONS: {dict(sorted(cats.items()))}")
        print(f"{env} TWO-SIDED BY EVENT: {by_event.most_common(20)}")
        print(f"{env} ASK VALUES: zero={sum(n for val,n in ask_values.items() if amount(val)==0)}, one={sum(n for val,n in ask_values.items() if amount(val)==1)}, missing={ask_values.get('None',0)}")
        print(f"{env} BID VALUES: zero={sum(n for val,n in bid_values.items() if amount(val)==0)}, missing={bid_values.get('None',0)}")
        import csv
        from pathlib import Path
        from zoneinfo import ZoneInfo

        fixtures = []
        with Path("data/nfl/games.csv").open(newline="") as file:
            for game in csv.DictReader(file):
                if game["gameday"] != "2026-10-18" or not game["gametime"]:
                    continue
                start = datetime.strptime(
                    game["gameday"] + " " + game["gametime"], "%Y-%m-%d %H:%M"
                ).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
                prefix = game["away_team"] + game["home_team"]
                prefix = prefix.replace("JAX", "JAC").replace("LA", "LAR")
                fixtures.append((prefix, start))
        now = datetime.now(timezone.utc)
        def within_window(row):
            event = str(row.get("event_ticker", "")).split("-", 1)[-1]
            return any(
                event.endswith(teams) and 2 <= (start-now).total_seconds()/3600 <= 6
                for teams, start in fixtures
            )
        upcoming = [x for x in all_rows if within_window(x)]
        print(f"{env} TODAY IN 2-6H SCHEDULE WINDOW: markets={len(upcoming)}, two_sided={sum(classify(x)=='two_sided' for x in upcoming)}, bid_nonzero={sum((amount(x.get('yes_bid_dollars')) or 0)>0 for x in upcoming)}")
        print(
            f"{env} bids={len(bidded)} asks={len(askable)}"
            f" traded_markets={len(traded)} sum_volume={round(sum(volumes))}"
            f" best_bid_max={max((amount(x.get('yes_bid_dollars')) or 0 for x in all_rows),default=0)}"
        )
        samples = sorted(
            all_rows, key=lambda x: (classify(x)=="two_sided", amount(x.get("volume_fp")) or 0), reverse=True
        )[:3]
        for row in samples:
            fields = [
                "ticker", "status", "yes_bid_dollars", "yes_ask_dollars",
                "no_bid_dollars", "no_ask_dollars", "yes_bid_size_fp",
                "yes_ask_size_fp", "volume_fp", "open_interest_fp",
                "last_price_dollars", "yes_bid", "yes_ask"
            ]
            print(f"  SAMPLE {env}: {json.dumps({x: row.get(x) for x in fields})}")
        for row in samples[:2]:
            try:
                orderbook_check(env, row)
            except (OSError, RuntimeError) as e:
                print(f"  BOOK CHECK FAILED {env} {row['ticker']}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
