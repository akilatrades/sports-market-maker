"""A robustness search across Kalshi (RESEARCH_LOG.md, 2026-11-24, plan
written before any results). Research only; historical and simulated.

480 resting-order variants (market type x side x price band x minimum
spread) on the cross-market scan (``outputs/scan/orders_*.csv.gz``), put
through four checks:

1. parameter sensitivity: every variant on the whole period, as a grid;
2. walk-forward: each test month (January-August 2026) trades the variants
   chosen on earlier months only;
3. stress tests on the walk-forward result: haircuts, double fees, leave out
   the best month or series;
4. Monte Carlo: resampled events, and a null where every outcome is redrawn
   at the order's own price (a fair market).

    python -m research.robustness_search            # all four, about 10 min
    python -m research.robustness_search --sims 20  # a quicker null

Writes outputs/robustness_search/summary.json and grid.csv (aggregates).
"""

import argparse
import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCAN = "outputs/scan/orders_*.csv.gz"
OUT = Path("outputs/robustness_search")
COLUMNS = ["ticker", "price", "yes_bid", "yes_ask", "side", "traded", "result",
           "event_ticker", "date", "won", "pnl", "series"]  # fmt: skip

# --- the plan, fixed before any results ------------------------------------------
KINDS = ("game", "spread", "total", "part", "season", "all")
SIDES = ("yes", "no")
BANDS = [(0.02, 0.10)] + [(i / 10, (i + 1) / 10) for i in range(1, 9)] + [(0.90, 0.98)]
MIN_SPREADS = (1, 2, 4, 8)  # cents
TEST_MONTHS = [f"2026-{m:02d}" for m in range(1, 9)]
MIN_FILLS, MIN_T = 300, 2.0
HAIRCUTS = (0.02, 0.04)
PASS_HAIRCUT, PASS_T, PASS_FILLS, PASS_MONTHS, PASS_NULL = 0.02, 2.0, 1000, 5, 0.05
SIMS, SEED = 200, 20261124
PART_WORDS = ("1H", "2H", "1Q", "2Q", "3Q", "4Q", "BTTS", "FTTS", "INNING", "RFI",
              "MAP", "SET", "1P", "2P", "3P", "SCORE", "CORNERS", "HALF")  # fmt: skip


def kind_of(series):
    """Market type from the series name (KXNBAGAME, KXEPLSPREAD, ...)."""
    s = str(series).upper()
    if any(w in s.removeprefix("KX") for w in PART_WORDS):
        return "part"
    if s.endswith(("GAME", "MATCH", "FIGHT")):
        return "game"
    if s.endswith("SPREAD"):
        return "spread"
    if s.endswith("TOTAL"):
        return "total"
    return "season"


def band_of(price):
    for i, (low, high) in enumerate(BANDS):
        if low <= price < high:
            return i
    return -1


def load(pattern=SCAN):
    frames = []
    for path in sorted(glob.glob(pattern)):
        try:
            frames.append(pd.read_csv(path, usecols=lambda c: c in COLUMNS))
        except (ValueError, OSError, EOFError):
            continue  # a few scan files are not data
    d = pd.concat(frames, ignore_index=True)
    return prepare(d)


def prepare(d):
    """Filled orders only, with the fields the search needs."""
    d = d[(d.traded >= 1) & d.result.isin(["yes", "no"])].copy()
    d["kind"] = d.series.map(kind_of)
    d["band"] = d.price.map(band_of)
    d["spread_c"] = (100 * (d.yes_ask - d.yes_bid)).round().astype(int)
    d["month"] = pd.to_datetime(d.date).dt.strftime("%Y-%m")
    d["fee"] = d.won - d.price - d.pnl  # the scan's maker fee
    d = d[d.band >= 0].reset_index(drop=True)
    d["row"] = np.arange(len(d))
    return d


# --- statistics on event sums ---------------------------------------------------


