"""Spread maker backtest split by game phase: pregame, across the start, in
the game (exploratory).

RESEARCH_LOG.md, "2026-10-23: Spread maker v2, pregame only". Simulated
from the strategy sweep's hourly resting-order rows for the 64 pilot series,
spreads of 8c or more, one contract per order, first in line, held to
settlement (as in research/strategy_sweep.py). A row's order rests for the
hour after its candle ends.

- Exact phase where the event ticker carries the scheduled start (New York
  time, as the live bot reads it): pregame if the order's hour ends by the
  start, in the game if it begins at or after the start, else across it.
- For every series: the last hour before the 4-hour cutoff (k = 0) against
  earlier hours, because events often start around then.

    python -m research.spread_pregame_split   # outputs/research/spread_pregame_split.{json,md}
"""

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from live import spread_policy as P
from live.prod_spread_auto import ticker_start
from research.fill_sizing_replay import clustered_mean_t
from research.strategy_sweep import load

SCAN = Path("outputs/scan")
OUT = Path("outputs/research")
MIN_SPREAD = 0.08
FINANCIAL = {"KXBRENTD", "KXINXDUD", "KXTNOTED"}  # no event start


def rows(scan=SCAN):
    with tempfile.TemporaryDirectory() as folder:
        for series in P.SERIES:
            source = scan / f"orders_{series}.csv.gz"
            if source.exists():
                shutil.copy(source, Path(folder) / source.name)
        r = load(folder)
    r = r[r.spread >= MIN_SPREAD - 1e-9].copy()
    events = r.event_ticker.drop_duplicates()
    start = {e: ticker_start(e) for e in events}
    r["start_ts"] = r.event_ticker.map(
        lambda e: start[e].timestamp() if start.get(e) else np.nan
    )
    hours = (r.end_ts - r.start_ts) / 3600
    r["phase"] = np.select(
        [r.start_ts.isna(), hours + 1 <= 0, hours >= 0],
        ["no_time", "pregame", "in_game"],
        "across_start",
    )
    # Hours before the market's last scanned hour (0 = the last hour before
    # the 4-hour cutoff), from all rows of the market.
    last = {}
    for series in P.SERIES:
        source = scan / f"orders_{series}.csv.gz"
        if source.exists():
            x = pd.read_csv(source, usecols=["ticker", "end_ts"])
            last.update(x.groupby("ticker").end_ts.max().to_dict())
    r["k"] = (r.ticker.map(last) - r.end_ts) / 3600
    return r


def stats(x, base):
    out = {"fills": int(len(x)), "dollars": round(float(x.pnl.sum()), 2)}
    out["share_of_profit"] = round(out["dollars"] / base, 3) if base else None
    if len(x) >= 30:
        mean, t = clustered_mean_t(
            x.pnl.to_numpy(), np.ones(len(x)), x.event_ticker.to_numpy()
        )
        mid = x.day.median()
        out.update(
            events=int(x.event_ticker.nunique()),
            cents_per_contract=round(100 * float(mean), 2),
            t_event_clustered=round(float(t), 2),
            earlier_half_cents=round(100 * float(x[x.day < mid].pnl.mean()), 2),
            later_half_cents=round(100 * float(x[x.day >= mid].pnl.mean()), 2),
        )
    return out


def report(r):
    f = r[r.fill > 0]
    base = float(f.pnl.sum())
    known = f[f.phase != "no_time"]
    result = {
        "note": "SIMULATED, in-sample, first in line, 1 contract per order; exploratory",
        "all": stats(f, base),
        "ticker_start_known": {
            "share_of_fills": round(len(known) / len(f), 3),
            **{
                phase: stats(known[known.phase == phase], float(known.pnl.sum()))
                for phase in ("pregame", "across_start", "in_game")
            },
        },
        "by_hour_before_cutoff": {
            str(int(k)): stats(x, base)
            for k, x in f.groupby(f.k.clip(lower=0, upper=3).round())
        },
        "variants": {
            "all hours (v1)": stats(f, base),
            "skip the last hour": stats(f[f.k >= 1], base),
            "skip the last hour and known in-game": stats(
                f[(f.k >= 1) & ~f.phase.isin(["in_game", "across_start"])], base
            ),
            "ticker start known, pregame only": stats(f[f.phase == "pregame"], base),
            # The live v2 rule: posted at least MIN_LEAD_MINUTES before the
            # start (the scan's order rests from end_ts).
            "ticker start known, v2 rule": stats(
                f[
                    f.start_ts.notna()
                    & (f.start_ts - f.end_ts >= 60 * P.MIN_LEAD_MINUTES)
                ],
                base,
            ),
            "skip the last hour, no financial series": stats(
                f[(f.k >= 1) & ~f.series.isin(FINANCIAL)], base
            ),
        },
    }
    return result


def main():
    result = report(rows())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spread_pregame_split.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# Spread maker backtest by game phase (SIMULATED, in-sample, exploratory)",
        "",
        "| Rule | Fills | ¢/contract (t) | Earlier / later half ¢ | Share of profit |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, s in result["variants"].items():
        lines.append(
            f"| {name} | {s['fills']:,} | {s.get('cents_per_contract')} "
            f"({s.get('t_event_clustered')}) | {s.get('earlier_half_cents')} / "
            f"{s.get('later_half_cents')} | {s['share_of_profit']:.0%} |"
        )
    (OUT / "spread_pregame_split.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(result["variants"], indent=2))


if __name__ == "__main__":
    main()
