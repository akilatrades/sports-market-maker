"""Compare maker quote timing and edge filters on saved 2025-26 prints.

Research-only. These are hypothetical fills using public trade-through, NOT
our place-in-queue or actual P&L. Inputs are the original historical model
and bid/ask snapshots. Cannot validate today's current roles, the 2026-27
NBA roster or live sportsbook source; no exchange actions.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.maker import fills, maker_fee
from kalshi.stats import clustered_mean_t
from research.quote_placement import load, policy_orders

OUT = Path("outputs/research/nba_quote_time_comparison.json")


def evaluate(q, trades, cutoff_hours, min_model_edge):
    """Use a PAIRED denominator, including quotes that expire upon placement.

    This is essential: a policy that cannot place the quote at its proposed
    cutoff must count as an eligible-but-unfilled opportunity (not vanish).
    """
    x = q[q.edge >= min_model_edge].copy()
    x["effective_end_ts"] = x.tip_ts - int(cutoff_hours * 3600)
    can_place = x.effective_end_ts > x.end_ts
    valid = x[can_place].copy()
    # fills() interprets tip_ts as the last allowed print time.
    valid["tip_ts"] = valid.effective_end_ts
    observed = fills(valid, trades) if len(valid) else pd.Series(dtype=float)
    x["could_fill"] = x.ticker.map(observed).fillna(0) >= 1
    x["pnl_if_fill"] = (
        (1 - x.over.astype(float))
        - x.price.astype(float)
        - maker_fee(x.price.astype(float))
    )
    x["pnl_per_eligible"] = x.pnl_if_fill.where(x.could_fill, 0)
    mean, t_stat = (
        clustered_mean_t(x.pnl_per_eligible, x.game_id)
        if len(x) > 1
        else (float("nan"), float("nan"))
    )
    return {
        "cutoff_hours_before_tip": cutoff_hours,
        "model_edge_filter": min_model_edge,
        "eligible_quotes": len(x),
        "placeable_quotes": int(can_place.sum()),
        "expired_at_submission": int((~can_place).sum()),
        "independent_games": int(x.game_id.nunique()),
        "possible_print_fill_quotes": int(x.could_fill.sum()),
        "possible_print_fill_rate": (
            round(float(x.could_fill.mean()), 4) if len(x) else None
        ),
        "hypothetical_cents_per_eligible_order": (
            round(100 * float(mean), 3) if np.isfinite(mean) else None
        ),
        "game_cluster_t": round(float(t_stat), 3) if np.isfinite(t_stat) else None,
        "hypothetical_cents_per_possible_fill": (
            round(100 * float(x.loc[x.could_fill, "pnl_if_fill"].mean()), 3)
            if x.could_fill.any()
            else None
        ),
    }


def main():
    orders, prints = load()
    # Model edge/source is from the historical simulation, NOT the live
    # sportsbook-veto policy; compare only mechanics that this file can test.
    quotes = policy_orders(orders, "improve1")
    hours = (quotes.tip_ts.astype(float) - quotes.end_ts.astype(float)) / 3600
    quotes = quotes[hours.between(2, 6)].copy()
    quotes = quotes.sort_values(["end_ts", "ticker"]).drop_duplicates(
        "ticker", keep="first"
    )
    results = [
        evaluate(quotes, prints, cutoff, minimum)
        for cutoff in (2, 1, 0.5, 0)
        for minimum in (0, 0.03)
    ]
    report = {
        "description": "Same 2025-26 snapshot and public-trade-replay; does NOT establish an edge or real fill probability.",
        "model": "Frozen 2025-26 historical NBA, not an improved 2026-27 forecast",
        "simulated_order_rule": "one print-eligible order per ticker, quoted 2-6h pre-tip",
        "source": str(Path("outputs/decompose/orders_no.csv.gz")),
        "critical_limitations": [
            "Public trade-through is not proof our newly posted order would fill.",
            "No live queue priority, order replay, cancellations or latency.",
            "No as-of validated current injury/lineup/projected-minutes data.",
            "No as-of independent sportsbook-veto replay; model-only threshold.",
            "Repeated same-game props are correlated; t grouped by game.",
            "Research policies compared on the same history, not a new holdout.",
        ],
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
