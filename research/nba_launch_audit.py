"""Reproduce the October 18 launch audit using saved production-market history.

No exchange writes, no demo fills, no parameter search. This reanalysis is
discovery evidence, not a new out-of-sample test. Run from the repo root.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

OUT = Path("outputs/launch_audit_20261018")


def summary(values, clusters):
    x = np.asarray(values, dtype=float)
    c = np.asarray(clusters)
    valid = np.isfinite(x) & pd.notna(c)
    x, c = x[valid], c[valid]
    if not len(x):
        return {"rows": 0, "events": 0}
    mean = x.mean()
    grouped = pd.DataFrame({"x": x, "c": c}).groupby("c").x.agg(["sum", "size"])
    g = len(grouped)
    se = (
        np.sqrt(np.square(grouped["sum"] - grouped["size"] * mean).sum() * g / (g - 1))
        / len(x)
        if g > 1
        else np.nan
    )
    crit = student_t.ppf(0.975, g - 1) if g > 1 else np.nan
    rng = np.random.default_rng(20261018)
    boot = []
    if g > 1:
        sums, sizes = grouped["sum"].to_numpy(), grouped["size"].to_numpy()
        for _ in range(5000):
            idx = rng.integers(0, g, g)
            boot.append(sums[idx].sum() / sizes[idx].sum())
    return {
        "rows": len(x),
        "events": g,
        "cents": float(mean * 100),
        "t": float(mean / se) if se > 0 else None,
        "ci95_cents": [float((mean - crit * se) * 100), float((mean + crit * se) * 100)]
        if g > 1
        else None,
        "bootstrap_ci95_cents": (np.quantile(boot, [0.025, 0.975]) * 100).tolist()
        if boot
        else None,
        "two_sided_p": float(2 * student_t.sf(abs(mean / se), g - 1))
        if se > 0
        else None,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inputs = [
        Path("outputs/bookline/fills_with_book.csv.gz"),
        Path("outputs/scan/table.csv"),
        Path("outputs/paper_markets/orders.csv"),
    ]
    f = pd.read_csv(inputs[0])
    f["edge_used"] = f.book_edge.where(f.p_book.notna(), f.model_edge_c)
    subsets = {
        "all_sampled_no_print_fills": f,
        "book_veto_original": f[f.p_book.notna() & (f.book_edge >= 0)],
        "model_veto_original": f[f.model_edge_c >= 0],
        "baseline_book_or_model": f[f.edge_used >= 0],
        "current_price_and_edge_caps": f[
            f.price.between(0.1, 0.9) & f.edge_used.between(0, 0.15)
        ],
        "opening_two_books_price_edge_caps": f[
            f.price.between(0.1, 0.9) & f.book_edge.between(0, 0.15) & (f.book_n >= 2)
        ],
    }
    nba = {name: summary(v.pnl_if_filled, v.game_id) for name, v in subsets.items()}
    v = subsets["book_veto_original"]
    nba["original_by_month"] = {
        str(k): summary(g.pnl_if_filled, g.game_id) for k, g in v.groupby("month")
    }
    nba["original_by_season_type"] = {
        str(k): summary(g.pnl_if_filled, g.game_id) for k, g in v.groupby("season_type")
    }
    nba["opening_by_stat"] = {
        str(k): summary(g.pnl_if_filled, g.game_id)
        for k, g in subsets["opening_two_books_price_edge_caps"].groupby("stat")
    }
    # Fee-bound scenario: whole-contract cent rounding, not a claim about
    # historical fees actually charged on these hypothetical orders.
    v = subsets["opening_two_books_price_edge_caps"].copy()
    fee = np.ceil(0.0175 * v.price * (1 - v.price) * 100 - 1e-12) / 100
    adjusted = v.pnl_no_fee - fee
    nba["opening_with_one_contract_fee_bound"] = summary(adjusted, v.game_id)
    nba["opening_fee_bound_positive_edge"] = summary(
        adjusted[(1 - v.p_book - v.price - fee) > 0],
        v.game_id[(1 - v.p_book - v.price - fee) > 0],
    )
    nba["stress_cents_per_captured_contract"] = {
        f"extra_{drag}c": float(adjusted.mean() * 100 - drag) for drag in (0, 1, 2, 4)
    }
    nba["warning"] = (
        "All NBA rows here were preselected as possible historical fills. No unfilled-order denominator, actual queue, current roster gate, current fee schedule or full pilot-budget replay is available in this file. Do not call this live P&L or launch-version backtest."
    )
    table = pd.read_csv(inputs[1])
    scanned = table.no_fills.notna()
    family = 2 * int(scanned.sum())
    scan = {
        "listed_series": len(table),
        "series_with_no_fill_statistics": int(scanned.sum()),
        "nominal_passes": int(table.passes.fillna(False).sum()),
        "minimum_side_tests": family,
        "warning": "Additional windows, prices and filters make the true search family larger. Correlated outcomes and expiry after resolution can invalidate a scan even with a small adjusted p value.",
    }
    selected = {}
    selected_names = [
        "KXBTC",
        "KXCPI",
        "KXITFMATCH",
        "KXLALIGASPREAD",
        "KXNASCARRACE",
        "KXNCAAMB1HSPREAD",
        "KXNWSLSPREAD",
    ]
    for series in selected_names:
        path = Path("outputs/scan") / f"orders_{series}.csv.gz"
        inputs.append(path)
        o = pd.read_csv(path)
        no = o[o.side.eq("no")].copy()
        hit = no.traded >= 1
        stats = summary(no.loc[hit, "pnl"], no.loc[hit, "event_ticker"])
        stats["placed_rows"] = len(no)
        stats["print_fill_rate"] = float(hit.mean())
        stats["cents_per_placed_order"] = float(no.pnl.where(hit, 0).mean() * 100)
        stats["bonferroni_p_lower_bound_family"] = (
            min(1.0, stats["two_sided_p"] * family)
            if stats.get("two_sided_p") is not None
            else None
        )
        unique = no.loc[hit].sort_values("end_ts").drop_duplicates("ticker")
        stats["first_possible_fill_per_ticker"] = summary(
            unique.pnl, unique.event_ticker
        )
        stats["dates"] = [str(no.date.min()), str(no.date.max())]
        selected[path.name.removeprefix("orders_").removesuffix(".csv.gz")] = stats
    paper = pd.read_csv(inputs[2])
    settled = paper[paper.status.eq("settled") & (paper.filled_contracts > 0)].copy()
    paper_results = {}
    for name, v in settled.groupby("series"):
        stats = summary(v.profit / v.filled_contracts, v.event_ticker)
        stats.update(
            profit_dollars=float(v.profit.sum()),
            contracts=float(v.filled_contracts.sum()),
            weighted_cents=float(v.profit.sum() / v.filled_contracts.sum() * 100),
            dates=[str(v.day.min()), str(v.day.max())],
        )
        paper_results[name] = stats
    result = {
        "as_of_utc": "2026-10-18",
        "nba": nba,
        "broad_scan": scan,
        "selected_series": selected,
        "later_paper": paper_results,
        "source_sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs
        },
    }
    (OUT / "results.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "nba": {k: v for k, v in nba.items() if k in subsets},
                "broad_scan": scan,
                "selected": selected,
                "later_paper": paper_results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
