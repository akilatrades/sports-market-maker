"""Study A: adverse selection by market, Glosten-Milgrom style (RESEARCH_LOG.md,
2026-11-26, plan written before any result). SIMULATED, cross-market scan,
resting NO only.

Toxicity gap per series = profit of NO orders that filled (5+ contracts
traded through) minus profit of NO orders nothing traded through, both "if
filled" at their own price. Each month, the least toxic 20% of series (from
earlier months only) are traded.

    python -m research.toxicity

Writes outputs/toxicity/summary.json and grid.csv (aggregates only).
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research import tourist_map as TM

OUT = Path("outputs/toxicity")
TOP, QUEUE = 0.20, 5
TOPS, QUEUES = (0.10, 0.20, 0.33), (1, 5, 10)
MIN_EACH = 30
SPLIT = pd.Timestamp("2026-03-01")
BAR = {
    "t": 2.5,
    "fills": 1000,
    "events": 100,
    "months_positive": 7,
    "random_share": 0.95,
}


def gaps(part, queue=QUEUE):
    """Per series: filled minus unfilled mean profit, with both counts."""
    res = part[part.result.isin(["yes", "no"]) & part.pnl.notna()]
    filled = res[res.traded >= queue].groupby("series").pnl.agg(["mean", "size"])
    unfilled = res[res.traded <= 0].groupby("series").pnl.agg(["mean", "size"])
    g = filled.join(unfilled, lsuffix="_filled", rsuffix="_unfilled", how="inner")
    g = g[(g.size_filled >= MIN_EACH) & (g.size_unfilled >= MIN_EACH)]
    g["gap"] = g.mean_filled - g.mean_unfilled
    return g


def persistence(d):
    a, b = gaps(d[d.day < SPLIT]), gaps(d[d.day >= SPLIT])
    both = a[["gap"]].join(b[["gap"]], lsuffix="_first", rsuffix="_second", how="inner")
    all_gap = gaps(d)
    weights = all_gap.size_filled
    return {
        "series_in_both_halves": int(len(both)),
        "correlation_first_vs_second_half": round(float(both.gap_first.corr(both.gap_second)), 3)
        if len(both) > 2 else None,
        "rank_correlation": round(float(both.gap_first.corr(both.gap_second, method="spearman")), 3)
        if len(both) > 2 else None,
        "median_gap_cents": round(100 * float(all_gap.gap.median()), 2),
        "fill_weighted_gap_cents": round(100 * float(np.average(all_gap.gap, weights=weights)), 2),
        "share_of_series_with_negative_gap": round(float((all_gap.gap < 0).mean()), 3),
    }  # fmt: skip


def chosen(d, month, top, queue):
    past = d[d.day < month.to_timestamp()]
    g = gaps(past, queue)
    k = max(1, int(round(top * len(g)))) if len(g) else 0
    return set(g.gap.sort_values(ascending=False).index[:k]), sorted(g.index)


def walk(d, top, queue):
    f_all = TM.fills(d, queue)
    out, picked = [], {}
    for month in TM.MONTHS:
        sel, _ = chosen(d, month, top, queue)
        picked[str(month)] = len(sel)
        out.append(f_all[(f_all.month == month) & f_all.series.isin(sel)])
    return pd.concat(out), picked


def random_share(d, a, top, queue, rng, draws=TM.RANDOM_DRAWS):
    f_all = TM.fills(d, queue)
    totals, counts = np.zeros(draws), np.zeros(draws)
    for month in TM.MONTHS:
        _, eligible = chosen(d, month, top, queue)
        if not eligible:
            continue
        k = max(1, int(round(top * len(eligible))))
        per = f_all[f_all.month == month].groupby("series").pnl.agg(["sum", "size"])
        per = per.reindex(eligible).fillna(0)
        s, n = per["sum"].to_numpy(), per["size"].to_numpy()
        for i in range(draws):
            j = rng.choice(len(eligible), size=k, replace=False)
            totals[i] += s[j].sum()
            counts[i] += n[j].sum()
    means = np.divide(totals, counts, out=np.full(draws, np.nan), where=counts > 0)
    return round(float(np.nanmean(means < a.pnl.mean())), 3), round(
        100 * float(np.nanmedian(means)), 2
    )


def run(d):
    rng = np.random.default_rng(TM.SEED)
    grid = []
    for top in TOPS:
        for q in QUEUES:
            f, _ = walk(d, top, q)
            grid.append({"top": top, "queue": q, **TM.measure(f)})
    a, picked = walk(d, TOP, QUEUE)
    before, after = TM.measure(a), TM.measure(a, TM.HAIRCUT)
    beats, random_median = random_share(d, a, TOP, QUEUE, rng)
    passed = bool(
        (after.get("cents") or -1) > 0 and (after.get("t") or 0) >= BAR["t"]
        and after.get("fills", 0) >= BAR["fills"] and after.get("events", 0) >= BAR["events"]
        and before.get("months_positive", 0) >= BAR["months_positive"]
        and beats >= BAR["random_share"]
    )  # fmt: skip
    return pd.DataFrame(grid), {
        "note": "SIMULATED (cross-market scan 2025-26), resting NO, walk-forward by month; "
        "fills need `queue` contracts traded through. Cents per contract after the fee.",
        "persistence": persistence(d),
        "primary": {
            "before_haircut": before,
            "after_2c_haircut": after,
            "range_90_cents_before_haircut": TM.boot_range(a, rng) if len(a) else None,
            "beats_random_share": beats,
            "random_median_cents": random_median,
            "series_chosen_per_month": picked,
            "fills_by_family": a.family.value_counts().to_dict(),
        },  # fmt: skip
        "variants": 9,
        "bar": BAR,
        "pass": passed,
    }


def main(argv=None, d=None):
    grid, summary = run(TM.load() if d is None else d)
    OUT.mkdir(parents=True, exist_ok=True)
    grid.to_csv(OUT / "grid.csv", index=False)
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(grid.to_string(index=False))
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
