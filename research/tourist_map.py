"""Tourist map: a walk-forward backtest across Kalshi (RESEARCH_LOG.md,
2026-11-26, plan written before any result). SIMULATED, from the
cross-market scan; resting NO only; fills need QUEUE contracts traded
through the price in the next hour.

Each month, using only earlier orders, series are scored on three proxies
for "casual buyers, no professionals": wide spreads, low volume, young
series. The top share is traded the next month and compared with
past-profit picks, every series, and random picks.

    python -m research.tourist_map

Writes outputs/tourist_map/summary.json and grid.csv (aggregates only).
"""

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from research.queue_stress import family

SCAN = "outputs/scan/orders_*.csv.gz"
OUT = Path("outputs/tourist_map")
COLUMNS = ["series", "event_ticker", "date", "yes_bid", "yes_ask", "volume",
           "traded", "pnl", "result", "side"]  # fmt: skip

# --- the plan, fixed before results ---------------------------------------------
MONTHS = pd.period_range("2025-11", "2026-08", freq="M")
TOP, QUEUE = 0.20, 5
TOPS, QUEUES = (0.10, 0.20, 0.33), (1, 5, 10)
MIN_ORDERS, MIN_PAST_FILLS = 30, 10
OLD_DAYS = 14  # series seen in the scan's first two weeks count as old
HAIRCUT = 0.02
RANDOM_DRAWS, BOOT_DRAWS, SEED = 2000, 2000, 20261126
BAR = {
    "t": 2.5,
    "fills": 1000,
    "events": 100,
    "months_positive": 7,
    "random_share": 0.95,
}


def load(pattern=SCAN):
    frames = []
    for path in sorted(glob.glob(pattern)):
        try:
            frames.append(pd.read_csv(path, usecols=lambda c: c in COLUMNS))
        except (ValueError, OSError, EOFError):
            continue
    return prepare(pd.concat(frames, ignore_index=True))


