"""Where is the NO edge thicker? Slices of the 2025-26 replay (exploratory).

Plan: RESEARCH_LOG.md, "2026-10-22: Where is the NO edge thicker?
(exploratory plan)", parts A (who is on the other side) and B (being first
in line). Simulated and in-sample; nothing here changes the live rules.

Orders: the replay orders under the v5 filter (one contract, 0-15¢ of model
edge, NO 5-95¢), no caps. Fills as if first in line (flow share 1.0: at
least one contract traded through our price before tip) and at flow share
0.25 (expected fill 1 - 0.75^n). A slice is "promising" only if its cents
per filled contract beat the rest of the season with a game-clustered t of
at least 2, the difference is positive in both halves of the season, and it
has at least 1,000 fills.

    python -m research.explore_edge [PUBLIC_CHECKOUT]   # writes outputs/research/explore_edge.{json,md}
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.article_tests import load_candles
from research.fill_sizing_replay import clustered_mean_t, load_orders

OUT = Path("outputs/research")
SPLIT = pd.Timestamp("2026-02-09").date()
MIN_FILLS = 1000
EDGE = (0.0, 0.15)
BAND = (0.05, 0.95)
ET = "America/New_York"


def unix(series):
    stamps = pd.to_datetime(series, utc=True, format="ISO8601")
    return stamps.dt.tz_convert(None).to_numpy().astype("datetime64[s]").astype("int64")


def eligible(orders):
    o = orders[orders.edge.between(EDGE[0] - 1e-9, EDGE[1] + 1e-9)]
    return o[o.price.between(*BAND)].copy()


def add_features(o, candles, orders):
    """Slice variables, each known when the order is posted."""
    o = o.copy()
    tip = pd.to_datetime(o.tip_ts, unit="s", utc=True).dt.tz_convert(ET)
    o["fill_1"] = (np.floor(o.through) >= 1).astype(float)
    o["fill_q"] = 1 - 0.75 ** np.floor(o.through)
    o["half"] = np.where(o.day < SPLIT, "first", "second")
    o["no_price"] = pd.cut(
        o.price,
        [0.0, 0.15, 0.30, 0.50, 0.70, 0.85, 1.0],
        right=False,
        labels=["5-15¢", "15-30¢", "30-50¢", "50-70¢", "70-85¢", "85-95¢"],
    )
    gap = o.line - o.model_mean
    o["line_minus_mean"] = pd.qcut(gap, 5, labels=[f"q{i}" for i in range(1, 6)])
    # Trading before posting: hourly candles on file start about 7 hours before tip.
    c = candles[["ticker", "end_ts", "volume"]].merge(
        o[["ticker", "end_ts", "game_id"]].rename(columns={"end_ts": "post_ts"}),
        on="ticker",
    )
    before = c[c.end_ts <= c.post_ts]
    vol = before.groupby("ticker").volume.sum()
    o["market_volume"] = o.ticker.map(vol).fillna(0.0)
    o["market_volume_q"] = pd.qcut(
        o.market_volume.rank(method="first"), 5, labels=[f"q{i}" for i in range(1, 6)]
    )
    # The whole game's prop volume up to 5 hours before tip (all markets in the game).
    allc = candles[["ticker", "end_ts", "volume"]].merge(
        orders[["ticker", "game_id", "tip_ts"]], on="ticker"
    )
    gv = allc[allc.end_ts <= allc.tip_ts - 5 * 3600].groupby("game_id").volume.sum()
    o["game_volume"] = o.game_id.map(gv).fillna(0.0)
    games = o.drop_duplicates("game_id").set_index("game_id").game_volume
    edges = games.rank(method="first")
    game_q = pd.qcut(edges, 5, labels=[f"q{i}" for i in range(1, 6)])
    o["game_volume_q"] = o.game_id.map(game_q)
    minutes = tip.dt.hour * 60 + tip.dt.minute
    o["tip_time"] = pd.cut(
        minutes,
        [0, 19 * 60 + 30, 21 * 60, 24 * 60],
        right=False,
        labels=["before 7:30 pm", "7:30-8:59 pm", "9 pm or later"],
    )
    o["weekend"] = np.where(tip.dt.dayofweek >= 5, "weekend", "weekday")
    o["season_part"] = o.season_type
    o["stat_type"] = o.series
    spread = ((o.yes_ask - o.yes_bid) * 100).round()
    o["spread"] = pd.cut(
        spread, [0, 1.5, 2.5, 4.5, 100], labels=["1¢", "2¢", "3-4¢", "5¢+"]
    )
    age = (o.end_ts - unix(o.open_time)) / 3600
    o["market_age"] = pd.cut(
        age, [-1e9, 24, 48, 1e9], right=False, labels=["<24 h", "24-48 h", "48 h+"]
    )
    return o


SLICES = {
    "A. NO price": "no_price",
    "A. Line minus model mean (quintiles, low to high)": "line_minus_mean",
    "A. Market volume before posting (quintiles)": "market_volume_q",
    "A. Whole-game prop volume before posting (quintiles)": "game_volume_q",
    "A. Tip-off time (Eastern)": "tip_time",
    "A. Weekend or weekday": "weekend",
    "A. Season part": "season_part",
    "A. Stat": "stat_type",
    "B. Spread at posting": "spread",
    "B. Market age at posting": "market_age",
}


def weighted_difference(y, flag, weight, clusters):
    """Weighted mean of y where flag minus where not, and its game-clustered t."""
    y, f, w = (np.asarray(a, float) for a in (y, flag, weight))
    X = np.column_stack([np.ones(len(y)), f])
    Xw = X * w[:, None]
    bread = np.linalg.inv(X.T @ Xw)
    beta = bread @ (Xw.T @ y)
    resid = y - X @ beta
    scores = pd.DataFrame(Xw * resid[:, None]).groupby(np.asarray(clusters)).sum()
    g = len(scores)
    cov = bread @ (scores.to_numpy().T @ scores.to_numpy()) @ bread * g / (g - 1)
    se = float(np.sqrt(cov[1, 1]))
    return float(beta[1]), float(beta[1] / se) if se > 0 else np.nan


def slice_rows(o, column):
    rows = []
    for label in [x for x in pd.unique(o[column].dropna())]:
        inside = o[column].eq(label).to_numpy()
        part = o[inside]
        fills = float(part.fill_1.sum())
        mean, t = clustered_mean_t(part.pnl_c, part.fill_1, part.game_id)
        mean_q, t_q = clustered_mean_t(part.pnl_c, part.fill_q, part.game_id)
        diff, t_diff = weighted_difference(o.pnl_c, inside, o.fill_1, o.game_id)
        diff_q, t_diff_q = weighted_difference(o.pnl_c, inside, o.fill_q, o.game_id)
        halves = {}
        for h in ("first", "second"):
            hh = o[o.half.eq(h)]
            flag = hh[column].eq(label).to_numpy()
            if flag.any() and (~flag).any() and hh.fill_1[flag].sum() > 1:
                halves[h] = (
                    100 * weighted_difference(hh.pnl_c, flag, hh.fill_1, hh.game_id)[0]
                )
            else:
                halves[h] = np.nan
        promising = bool(
            t_diff >= 2
            and fills >= MIN_FILLS
            and all(np.isfinite(v) and v > 0 for v in halves.values())
        )
        rows.append(
            {
                "bin": str(label),
                "eligible_orders": len(part),
                "fill_rate": float(part.fill_1.mean()),
                "fills": fills,
                "cents_per_contract": 100 * mean,
                "t": t,
                "per_100_orders_cents": 100
                * 100
                * float((part.fill_1 * part.pnl_c).mean()),
                "vs_rest_cents": 100 * diff,
                "t_vs_rest": t_diff,
                "vs_rest_first_half": halves["first"],
                "vs_rest_second_half": halves["second"],
                "cents_per_contract_q25": 100 * mean_q,
                "vs_rest_cents_q25": 100 * diff_q,
                "t_vs_rest_q25": t_diff_q,
                "promising": promising,
            }
        )
    order = (
        {str(x): i for i, x in enumerate(o[column].cat.categories)}
        if hasattr(o[column], "cat")
        else {}
    )
    return sorted(rows, key=lambda r: order.get(r["bin"], r["bin"]))


def improvable_share(orders, candles, hours=(2, 3, 4, 5, 6)):
    """Share of markets whose spread is 2¢ or more at each hour before tip."""
    c = candles.merge(orders[["ticker", "tip_ts"]], on="ticker")
    out = {}
    for h in hours:
        last = (
            c[c.end_ts <= c.tip_ts - h * 3600]
            .sort_values("end_ts")
            .drop_duplicates("ticker", keep="last")
        )
        two = last[
            (last.yes_bid > 0) & (last.yes_ask < 1) & (last.yes_ask > last.yes_bid)
        ]
        out[f"{h}h"] = {
            "markets": len(two),
            "share_spread_2c_plus": float(
                ((two.yes_ask - two.yes_bid).round(4) >= 0.02).mean()
            ),
        }
    return out


def this_season_spreads(root="."):
    """2026-27 public snapshots: spread by whether the rung has a two-book line.

    Kalshi snapshots (data/kalshi/2027) 2-6 hours before tip, rungs mapped
    to player, stat, line and tip-off through the projection ladders, and the
    sportsbook files (outputs/books) for rungs with an exact line quoted by
    at least two books.
    """
    root = Path(root)
    snaps = sorted((root / "data/kalshi/2027").glob("*.csv.gz"))
    ladders = sorted((root / "outputs/projections/ladders").glob("*.csv"))
    books = sorted((root / "outputs/books").glob("nba_20*.csv.gz"))
    if not (snaps and ladders and books):
        return None
    cols = ["snapshot_utc", "series", "ticker", "yes_bid_dollars", "yes_ask_dollars"]
    d = pd.concat([pd.read_csv(f, usecols=cols) for f in snaps])
    d = d[d.series.isin(["KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT"])]
    use = ["ticker", "player_key", "stat", "line", "tip_utc"]
    lad = pd.concat([pd.read_csv(f, usecols=use) for f in ladders])
    d = d.merge(lad.drop_duplicates("ticker", keep="last"), on="ticker", how="inner")
    snap = pd.to_datetime(d.snapshot_utc, utc=True, format="ISO8601")
    tip = pd.to_datetime(d.tip_utc, utc=True, format="ISO8601")
    hours = (tip - snap).dt.total_seconds() / 3600
    bid, ask = d.yes_bid_dollars.astype(float), d.yes_ask_dollars.astype(float)
    d = d[(bid > 0) & (ask < 1) & (ask > bid) & hours.between(2, 6)].copy()
    d["spread"] = (d.yes_ask_dollars - d.yes_bid_dollars).round(2)
    b = pd.concat([pd.read_csv(f) for f in books])
    b = b[pd.to_numeric(b.book_n, errors="coerce") >= 2]
    quoted = set(zip(b.player_key, b.stat, pd.to_numeric(b.line).round(1)))
    keys = zip(d.player_key, d.stat, pd.to_numeric(d.line).round(1))
    d["two_book_line"] = [k in quoted for k in keys]
    nights = tip.loc[d.index].dt.tz_convert(ET).dt.strftime("%Y-%m-%d")
    out = {"nights": sorted(set(nights))}
    for flag, g in d.groupby("two_book_line"):
        out["with two-book line" if flag else "without"] = {
            "snapshots": len(g),
            "markets": int(g.ticker.nunique()),
            "share_spread_2c_plus": float((g.spread >= 0.02).mean()),
        }
    return out


def report(results):
    lines = [
        "# Where is the NO edge thicker? (2025-26 replay, simulated, in-sample)",
        "",
        "v5 filter, one contract, no caps. Cents per filled contract; 'vs rest' is",
        "this bin minus the rest of the season (game-clustered t). ⭐ = promising",
        "(t ≥ 2, positive in both halves, 1,000+ fills). Flow share 0.25 in the",
        "last column.",
        "",
    ]
    for name, rows in results["slices"].items():
        lines += [
            f"## {name}",
            "",
            "| Bin | Orders | Fill rate | Fills | ¢/contract | t | ¢ per 100 orders | vs rest | t | 1st half | 2nd half | vs rest at 0.25 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in rows:
            star = " ⭐" if r["promising"] else ""
            lines.append(
                f"| {r['bin']}{star} | {r['eligible_orders']:,} | {r['fill_rate']:.0%} | "
                f"{r['fills']:,.0f} | {r['cents_per_contract']:+.2f} | {r['t']:.2f} | "
                f"{r['per_100_orders_cents']:+.0f} | {r['vs_rest_cents']:+.2f} | "
                f"{r['t_vs_rest']:.2f} | {r['vs_rest_first_half']:+.2f} | "
                f"{r['vs_rest_second_half']:+.2f} | {r['vs_rest_cents_q25']:+.2f} |"
            )
        lines.append("")
    lines += [
        "## B. Markets with a spread of 2¢ or more (room to go first in line)",
        "",
        "| Hours before tip | Two-sided markets | Spread ≥ 2¢ |",
        "|---|---:|---:|",
    ]
    for h, r in results["improvable_share"].items():
        lines.append(f"| {h} | {r['markets']:,} | {r['share_spread_2c_plus']:.0%} |")
    now = results.get("this_season_spreads")
    if now:
        lines += [
            "",
            f"This season (public snapshots, {', '.join(now['nights'])}, 2-6 h before tip):",
            "",
            "| Rungs | Snapshots | Markets | Spread ≥ 2¢ |",
            "|---|---:|---:|---:|",
        ]
        for k in ("with two-book line", "without"):
            if k in now:
                r = now[k]
                lines.append(
                    f"| {k} | {r['snapshots']:,} | {r['markets']:,} | {r['share_spread_2c_plus']:.0%} |"
                )
    n = results["counts"]
    lines += [
        "",
        f"Bins tested: {n['bins']}; promising: {n['promising']} "
        f"(about {n['expected_by_chance']:.1f} expected by chance at t ≥ 2).",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    public = args[0] if args else "."  # a checkout with this season's public data
    orders = load_orders()
    candles = load_candles()
    o = add_features(eligible(orders), candles, orders)
    results = {"orders": len(o), "games": int(o.game_id.nunique()), "slices": {}}
    for name, column in SLICES.items():
        results["slices"][name] = slice_rows(o, column)
    results["improvable_share"] = improvable_share(orders, candles)
    results["this_season_spreads"] = this_season_spreads(public)
    bins = sum(len(r) for r in results["slices"].values())
    results["counts"] = {
        "bins": bins,
        "promising": sum(x["promising"] for r in results["slices"].values() for x in r),
        "expected_by_chance": bins * 0.023,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "explore_edge.json").write_text(
        json.dumps(results, indent=1, default=float) + "\n"
    )
    text = report(results)
    (OUT / "explore_edge.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
