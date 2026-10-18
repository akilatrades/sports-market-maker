"""Read-only Polymarket US historical quote replay, NOT an execution backtest.

Public price history contains book-derived display prices, NOT individual
historical executions or queue-depth. Outcome-conditioned returns are a
counterfactual IF a maker order had filled, never realized or estimated P&L.

Run: python -m research.polymarket_us_replay
"""
import json
import math
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from live.compare_polymarket_us import poly_key

API = "https://gateway.polymarket.us"
OUT = Path("outputs/polymarket_us_replay/latest.json")
LEAGUES = ("nba", "nfl")
PAGE_LIMIT = 100
MAX_PAGES = 3
MAX_MARKETS_PER_LEAGUE = 20
TICK = 0.01


def get_json(path, params=None):
    """Public GET only. Never use account credentials or trading endpoints."""
    if not (
        path in {"/v1/markets", "/v1/price-history"}
        or path.startswith("/v2/leagues/")
        or (path.startswith("/v1/markets/") and path.endswith("/settlement"))
    ):
        raise ValueError("Non-research API path rejected")
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "smm-research/1.0"}),
        timeout=18,
    ) as response:
        return json.load(response)


def props_from_closed(league, get=get_json):
    """Bounded archived-market discovery with strict player-prop parsing."""
    league_info = get(f"/v2/leagues/{league}")
    tag = (league_info.get("league") or {}).get("tagId")
    if not isinstance(tag, int):
        raise ValueError(f"No US league tag for {league}")
    seen, found, counts = set(), [], {}
    # The filtered API can be empty even when unfiltered markets are present.
    # Neither an empty page nor a bounded response proves complete coverage.
    queries = {
        "typed_closed": {"closed": "true", "tagIds": tag,
                         "sportsMarketTypes": "SPORTS_MARKET_TYPE_PROP"},
        "all_closed": {"closed": "true", "tagIds": tag},
    }
    for source, filters in queries.items():
        n = 0
        for page in range(MAX_PAGES):
            data = get("/v1/markets", {**filters, "limit": PAGE_LIMIT,
                                       "offset": page * PAGE_LIMIT})
            batch = data.get("markets") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                raise ValueError("US market catalog returned unexpected format")
            n += len(batch)
            for m in batch:
                if not isinstance(m, dict):
                    continue
                slug = m.get("slug")
                if not isinstance(slug, str) or not slug or slug in seen:
                    continue
                # Parser normally refuses closed markets (for LIVE scanning).
                # Re-evaluate a copy as open solely to reuse its strict
                # player/stat/line/date parsing; no orders are created.
                key = poly_key({**m, "closed": False, "active": True}, league, {})
                if key is not None:
                    found.append((key, m))
                    seen.add(slug)
            if len(batch) < PAGE_LIMIT:
                break
        counts[source] = n
    return found, counts