def prepare(d):
    d = d[d.side == "no"].copy()
    for c in ("yes_bid", "yes_ask", "volume", "traded", "pnl"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["day"] = pd.to_datetime(d.date, errors="coerce")
    d = d.dropna(subset=["day"])
    d["month"] = d.day.dt.to_period("M")
    d["spread"] = d.yes_ask - d.yes_bid
    first = d.groupby("series").day.transform("min")
    d["first_day"] = first
    d["old"] = first < d.day.min() + pd.Timedelta(days=OLD_DAYS)
    d["mention"] = d.series.str.contains("MENTION")
    d["family"] = d.series.map(family)
    return d.reset_index(drop=True)


def fills(d, queue):
    return d[(d.traded >= queue) & d.result.isin(["yes", "no"]) & d.pnl.notna()]


def scores(past, month_start):
    """Score per series from orders before the month: mean percentile rank
    of wide spread, low volume and young age."""
    g = past.groupby("series").agg(
        orders=("pnl", "size"), spread=("spread", "median"), volume=("volume", "median"),
        first_day=("first_day", "first"), old=("old", "first"),
    )  # fmt: skip
    g = g[g.orders >= MIN_ORDERS].copy()
    age = (month_start - g.first_day).dt.days.astype(float)
    g["age"] = np.where(g.old, np.inf, age)
    g["score"] = (
        g.spread.rank(pct=True) + (-g.volume).rank(pct=True) + (-g.age).rank(pct=True)
    ) / 3
    return g


def picks(d, month, top, queue, how):
    start = month.to_timestamp()
    past = d[d.day < start]
    g = scores(past, start)
    if g.empty:
        return set(), set(g.index)
    if how == "tourist":
        ranked = g.score
    else:  # "momentum": past profit per fill at the same queue
        f = fills(past[past.series.isin(g.index)], queue)
        per = f.groupby("series").pnl.agg(["mean", "size"])
        ranked = per[per["size"] >= MIN_PAST_FILLS]["mean"]
    k = max(1, int(round(top * len(ranked))))
    return set(ranked.sort_values(ascending=False).index[:k]), set(g.index)


def measure(f, haircut=0.0):
    if len(f) < 2:
        return {"fills": int(len(f))}
    mean, t = clustered_mean_t(f.pnl.to_numpy() - haircut, f.event_ticker.to_numpy())
    by_month = f.groupby("month").pnl.mean()
    return {"fills": int(len(f)), "events": int(f.event_ticker.nunique()),
            "series": int(f.series.nunique()),
            "cents": round(100 * float(mean), 2),
            "t": round(float(t), 2) if math.isfinite(t) else None,
            "months_positive": int((by_month > 0).sum()), "months": int(len(by_month))}  # fmt: skip


def boot_range(f, rng, draws=BOOT_DRAWS):
    e = f.groupby("event_ticker").pnl.agg(["sum", "size"])
    s, n = e["sum"].to_numpy(), e["size"].to_numpy()
    idx = rng.integers(0, len(e), size=(draws, len(e)))
    means = s[idx].sum(1) / n[idx].sum(1)
    return [round(100 * float(x), 2) for x in np.percentile(means, [5, 95])]


def walk(d, top, queue, how):
    """Fills traded by a strategy over the test months."""
    out, chosen = [], {}
    f_all = fills(d, queue)
    for month in MONTHS:
        f = f_all[f_all.month == month]
        if how == "all":
            sel = set(f.series)
        else:
            sel, _ = picks(d, month, top, queue, how)
        chosen[str(month)] = len(sel)
        out.append(f[f.series.isin(sel)])
    return pd.concat(out), chosen


def random_share(d, chosen_fills, top, queue, rng, draws=RANDOM_DRAWS):
    """Share of random same-size picks that the chosen mean beats."""
    f_all = fills(d, queue)
    totals = np.zeros(draws)
    counts = np.zeros(draws)
    for month in MONTHS:
        start = month.to_timestamp()
        eligible = sorted(scores(d[d.day < start], start).index)
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
    chosen = chosen_fills.pnl.mean()
    return round(float(np.nanmean(means < chosen)), 3), round(
        100 * float(np.nanmedian(means)), 2
    )


def age_table(d, queue=QUEUE):
    f = fills(d[d.month.isin(MONTHS)], queue).copy()
    age = (f.day - f.first_day).dt.days
    f["age"] = np.select([f.old, age < 30, age < 90], ["old", "under 30 days", "30-90 days"],
                         "over 90 days")  # fmt: skip
    return {a: measure(g) for a, g in f.groupby("age")}


def run(d):
    rng = np.random.default_rng(SEED)
    grid = []
    for how in ("tourist", "momentum"):
        for top in TOPS:
            for q in QUEUES:
                f, _ = walk(d, top, q, how)
                grid.append({"strategy": how, "top": top, "queue": q, **measure(f)})
    for q in QUEUES:
        f, _ = walk(d, TOP, q, "all")
        grid.append({"strategy": "all", "top": 1.0, "queue": q, **measure(f)})
    a, chosen = walk(d, TOP, QUEUE, "tourist")
    after = measure(a, HAIRCUT)
    beats, random_median = random_share(d, a, TOP, QUEUE, rng)
    no_mention = measure(a[~a.mention], HAIRCUT)
    primary = {
        "before_haircut": measure(a),
        "after_2c_haircut": after,
        "range_90_cents_before_haircut": boot_range(a, rng) if len(a) else None,
        "beats_random_share": beats,
        "random_median_cents": random_median,
        "without_mentions_after_haircut": no_mention,
        "series_chosen_per_month": chosen,
        "fills_by_family": a.family.value_counts().to_dict(),
        "top_series": a.groupby("series").pnl.agg(["size", "mean"]).sort_values("size", ascending=False)
        .head(15).assign(mean=lambda x: (100 * x["mean"]).round(2)).to_dict("index"),
    }  # fmt: skip
    before = primary["before_haircut"]
    passed = bool(
        (after.get("cents") or -1) > 0
        and (after.get("t") or 0) >= BAR["t"]
        and after.get("fills", 0) >= BAR["fills"]
        and after.get("events", 0) >= BAR["events"]
        and before.get("months_positive", 0) >= BAR["months_positive"]
        and beats >= BAR["random_share"]
        and (no_mention.get("cents") or -1) > 0
    )
    return pd.DataFrame(grid), {
        "note": "SIMULATED (cross-market scan, 2025-26), resting NO, walk-forward by "
        "month (Nov 2025-Aug 2026); fills need `queue` contracts traded through. "
        "Cents per contract after the maker fee. Not a forecast.",
        "variants": 25,
        "bar": BAR,
        "primary": primary,
        "age_effect_queue_5": age_table(d),
        "pass": passed,
    }


def main(argv=None):
    grid, summary = run(load())
    OUT.mkdir(parents=True, exist_ok=True)
    grid.to_csv(OUT / "grid.csv", index=False)
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    with pd.option_context("display.width", 200):
        print(grid.to_string(index=False))
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
