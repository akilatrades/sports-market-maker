"""Which Kalshi resting-order edges survive a queue? (RESEARCH_LOG.md,
2026-11-24, plan written before results). Exploratory, in-sample, SIMULATED.

The cross-market scan counts a fill when one contract trades through the
order's price in the next hour (first in line). Here a fill needs at least Q
contracts traded through, as if Q - 1 contracts rested ahead of us. If an edge
lives only in the small trades, a queue removes it live.

    python -m research.queue_stress

Writes outputs/queue_stress/summary.json and grid.csv (aggregates only).
"""

import glob
import json
import math
import sys
from pathlib import Path

import pandas as pd

SCAN = "outputs/scan/orders_*.csv.gz"
OUT = Path("outputs/queue_stress")
COLUMNS = ["price", "side", "traded", "result", "event_ticker", "date", "won",
           "pnl", "series"]  # fmt: skip

# --- the plan, fixed before results ---------------------------------------------
QUEUES = (1, 5, 10, 25)
SIDES = ("yes", "no")
FIRST_HALF_END = "2026-03-01"
BAR = {"queue": 5, "mean": 0.02, "t": 3.0, "fills": 500, "events": 50}
PROP_WORDS = ("PTS", "REB", "AST", "ANYTD", "2TD", "FIRSTTD", "PASSYDS", "RSHYDS",
              "RECYDS", "PASSTDS", "KS", "OUTS", "SOA", "GOAL", "NBA2D", "NBA3D",
              "HR", "HITS", "TB", "BLK", "STL", "3PT", "SACK", "SHOTS")  # fmt: skip
COMBAT_WORDS = ("UFC", "BOXING", "FIGHT", "MMA")
RACING_WORDS = ("NASCAR", "F1", "INDYCAR", "MOTOGP")
FINANCE_WORDS = ("WTI", "BRENT", "GOLD", "SILVER", "NATGAS", "INX", "NASDAQ", "BTC",
                 "ETH", "USD", "EUR", "JPY", "YRRATE", "YRDIR", "TREAS", "FED",
                 "CPI", "COPPER", "SOL", "DOGE", "XRP")  # fmt: skip
PART_WORDS = ("1H", "2H", "1Q", "2Q", "3Q", "4Q", "BTTS", "FTTS", "INNING", "RFI",
              "MAP", "SET", "1P", "2P", "3P", "SCORE", "CORNERS", "HALF", "F5",
              "F3", "FIRST10")  # fmt: skip


def family(series):
    """Market family from the series name; first match wins."""
    s = str(series).upper().removeprefix("KX")
    if "MENTION" in s:
        return "mention"
    if any(w in s for w in COMBAT_WORDS):
        return "combat"
    if any(w in s for w in RACING_WORDS):
        return "racing"
    if any(s.endswith(w) for w in PROP_WORDS):
        return "player prop"
    if any(w in s for w in PART_WORDS):
        return "part of game"
    if s.endswith(("GAME", "MATCH")):
        return "game"
    if s.endswith("SPREAD"):
        return "spread"
    if s.endswith("TOTAL"):
        return "total"
    if any(w in s for w in FINANCE_WORDS):
        return "finance"
    return "other"


def load(pattern=SCAN):
    frames = []
    for path in sorted(glob.glob(pattern)):
        try:
            frames.append(pd.read_csv(path, usecols=lambda c: c in COLUMNS))
        except (ValueError, OSError, EOFError):
            continue  # a few scan files are not data
    return prepare(pd.concat(frames, ignore_index=True))


def prepare(d):
    d = d.copy()
    for c in ("traded", "price", "pnl", "won"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[(d.traded >= 1) & d.result.isin(["yes", "no"]) & d.pnl.notna()]
    d["family"] = d.series.map(family)
    d["first_half"] = pd.to_datetime(d.date) < pd.Timestamp(FIRST_HALF_END)
    return d.reset_index(drop=True)


def clustered(pnl, events):
    """(mean per fill, t) with errors clustered by event."""
    g = pd.DataFrame({"p": pnl, "e": events}).groupby("e").p.agg(["sum", "size"])
    n, k = g["size"].sum(), len(g)
    if n == 0 or k < 2:
        return math.nan, math.nan
    mean = g["sum"].sum() / n
    var = ((g["sum"] - mean * g["size"]) ** 2).sum() * k / (k - 1) / n**2
    return mean, (mean / math.sqrt(var) if var > 0 else math.nan)


def cell(part):
    mean, t = clustered(part.pnl, part.event_ticker)
    halves = [part[part.first_half], part[~part.first_half]]
    return {
        "fills": int(len(part)),
        "events": int(part.event_ticker.nunique()),
        "mean_cents": round(100 * mean, 2) if len(part) else None,
        "t": round(t, 2) if not math.isnan(t) else None,
        "first_half_cents": _cents(halves[0]),
        "second_half_cents": _cents(halves[1]),
    }


def _cents(part):
    return round(100 * part.pnl.mean(), 2) if len(part) else None


def grid(d):
    rows = []
    for fam in sorted(d.family.unique()) + ["all"]:
        for side in SIDES:
            base = d[(d.side == side) & ((d.family == fam) | (fam == "all"))]
            for q in QUEUES:
                rows.append({"family": fam, "side": side, "queue": q,
                             **cell(base[base.traded >= q])})  # fmt: skip
    return pd.DataFrame(rows)


def candidates(g, bar=BAR):
    c = g[
        (g.family != "all")
        & (g.queue == bar["queue"])
        & (g.mean_cents >= 100 * bar["mean"])
        & (g.t >= bar["t"])
        & (g.fills >= bar["fills"])
        & (g.events >= bar["events"])
        & (g.first_half_cents > 0)
        & (g.second_half_cents > 0)
    ]
    return c.to_dict("records")


def main(argv=None):
    d = load()
    g = grid(d)
    OUT.mkdir(parents=True, exist_ok=True)
    g.to_csv(OUT / "grid.csv", index=False)
    summary = {
        "note": "EXPLORATORY, in-sample 2025-26, SIMULATED fills from public "
        "trades. A fill needs >= queue contracts traded through the price in "
        "the hour. Profit per contract after the maker fee, cents.",
        "variants": int(len(g[g.family != "all"])),
        "bar": BAR,
        "candidates": candidates(g),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    with pd.option_context("display.width", 200, "display.max_rows", 200):
        print(g.to_string(index=False))
    print(json.dumps(summary["candidates"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
