"""Execution sensitivity audit for historical resting-order scan outputs.

This is NOT a reconstructed queue. Public prints do not reveal queue position.
The script applies transparent queue-ahead thresholds to the scan's
contracts-traded-through proxy and sweeps per-contract replay haircuts.

Usage:
    python -m research.execution_robustness
    python -m research.execution_robustness --input 'outputs/scan/orders_*.csv.gz' \
        --queues 0,1,5,10,25,50 --haircuts 0,0.5,1,2,3,4

Outputs:
    outputs/execution_robustness/sensitivity.csv
    outputs/execution_robustness/summary.json
"""

import argparse
import glob
import json
import math
from pathlib import Path

import pandas as pd

DEFAULT_INPUT = "outputs/scan/orders_*.csv.gz"
OUT = Path("outputs/execution_robustness")
REQUIRED = {"traded", "pnl", "side", "event_ticker", "date", "series"}


def load(pattern):
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No scan CSVs match: {pattern}")
    frames = []
    for file in files:
        try:
            f = pd.read_csv(file)
            if REQUIRED.issubset(f.columns):
                frames.append(f)
        except (OSError, ValueError, EOFError):
            continue
    if not frames:
        raise ValueError("No usable scan files with required columns")
    d = pd.concat(frames, ignore_index=True)
    for col in ("traded", "pnl", "price"):
        if col in d:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["traded", "pnl", "event_ticker", "side", "series"])
    d = d[d.side.isin(["yes", "no"])].copy()
    d["date"] = pd.to_datetime(d.date, errors="coerce")
    d = d.dropna(subset=["date"])
    d["family"] = d.series.map(family)
    d["first_half"] = d.date < d.date.median()
    return d


def family(series):
    s = str(series).upper().removeprefix("KX")
    if "MENTION" in s:
        return "mention"
    if any(x in s for x in ("UFC", "BOXING", "FIGHT", "MMA")):
        return "combat"
    if any(x in s for x in ("NASCAR", "F1", "INDYCAR", "MOTOGP")):
        return "racing"
    if any(x in s for x in ("PTS", "REB", "AST", "HR", "HITS", "3PT", "GOAL",
                              "SHOTS", "PASSYDS", "RSHYDS", "RECYDS", "OUTS")):
        return "player prop"
    if any(x in s for x in ("1H", "2H", "1Q", "2Q", "3Q", "4Q", "BTTS",
                              "INNING", "MAP", "SET", "HALF", "F5")):
        return "part of game"
    if s.endswith(("GAME", "MATCH")):
        return "game"
    if s.endswith("SPREAD"):
        return "spread"
    if s.endswith("TOTAL"):
        return "total"
    if any(x in s for x in ("WTI", "BRENT", "GOLD", "SILVER", "NATGAS", "NASDAQ",
                              "BTC", "ETH", "FED", "CPI", "COPPER")):
        return "finance"
    return "other"


def clustered_mean_t(values, clusters):
    x = pd.DataFrame({"x": values, "cluster": clusters}).dropna()
    if len(x) < 2:
        return float("nan"), float("nan")
    g = x.groupby("cluster").x.agg(["sum", "size"])
    n, k = int(g["size"].sum()), len(g)
    mean = float(g["sum"].sum() / n)
    if k < 2:
        return mean, float("nan")
    variance = ((g["sum"] - mean * g["size"]) ** 2).sum() * k / (k - 1) / n**2
    return mean, mean / math.sqrt(variance) if variance > 0 else float("nan")


def run(d, queues, haircuts):
    rows = []
    # queue_ahead=0 approximates the original first-in-line (>=1 print).
    # For q contracts ahead, require q+1 contracts traded through.
    for family_name in sorted(d.family.unique()):
        fam = d[d.family == family_name]
        for side in ("yes", "no"):
            base = fam[fam.side == side]
            for q_ahead in queues:
                fills = base[base.traded >= q_ahead + 1].copy()
                if fills.empty:
                    for haircut in haircuts:
                        rows.append({"family": family_name, "side": side,
                                    "queue_ahead": q_ahead, "haircut_cents": haircut,
                                    "fills": 0, "events": 0, "net_cents": None,
                                    "cluster_t": None, "first_half_cents": None,
                                    "second_half_cents": None})
                    continue
                for haircut in haircuts:
                    net = fills.pnl - haircut / 100
                    mean, t = clustered_mean_t(net, fills.event_ticker)
                    h1 = net[fills.first_half].mean() if fills.first_half.any() else None
                    h2 = net[~fills.first_half].mean() if (~fills.first_half).any() else None
                    rows.append({
                        "family": family_name, "side": side,
                        "queue_ahead": q_ahead, "haircut_cents": haircut,
                        "fills": len(fills), "events": fills.event_ticker.nunique(),
                        "net_cents": round(mean * 100, 3),
                        "cluster_t": round(t, 3) if not math.isnan(t) else None,
                        "first_half_cents": round(h1 * 100, 3) if h1 is not None else None,
                        "second_half_cents": round(h2 * 100, 3) if h2 is not None else None,
                    })
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--queues", default="0,1,5,10,25,50",
                   help="estimated contracts ahead; 0 means first-in-line proxy")
    p.add_argument("--haircuts", default="0,0.5,1,2,3,4",
                   help="replay haircut in cents per filled contract")
    args = p.parse_args()
    queues = sorted({int(v) for v in args.queues.split(",")})
    haircuts = sorted({float(v) for v in args.haircuts.split(",")})
    if min(queues) < 0 or min(haircuts) < 0:
        p.error("queues and haircuts must be nonnegative")
    d = load(args.input)
    sensitivity = run(d, queues, haircuts)
    OUT.mkdir(parents=True, exist_ok=True)
    sensitivity.to_csv(OUT / "sensitivity.csv", index=False)
    meta = {
        "input_pattern": args.input, "orders_loaded": int(len(d)),
        "events": int(d.event_ticker.nunique()), "families": int(d.family.nunique()),
        "queue_ahead_scenarios": queues, "haircut_cents": haircuts,
        "warning": "Queue-ahead scenarios are sensitivity bounds, not actual queue reconstruction. Public trade prints do not reveal queue position, order cancellations, or partial-fill priority.",
        "fill_rule": "For q estimated contracts ahead, require traded >= q+1. A print count is not proof of fill.",
        "output": "sensitivity.csv",
    }
    (OUT / "summary.json").write_text(json.dumps(meta, indent=2) + "\\n")
    print(json.dumps(meta, indent=2))
    print(sensitivity.to_string(index=False))


if __name__ == "__main__":
    main()
