"""Reproduce the saved NFL evidence review. No exchange orders or demo runs.

This summarizes a different historical taker rule and a quote-eligibility screen;
it does not simulate maker fills or estimate the profitability of live v2.
"""

import argparse
import json
import math
from pathlib import Path

import pandas as pd


def review(frame):
    settled = frame[frame.over.notna()]
    traded = settled[settled.profit_per_contract.notna()]
    receiving = settled[settled.stat.eq("receiving_yards")]
    historical = []
    for (stat, side), group in traded.groupby(["stat", "side"]):
        historical.append({"stat":stat,"side":side,"contracts":len(group),"paper_profit_dollars":round(float(group.profit_per_contract.sum()),6)})
    quote_screen = frame[
        frame.over.isna() & frame.stat.eq("receiving_yards")
        & frame.yes_bid_dollars.gt(0) & frame.yes_ask_dollars.lt(1)
        & frame.yes_ask_dollars.gt(frame.yes_bid_dollars)
    ].copy()
    spread = quote_screen.yes_ask_dollars - quote_screen.yes_bid_dollars
    quote_screen["no_price"] = (1 - quote_screen.yes_ask_dollars + .01 * spread.ge(.019999)).round(2)
    quote_screen = quote_screen[quote_screen.no_price.between(.10,.90)]
    # ONE contract per line, no second tick. Existing outlier check uses the
    # original estimated-maker-fee edge; keep it separate from the reserve.
    original_edge = 1 - quote_screen.p_over - quote_screen.no_price - .0175 * quote_screen.no_price * (1-quote_screen.no_price)
    reserved = (quote_screen.no_price * 1.1 * 100 - 1e-8).map(math.ceil) / 100
    buffered_edge = 1 - quote_screen.p_over - reserved
    eligible = original_edge.between(0,.15)
    sensitivity = {str(floor):int((eligible & buffered_edge.ge(floor)).sum()) for floor in (0,.03,.05)}
    return {
        "snapshot_latest_utc":str(frame.snapshot_utc.max()),
        "settled_games":int(settled.game_id.nunique()),
        "settled_market_lines":len(settled),
        "historical_paper_contracts":len(traded),
        "historical_paper_profit_dollars":round(float(traded.profit_per_contract.sum()),6),
        "historical_receiving_players":int(receiving.player.nunique()),
        "historical_breakdown":historical,
        "one_contract_quote_screen_by_buffered_edge_floor":sensitivity,
        "quote_screen_caveat":"Model-only, saved quotes; excludes live roster, entry-time, book coverage, queue, fill and risk-cap checks. Counts are not tradable orders or performance estimates.",
        "conclusion":"One settled game cannot establish live profitability. Separate NFL v2 fills from prior cohorts; reconcile actual fees and settlements before sizing up.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison",type=Path,default=Path("outputs/nfl/market/comparison.csv.gz"))
    args = parser.parse_args()
    print(json.dumps(review(pd.read_csv(args.comparison)),indent=2))


if __name__ == "__main__":
    main()