def quote_candidate(points, start_ts, end_ts, tick=TICK):
    """First viable postable resting-NO bid within pregame decision window.

    longPrice=YES ask, shortPrice=NO ask, so NO bid=1-YES ask.
    These are displayed quotes, not prints and NOT an executed fill.
    """
    for p in sorted(points, key=lambda x: x.get("timestamp", 0)):
        try:
            ts = int(p["timestamp"])
            yes_ask = float(p["longPrice"])
            no_ask = float(p["shortPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (start_ts <= ts <= end_ts):
            continue
        if not (math.isfinite(yes_ask) and math.isfinite(no_ask)):
            continue
        no_bid = 1 - yes_ask
        price = round(no_bid + tick, 4)
        if not (0 < no_bid < price < no_ask < 1):
            continue
        if price > no_ask - tick + 1e-8:
            continue
        return {"timestamp": ts, "no_bid": round(no_bid, 4),
                "no_ask": round(no_ask, 4), "rest_no_price": price,
                "spread_cents": round(100 * (no_ask - no_bid), 2)}
    return None


def settle_yes(data):
    """Return exact binary YES settlement; never infer it from current prices."""
    value = data.get("settlement") if isinstance(data, dict) else None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        s = float(value)
    except (TypeError, ValueError):
        return None
    return int(s) if s in (0.0, 1.0) else None


def replay(get=get_json):
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    result = {
        "updated_utc": stamp,
        "venue": "polymarket_us",
        "mode": "historical_quote_replay_read_only",
        "model_tested": False,
        "model_reason": "No historical as-of-time forecasts linked to these exact US contracts",
        "real_fill_events": None,
        "realized_profit": None,
        "simulated_fill_probability": None,
        "maker_rebate_assumed": 0.0,
        "incentive_rewards_assumed": 0.0,
        "per_market_rule": "first postable NO bid 1c inside displayed spread 2-6h before event",
        "coverage": {},
        "quote_opportunities": [],
    }
    for league in LEAGUES:
        info = {"catalog_complete": False, "reason": "bounded first pages"}
        try:
            props, counts = props_from_closed(league, get=get)
            info["market_rows_sampled"] = counts
            info["strict_archived_prop_contracts_found"] = len(props)
            info["examined"] = min(len(props), MAX_MARKETS_PER_LEAGUE)
        except (OSError, ValueError, KeyError) as error:
            info["error"] = type(error).__name__
            result["coverage"][league] = info
            continue
        for key, market in props[:MAX_MARKETS_PER_LEAGUE]:
            slug = market["slug"]
            dt_text = market.get("gameStartTime")
            if not dt_text:
                continue
            try:
                tip = datetime.fromisoformat(str(dt_text).replace("Z", "+00:00"))
                if tip.tzinfo is None:
                    continue
            except ValueError:
                continue
            lo = int((tip - timedelta(hours=6)).timestamp())
            hi = int((tip - timedelta(hours=2)).timestamp())
            try:
                history = get("/v1/price-history", {
                    "symbol": slug, "timestamp.startTimestamp": lo,
                    "timestamp.endTimestamp": hi, "fidelity": 1,
                }).get("history")
                if not isinstance(history, list):
                    continue
                quote = quote_candidate(history, lo, hi)
                if not quote:
                    continue
                settlement = settle_yes(
                    get(f"/v1/markets/{urllib.parse.quote(slug, safe='')}/settlement")
                )
            except (OSError, ValueError, KeyError):
                continue
            row = {
                "league": league, "date_eastern": key[1], "player": key[2],
                "stat": key[3], "line": key[4], "slug": slug,
                "quote": quote, "settlement_yes": settlement,
                "order_submitted": False, "filled": None, "model_probability": None,
                "expected_edge": None,
            }
            if settlement is not None:
                # Conditional payoff is NOT a backtest P&L: execution is unknown.
                row["no_payoff_if_filled"] = round(
                    (1 - settlement) - quote["rest_no_price"], 4
                )
            result["quote_opportunities"].append(row)
        result["coverage"][league] = info
    scored = [r for r in result["quote_opportunities"] if "no_payoff_if_filled" in r]
    result["scored_quote_opportunities"] = len(scored)
    result["all_fill_counterfactual"] = {
        "not_trading_profit": True,
        "profit_per_contract_if_every_order_filled": (
            round(sum(x["no_payoff_if_filled"] for x in scored) / len(scored), 4)
            if scored else None
        ),
        "severe_selection_bias_warning":
            "Resting maker fills depend on queue priority and adverse selection; "
            "a profitable all-filled counterfactual is not an executable edge.",
    }
    result["interpretation"] = (
        "Insufficient to conclude strategy profitability or compare with Kalshi"
        if len(scored) < 30 else
        "Quote-only exploratory statistics; queue/trade data and model forecasts "
        "still required before comparing executable edge with Kalshi"
    )
    return result


def main():
    result = replay()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "coverage": result["coverage"],
        "quotes_scored": result["scored_quote_opportunities"],
        "conditional_all_filled": result["all_fill_counterfactual"],
        "interpretation": result["interpretation"],
    }, indent=2))


if __name__ == "__main__":
    main()