def clustered(sums, counts):
    """(mean per fill, t) from per-event profit sums and fill counts."""
    sums, counts = np.asarray(sums, float), np.asarray(counts, float)
    n, g = counts.sum(), len(counts)
    if n == 0 or g < 2:
        return math.nan, math.nan
    mean = sums.sum() / n
    resid = sums - mean * counts
    var = (resid**2).sum() * g / (g - 1) / n**2
    return mean, (mean / math.sqrt(var) if var > 0 else math.nan)


def memberships(d):
    """One row per fill and variant it belongs to (variant = kind, side,
    band, minimum spread)."""
    parts = []
    for kind in ("own", "all"):
        for spread in MIN_SPREADS:
            part = d[d.spread_c >= spread]
            parts.append(
                pd.DataFrame(
                    {
                        "row": part.row,
                        "kind": part.kind if kind == "own" else "all",
                        "side": part.side,
                        "band": part.band,
                        "spread": spread,
                        "event": part.event_ticker,
                        "month": part.month,
                        "pnl": part.pnl,
                    }
                )
            )
    return pd.concat(parts, ignore_index=True)


VARIANT = ["kind", "side", "band", "spread"]


def event_sums(m, pnl="pnl"):
    return m.groupby([*VARIANT, "month", "event"], observed=True).agg(
        s=(pnl, "sum"), n=(pnl, "size")
    )


def variant_stats(es):
    """Mean, t and fills per variant from (variant, month, event) sums."""
    per_event = es.groupby([*VARIANT, "event"], observed=True)[["s", "n"]].sum()
    rows = []
    for key, g in per_event.groupby(level=VARIANT, observed=True):
        mean, t = clustered(g.s, g.n)
        rows.append((*key, int(g.n.sum()), mean, t))
    return pd.DataFrame(rows, columns=[*VARIANT, "fills", "mean", "t"])


def on_plateau(stats):
    """True where both neighbouring price bands (same kind, side, spread)
    are above zero; an end band needs its one neighbour."""
    s = stats.set_index(VARIANT)["mean"]
    out = []
    for kind, side, band, spread in stats[VARIANT].itertuples(index=False):
        ok = True
        for nb in (band - 1, band + 1):
            if 0 <= nb < len(BANDS):
                ok &= bool(s.get((kind, side, nb, spread), -1) > 0)
        out.append(ok)
    return stats.assign(plateau=out)


def chosen(stats):
    s = on_plateau(stats)
    keep = (s.fills >= MIN_FILLS) & (s["mean"] > 0) & (s.t >= MIN_T) & s.plateau
    return s[keep]


def walk_forward(d, m, es):
    """Out-of-sample fills: for each test month, the union of fills of the
    variants chosen on earlier months."""
    picked, choices = [], {}
    for month in TEST_MONTHS:
        train = es[es.index.get_level_values("month") < month]
        if train.empty:
            continue
        sel = chosen(variant_stats(train))
        choices[month] = sel[VARIANT].to_dict("records")
        if sel.empty:
            continue
        test = m[m.month == month].merge(sel[VARIANT], on=VARIANT)
        picked.append(test.row.unique())
    rows = np.unique(np.concatenate(picked)) if picked else np.array([], int)
    return d[d.row.isin(rows)], choices


def summarize(oos, haircut=0.0, pnl="pnl"):
    if oos.empty:
        return {"fills": 0}
    g = oos.assign(p=oos[pnl] - haircut).groupby("event_ticker").p.agg(["sum", "size"])
    mean, t = clustered(g["sum"], g["size"])
    months = oos.assign(p=oos[pnl] - haircut).groupby("month").p.mean()
    return {
        "fills": int(len(oos)),
        "events": int(len(g)),
        "cents_per_fill": round(100 * mean, 2),
        "t": round(t, 2) if math.isfinite(t) else None,
        "dollars_one_contract": round(float((oos[pnl] - haircut).sum()), 2),
        "months_positive": int((months > 0).sum()),
        "months": {k: round(100 * v, 2) for k, v in months.items()},
    }


