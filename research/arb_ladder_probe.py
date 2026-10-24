"""Read-only threshold-ladder arb feasibility: never authenticates or places orders.

For a lower threshold L and a higher threshold H, the portfolio YES(L)
and NO(H) pays at least $1 only if both use exactly compatible settlement
rules. Candidate quotes are not executable guarantees: the two legs do not
fill atomically, and rules have not been audited.

Usage: python -m research.arb_ladder_probe
"""

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

SERIES = ("KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT", "KXNFLRECYDS")
MAX_BOOK_QUERIES = 80
TAKER_FEE_RATE = Decimal("0.07")


def number(value):
    try:
        value = Decimal(str(value))
        return value if value.is_finite() else None
    except (ValueError, TypeError):
        return None


def player(market):
    subtitle = market.get("yes_sub_title") or ""
    match = re.fullmatch(r"\s*([\w .'-]{3,65}):\s*.+", subtitle)
    return " ".join(match.group(1).lower().split()) if match else None


def ladder_candidates(markets, series):
    """Group by series/event/player, skip ambiguous duplicate strikes."""
    groups = defaultdict(list)
    eligible = 0
    for market in markets:
        if market.get("status") not in ("active", "open"):
            continue
        name = player(market)
        strike = number(market.get("floor_strike"))
        event = market.get("event_ticker")
        ticker = market.get("ticker")
        if name and event and ticker and strike is not None and strike >= 0:
            eligible += 1
            groups[(event, name)].append((strike, market))

    candidates = []
    comparisons = 0
    for (event, name), items in groups.items():
        items.sort(key=lambda item: item[0])
        if len(items) < 2 or len(set(s for s, _ in items)) != len(items):
            continue
        for (lower, lm), (higher, hm) in zip(items, items[1:]):
            if lower >= higher:
                continue
            comparisons += 1
            no_bid_low = number(lm.get("no_bid_dollars"))
            yes_bid_high = number(hm.get("yes_bid_dollars"))
            if (
                no_bid_low is None
                or yes_bid_high is None
                or not 0 < no_bid_low < 1
                or not 0 < yes_bid_high < 1
            ):
                continue
            # Pair gross payout lower bound is $1, assuming correct rules.
            gross = no_bid_low + yes_bid_high - 1
            if gross > 0:
                candidates.append(
                    {
                        "series": series,
                        "event_ticker": event,
                        "player": name,
                        "lower_strike": str(lower),
                        "higher_strike": str(higher),
                        "buy_yes_ticker": lm["ticker"],
                        "buy_no_ticker": hm["ticker"],
                        "gross_cents_per_pair_at_list_quotes": float(100 * gross),
                    }
                )

    candidates.sort(
        key=lambda row: row["gross_cents_per_pair_at_list_quotes"], reverse=True
    )
    return candidates, {"eligible_markets": eligible, "adjacent_pairs_checked": comparisons}


def best_bid(book, side):
    """Books have YES/NO bids only, with [price, fixed-point quantity]."""
    levels = (book or {}).get(side + "_dollars") or []
    usable = []
    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price, quantity = number(level[0]), number(level[1])
        if (
            price is not None
            and quantity is not None
            and 0 < price < 1
            and quantity > 0
        ):
            usable.append((price, quantity))
    return max(usable, key=lambda value: value[0]) if usable else None


def fee(price, quantity):
    """Illustrative general Kalshi taker fee; per-order upward rounding."""
    raw = TAKER_FEE_RATE * quantity * price * (1 - price)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def check_depth(candidate, low_book, high_book, quantity_cap=10):
    low_no_bid = best_bid(low_book, "no")
    high_yes_bid = best_bid(high_book, "yes")
    if low_no_bid is None or high_yes_bid is None:
        return None
    low_price, low_quantity = low_no_bid
    high_price, high_quantity = high_yes_bid
    quantity = min(int(low_quantity), int(high_quantity), quantity_cap)
    if quantity < 1:
        return None

    yes_low_ask = 1 - low_price
    no_high_ask = 1 - high_price
    gross = quantity * (1 - yes_low_ask - no_high_ask)
    estimated_fees = fee(yes_low_ask, quantity) + fee(no_high_ask, quantity)
    net = gross - estimated_fees
    return {
        **candidate,
        "hypothetical_pairs": quantity,
        "yes_low_ask": str(yes_low_ask),
        "no_high_ask": str(no_high_ask),
        "gross_dollars": float(gross),
        "general_taker_fees_dollars": float(estimated_fees),
        "indicative_net_dollars": float(net),
        "general_fee_net_positive": net > 0,
        "rules_audited": False,
        "paired_fills_verified": False,
        "executable_arbitrage_verified": False,
    }


def run(fetch_markets, fetch_orderbook, series=SERIES, max_book_queries=80):
    """All calls are public market-data reads; no account, secrets, or orders."""
    coverage, opportunities = {}, []
    for name in series:
        markets = fetch_markets(name, status="open", historical=False)
        candidates, stats = ladder_candidates(markets, name)
        coverage[name] = {"scanned": len(markets), **stats}
        opportunities.extend(candidates)
    opportunities.sort(
        key=lambda row: row["gross_cents_per_pair_at_list_quotes"], reverse=True
    )

    depth_checked, reads = [], 0
    for candidate in opportunities:
        if reads + 2 > max_book_queries:
            break
        start = time.monotonic()
        low_book = fetch_orderbook(candidate["buy_yes_ticker"])
        high_book = fetch_orderbook(candidate["buy_no_ticker"])
        reads += 2
        result = check_depth(candidate, low_book, high_book)
        if result is None:
            continue
        elapsed = time.monotonic() - start
        result["book_fetch_seconds"] = round(elapsed, 3)
        result["temporally_usable"] = elapsed <= 2.0
        if not result["temporally_usable"]:
            result["general_fee_net_positive"] = False
        depth_checked.append(result)

    return {
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "research_only_no_order_access",
        "coverage": coverage,
        "gross_positive_list_quote_pairs": len(opportunities),
        "book_reads": reads,
        "depth_checked": len(depth_checked),
        "potential_fee_positive_quotes": sum(
            int(row["general_fee_net_positive"]) for row in depth_checked
        ),
        "verified_arbitrages": 0,
        "fee_warning": "General Kalshi taker fee only; confirm series overrides.",
        "execution_warning": "Non-atomic legs, unmatched time, unverified rules.",
        "candidates": depth_checked[:40],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default="outputs/arbitrage/kalshi_ladders_latest.json"
    )
    parser.add_argument("--max-book-queries", type=int, default=MAX_BOOK_QUERIES)
    args = parser.parse_args()
    if args.max_book_queries < 0:
        parser.error("max-book-queries must be nonnegative")
    from kalshi.api import fetch_markets, fetch_orderbook

    report = run(
        fetch_markets, fetch_orderbook, max_book_queries=args.max_book_queries
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "candidates"}, indent=2))
    print("Wrote read-only report to", output)


if __name__ == "__main__":
    main()
