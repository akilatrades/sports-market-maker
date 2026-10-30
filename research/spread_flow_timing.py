"""Spread maker: quote only where both sides trade, and when (RESEARCH_LOG.md, 2026-10-30).

SIMULATED and in-sample. Pregame quotes under the v3 rule from
``research.spread_start_window`` (24-to-4-hour scan, S1+S2+S3 starts, 85-minute
floor, 8c+ spreads), one contract per side per hourly quote, held to settlement.

    python -m research.spread_flow_timing   # outputs/research/spread_flow_timing.json
"""

import json

import numpy as np
import pandas as pd

from research.spread_start_window import (
    OUT,
    SOURCES,
    fills,
    load_events,
    load_rows,
    milestone_by_type,
    select,
    starts,
    trusted_types,
)

DRAWS = 20
MIN_FILLS = 30
BINS = [(12, 24), (6, 12), (3, 6), (85 / 60, 3)]


def clustered_diff(a, b):
    """Mean pnl of a minus mean of b, event-clustered (same method as the bookline test)."""
    if a.empty or b.empty:
        return {"cents": None, "t": None}
    xa, xb = a.pnl.astype(float), b.pnl.astype(float)
    est = float(xa.mean() - xb.mean())
    infl = pd.concat(
        [(xa - xa.mean()) / len(xa), -(xb - xb.mean()) / len(xb)], ignore_index=True
    )
    groups = pd.concat([a.event_ticker, b.event_ticker], ignore_index=True)
    by = infl.groupby(groups.to_numpy()).sum()
    se = float(np.sqrt((by**2).sum()))
    return {"cents": round(100 * est, 2), "t": round(est / se, 2) if se else None}


def cents(f):
    from kalshi.stats import clustered_mean_t

    if len(f) < 10:
        return {"fills": len(f), "cents": None, "t": None}
    m, t = clustered_mean_t(f.pnl, f.event_ticker)
    return {
        "fills": len(f),
        "events": int(f.event_ticker.nunique()),
        "cents": round(100 * float(m), 2),
        "t": round(float(t), 2),
    }


def paired_share(f):
    """Share of filled contracts that end up in a YES+NO pair within their market."""
    g = f.groupby(["ticker", "side"]).size().unstack(fill_value=0)
    for s in ("yes", "no"):
        if s not in g:
            g[s] = 0
    total = g["yes"] + g["no"]
    return (
        float((2 * np.minimum(g["yes"], g["no"])).sum() / total.sum())
        if total.sum()
        else np.nan
    )


def by_series_share(f):
    out = {}
    for s, g in f.groupby("series"):
        out[s] = (paired_share(g), len(g))
    return out


def test_a(f):
    early, late = f[f.half == "earlier"], f[f.half == "later"]
    shares = {s: v for s, v in by_series_share(early).items() if v[1] >= MIN_FILLS}
    ranked = sorted(shares, key=lambda s: shares[s][0], reverse=True)
    top = set(ranked[: max(1, len(ranked) // 3)])
    sel, rest = late[late.series.isin(top)], late[~late.series.isin(top)]
    return {
        "eligible_series": len(ranked),
        "selected": sorted(top),
        "earlier_paired_share_selected": round(
            paired_share(early[early.series.isin(top)]), 3
        ),
        "earlier_paired_share_rest": round(
            paired_share(early[~early.series.isin(top)]), 3
        ),
        "later_paired_share_selected": round(paired_share(sel), 3)
        if len(sel)
        else None,
        "later_paired_share_rest": round(paired_share(rest), 3) if len(rest) else None,
        "later_selected": cents(sel),
        "later_rest": cents(rest),
        "later_selected_minus_rest": clustered_diff(sel, rest),
    }


def hours_to_start(q, known):
    return (q.event_ticker.map(known) - q.end_ts) / 3600


def test_b(f):
    out = {}
    for lo, hi in BINS:
        label = f"{round(lo, 2)}-{hi} h"
        b = f[(f.h_start >= lo) & (f.h_start < hi)]
        out[label] = {h: cents(b[b.half == h]) for h in ("earlier", "later")}
    drop = [
        k
        for k, v in out.items()
        if v["earlier"]["cents"] is not None and v["earlier"]["cents"] < 0
    ]
    late = f[f.half == "later"]
    in_drop = np.zeros(len(late), bool)
    for k in drop:
        lo, hi = [float(x) for x in k.replace(" h", "").split("-")]
        in_drop |= ((late.h_start >= lo) & (late.h_start < hi)).to_numpy()
    kept, dropped = late[~in_drop], late[in_drop]
    return {
        "bins": out,
        "dropped_bins": drop,
        "later_kept_minus_dropped": clustered_diff(kept, dropped) if drop else None,
    }


def paired_vs_one_sided(f):
    late = f[f.half == "later"].copy()
    g = late.groupby(["ticker", "side"]).size().unstack(fill_value=0)
    for s in ("yes", "no"):
        if s not in g:
            g[s] = 0
    both = set(g[(g.yes > 0) & (g.no > 0)].index)
    return {
        "markets_with_both_sides": cents(late[late.ticker.isin(both)]),
        "markets_one_side_only": cents(late[~late.ticker.isin(both)]),
    }


def main():
    r, e = load_rows(), load_events()
    by_type = milestone_by_type(e)
    types = trusted_types(e, by_type)
    known, _ = starts(e, SOURCES["S1+S2+S3"], by_type, types)
    q = select(r, known, 24).copy()
    q["h_start"] = hours_to_start(q, known)
    res = {
        "note": "SIMULATED, in-sample, exploratory (RESEARCH_LOG.md 2026-10-30)",
        "quotes": len(q),
    }
    for name, share in (("first_in_line", 1.0), ("flow_0.25", 0.25)):
        draws = [fills(q, share, s) for s in range(1 if share >= 1 else DRAWS)]
        f = draws[0] if share >= 1 else draws[len(draws) // 2]
        res[name] = {
            "all_fills": cents(f),
            "test_a": test_a(f),
            "test_b": test_b(f),
            "paired_vs_one_sided": paired_vs_one_sided(f),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spread_flow_timing.json").write_text(
        json.dumps(res, indent=1, default=float) + "\n"
    )
    print(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
