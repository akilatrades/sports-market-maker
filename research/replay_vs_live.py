"""Does the replay's fill outcome match live? (open question 1)

The replay (research.bookline_backtest -> outputs/bookline/fills_with_book.csv.gz,
2025-26, SIMULATED: first in line at every public print at our price) and the
live NBA bot (2026-27, LIVE fills from the private export) both price resting
NO orders from the sportsbooks. For each, this measures how often NO won
compared with the sportsbooks' fair chance on the orders that FILLED:

    gap = share of fills where NO won - mean sportsbook fair chance of NO

A positive gap means fills did better than the books said. The replay and
live gaps are reported side by side, never added together, and their
difference is the adjustment a replay result needs before it is read as a
guide to live trading ("replay haircut"). Uncertainty comes from resampling
whole games (props in one game move together).

    python -m research.replay_vs_live --live ../smm-private-data/data/nba/orders

Writes outputs/research/replay_vs_live.json: counts and averages only. No
live order, price or player is written.
"""

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPLAY = Path("outputs/bookline/fills_with_book.csv.gz")
OUT = Path("outputs/research/replay_vs_live.json")
LIVE_VERSIONS = ("nba-no-v7-book-priced", "nba-no-v8-more-fills", "nba-no-v9-longshots")
# NO price bands (cents). v9 trades 65-95 only.
BANDS = {"all": (0, 100), "NO under 65c": (0, 65), "NO 65-95c": (65, 96)}
DRAWS = 2000
SEED = 20261124


def replay_fills(path=REPLAY):
    d = pd.read_csv(path)
    d = d[d.p_book.notna() & d.result.isin(["yes", "no"]) & (d.side == "no")]
    d = d[d.filled.astype(bool)]
    price = d.price if d.price.max() <= 1 else d.price / 100
    return pd.DataFrame(
        {
            "game": d.game_id.astype(str),
            "cents": (100 * price).round(),
            "fair_no": 1 - d.p_book,
            "no_won": (d.result == "no").astype(float),
        }
    )


def live_fills(folder):
    files = sorted(glob.glob(f"{folder}/*.csv"))
    if not files:
        raise SystemExit(f"no live order files in {folder}")
    o = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    o = o[
        o.strategy_version.isin(LIVE_VERSIONS)
        & (o.status == "accepted")
        & (o.filled_contracts.fillna(0) > 0)
        & o.market_settlement_net_profit_dollars.notna()
        & o.p_yes.notna()
    ]
    return pd.DataFrame(
        {
            "game": o.game_id.astype(str),
            "cents": (100 * o.avg_fill_no_price).round(),
            "fair_no": 1 - o.p_yes,
            # Settled profit above zero means NO paid out.
            "no_won": (o.market_settlement_net_profit_dollars > 0).astype(float),
        }
    )


def gap(frame, rng, draws=DRAWS):
    """(gap in points, 90% range, fills, games), resampling games."""
    if frame.empty:
        return {"fills": 0, "games": 0}
    per_game = (
        frame.assign(d=frame.no_won - frame.fair_no)
        .groupby("game")
        .d.agg(["sum", "size"])
    )
    total, count = per_game["sum"].to_numpy(), per_game["size"].to_numpy()
    point = total.sum() / count.sum()
    picks = rng.integers(0, len(per_game), size=(draws, len(per_game)))
    boots = total[picks].sum(axis=1) / count[picks].sum(axis=1)
    low, high = np.percentile(boots, [5, 95])
    return {
        "gap_points": round(100 * point, 2),
        "range_90_points": [round(100 * low, 2), round(100 * high, 2)],
        "fills": int(count.sum()),
        "games": int(len(per_game)),
        "_boots": boots,
    }


def compare(replay, live, seed=SEED):
    rng = np.random.default_rng(seed)
    out = {}
    for band, (low, high) in BANDS.items():
        r = gap(replay[(replay.cents >= low) & (replay.cents < high)], rng)
        lv = gap(live[(live.cents >= low) & (live.cents < high)], rng)
        row = {"replay_simulated": r, "live": lv}
        if r.get("fills") and lv.get("fills"):
            diff = lv["_boots"] - r["_boots"]
            row["live_minus_replay_points"] = round(
                lv["gap_points"] - r["gap_points"], 2
            )
            row["range_90_points"] = [
                round(100 * v, 2) for v in np.percentile(diff, [5, 95])
            ]
        for side in (r, lv):
            side.pop("_boots", None)
        out[band] = row
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--live", required=True, help="folder of exported NBA order CSVs"
    )
    parser.add_argument("--replay", default=str(REPLAY))
    args = parser.parse_args(argv)
    result = {
        "note": (
            "Fill outcome vs the sportsbooks' fair chance of NO, in points. Replay: "
            "2025-26, SIMULATED (first in line). Live: 2026-27 NBA v7-v9 fills. "
            "Reported side by side, never combined."
        ),
        "bands": compare(replay_fills(args.replay), live_fills(args.live)),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1) + "\n", "utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