def stress(oos):
    out = {f"haircut_{int(100 * h)}c": summarize(oos, h) for h in HAIRCUTS}
    out["double_fee"] = summarize(oos.assign(p2=oos.pnl - oos.fee), pnl="p2")
    if len(oos):
        best_month = oos.groupby("month").pnl.sum().idxmax()
        best_series = oos.groupby("series").pnl.sum().idxmax()
        out["without_best_month"] = {
            "month": best_month,
            **summarize(oos[oos.month != best_month]),
        }
        out["without_best_series"] = {
            "series": best_series,
            **summarize(oos[oos.series != best_series]),
        }
        out["by_kind_side"] = (
            oos.groupby(["kind", "side"])
            .pnl.agg(["size", "mean"])
            .round(4)
            .reset_index()
            .to_dict("records")
        )
    return out


def bootstrap(oos, draws=2000, seed=SEED, haircut=PASS_HAIRCUT):
    if oos.empty:
        return {}
    g = oos.assign(p=oos.pnl - haircut).groupby("event_ticker").p.sum().to_numpy()
    rng = np.random.default_rng(seed)
    totals = g[rng.integers(0, len(g), size=(draws, len(g)))].sum(axis=1)
    return {
        "haircut_cents": 100 * haircut,
        "total_dollars_p5_p50_p95": [
            round(float(x), 2) for x in np.percentile(totals, [5, 50, 95])
        ],
        "chance_of_a_loss": round(float((totals < 0).mean()), 3),
    }


def null_runs(d, m, sims=SIMS, seed=SEED):
    """The whole walk-forward on fair-market outcomes; returns their t's."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(sims):
        won = (rng.random(len(d)) < d.price.to_numpy()).astype(float)
        fake = d.assign(won=won, pnl=won - d.price.to_numpy() - d.fee.to_numpy())
        mm = m.drop(columns="pnl").merge(fake[["row", "pnl"]], on="row")
        oos, _ = walk_forward(fake, mm, event_sums(mm))
        out.append(summarize(oos, PASS_HAIRCUT).get("t") or 0.0)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sims", type=int, default=SIMS)
    args = parser.parse_args(argv)
    d = load()
    m = memberships(d)
    es = event_sums(m)
    grid = on_plateau(variant_stats(es))
    OUT.mkdir(parents=True, exist_ok=True)
    grid.assign(mean_cents=(100 * grid["mean"]).round(2)).to_csv(
        OUT / "grid.csv", index=False
    )
    oos, choices = walk_forward(d, m, es)
    main_result = summarize(oos, PASS_HAIRCUT)
    nulls = null_runs(d, m, args.sims)
    beat = (
        float(np.mean([n >= (main_result.get("t") or 0) for n in nulls]))
        if nulls
        else None
    )
    checks = {
        "fills": main_result.get("fills", 0) >= PASS_FILLS,
        "profit": (main_result.get("cents_per_fill") or 0) > 0,
        "t": (main_result.get("t") or 0) >= PASS_T,
        "months": main_result.get("months_positive", 0) >= PASS_MONTHS,
        "null": beat is not None and beat < PASS_NULL,
    }
    summary = {
        "note": "historical, simulated; first-in-line fills; maker fee",
        "data": {
            "filled_orders": int(len(d)),
            "events": int(d.event_ticker.nunique()),
            "series": int(d.series.nunique()),
            "from": d.date.min(),
            "to": d.date.max(),
        },  # fmt: skip
        "variants": int(len(grid)),
        "sensitivity_robust_variants": int(
            (
                (grid["mean"] > 0)
                & grid.plateau
                & (grid.t >= MIN_T)
                & (grid.fills >= MIN_FILLS)
            ).sum()
        ),
        "walk_forward_choices_per_month": {k: len(v) for k, v in choices.items()},
        "walk_forward_no_haircut": summarize(oos),
        "walk_forward_2c_haircut": main_result,
        "stress": stress(oos),
        "monte_carlo_events": bootstrap(oos),
        "null": {
            "sims": len(nulls),
            "share_at_least_as_good": beat,
            "t_p50_p95": [round(float(x), 2) for x in np.percentile(nulls, [50, 95])]
            if nulls
            else None,
        },  # fmt: skip
        "verdict": {"edge_found": all(checks.values()), **checks},
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
