"""Do star players' props deserve bigger resting NO orders? (2025-26 replay).

Pre-registered in RESEARCH_LOG.md (2026-10-21: Do star players' props
deserve bigger orders?). In-sample; fills as in research.fill_sizing_replay
(first in line, or ``flow_share`` of the traded-through contracts).

Star definitions, both known before tip-off:
- S1: the player's projected points that game (model_mean on his points
  markets) is 20 or more.
- S2: the player's average traded contracts per market over his earlier games
  (at least 3) is in the top 30% of player-games (season-wide cut-off).

    python -m research.star_weighting
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.fill_sizing_replay import TRADES, Rules, _candidates, load_orders

OUT = Path("outputs/research/star_weighting.json")
BASE = Rules("base", contracts=1, per_game=25)  # 0c edge, 15c cap, 10-90c
WEIGHTS = (1, 2, 3, 5)
FLOW_SHARES = (1.0, 0.25)
SEEDS = range(5)  # flow share < 1 is averaged over these draws
S1_POINTS = 20.0
S2_TOP_SHARE = 0.30
S2_MIN_GAMES = 3


def star_s1(orders):
    """Projected points >= 20 for the player in that game."""
    pts = orders[orders.stat.eq("points")]
    proj = pts.groupby(["game_id", "player_id"]).model_mean.first()
    key = pd.MultiIndex.from_frame(orders[["game_id", "player_id"]])
    return pd.Series(proj.reindex(key).to_numpy() >= S1_POINTS, index=orders.index)


def star_s2(orders, trades):
    """Top 30% by trailing traded contracts per market, earlier games only."""
    volume = trades.groupby("ticker")["count"].sum()
    o = orders.assign(volume=orders.ticker.map(volume).fillna(0.0))
    per_game = (
        o.groupby(["player_id", "day"]).volume.mean().reset_index().sort_values("day")
    )
    grouped = per_game.groupby("player_id").volume
    per_game["prior_mean"] = grouped.transform(lambda v: v.shift(1).expanding().mean())
    per_game["prior_games"] = grouped.cumcount()
    eligible = per_game.prior_games >= S2_MIN_GAMES
    cutoff = per_game.loc[eligible, "prior_mean"].quantile(1 - S2_TOP_SHARE)
    per_game["star"] = eligible & (per_game.prior_mean >= cutoff)
    lookup = per_game.set_index(["player_id", "day"]).star
    key = pd.MultiIndex.from_frame(o[["player_id", "day"]])
    return pd.Series(lookup.reindex(key).fillna(False).to_numpy(), index=o.index)


def clustered_difference(values, weights, star, clusters):
    """Weighted star-minus-other mean difference with game-clustered t."""
    y = np.asarray(values, float)
    w = np.asarray(weights, float)
    x = np.asarray(star, float)
    X = np.column_stack([np.ones_like(x), x])
    bread = np.linalg.inv((X * w[:, None]).T @ X)
    beta = bread @ ((X * w[:, None]).T @ y)
    resid = y - X @ beta
    scores = pd.DataFrame(X * (w * resid)[:, None]).groupby(np.asarray(clusters)).sum()
    g = len(scores)
    meat = scores.to_numpy().T @ scores.to_numpy() * g / (g - 1)
    cov = bread @ meat @ bread
    return beta[1], beta[1] / np.sqrt(cov[1, 1])


def weighted_mean_t(values, weights, clusters):
    y, w = np.asarray(values, float), np.asarray(weights, float)
    total = w.sum()
    mean = (w * y).sum() / total
    sums = pd.Series(w * (y - mean)).groupby(np.asarray(clusters)).sum()
    g = len(sums)
    se = np.sqrt((sums**2).sum() * g / (g - 1)) / total
    return mean, mean / se


def fills(traded, contracts, flow_share, seed):
    traded = np.floor(traded).astype(np.int64)
    if flow_share < 1:
        traded = np.random.default_rng(seed).binomial(traded, flow_share)
    return np.minimum(traded, contracts).astype(float)


def compare_groups(q, star, label):
    """Per-contract result of stars vs everyone else at 1 contract, flow 1."""
    got = fills(q.through.to_numpy(), 1, 1.0, 0)
    filled = got > 0
    s = star.to_numpy()
    row = {"sample": label, "orders": int(len(q)), "star share of orders": s.mean()}
    for name, mask in (("star", s), ("other", ~s)):
        m, t = weighted_mean_t(
            q.pnl_c.to_numpy()[mask & filled],
            got[mask & filled],
            q.game_id.to_numpy()[mask & filled],
        )
        row[f"{name} fills"] = int(got[mask].sum())
        row[f"{name} fill rate"] = got[mask].mean()
        row[f"{name} median traded-through"] = float(np.median(q.through[mask]))
        row[f"{name} c/contract"] = 100 * m
        row[f"{name} t"] = t
    d, t = clustered_difference(
        q.pnl_c.to_numpy()[filled], got[filled], s[filled], q.game_id.to_numpy()[filled]
    )
    row["star minus other, c"] = 100 * d
    row["difference t"] = t
    return row


def weighting(q, star, k, flow_share):
    """Season result with k contracts on star orders, 1 on the rest."""
    contracts = np.where(star.to_numpy(), k, 1)
    runs = []
    for seed in SEEDS if flow_share < 1 else [0]:
        got = fills(q.through.to_numpy(), contracts, flow_share, seed)
        pnl = got * q.pnl_c.to_numpy()
        nightly = pd.Series(pnl).groupby(q.day.to_numpy()).sum()
        curve = nightly.cumsum().to_numpy()
        drawdown = (curve - np.maximum.accumulate(np.r_[0.0, curve])[1:]).min()
        mean, t = weighted_mean_t(q.pnl_c.to_numpy(), got, q.game_id.to_numpy())
        runs.append(
            {
                "filled contracts": got.sum(),
                "star share of contracts": got[star.to_numpy()].sum() / got.sum(),
                "season P&L $": pnl.sum(),
                "c/contract": 100 * mean,
                "t": t,
                "max drawdown $": drawdown,
            }
        )
    out = pd.DataFrame(runs).mean().to_dict()
    out["P&L per $ of drawdown"] = out["season P&L $"] / abs(out["max drawdown $"])
    return out


def main():
    orders = load_orders()
    trades = pd.concat([pd.read_parquet(p) for p in TRADES], ignore_index=True)
    trades["count"] = trades["count"].astype(float)
    q = _candidates(orders, BASE)
    q = q[q.groupby("game_id").cumcount() < BASE.per_game]
    stars = {
        "S1 projected points >= 20": star_s1(q),
        "S2 trailing volume top 30%": star_s2(q, trades),
    }

    days = np.sort(q.day.unique())
    split = days[len(days) // 2]
    samples = {
        "full season": np.ones(len(q), bool),
        "regular season": q.season_type.eq("regular").to_numpy(),
        "first half": (q.day < split).to_numpy(),
        "second half": (q.day >= split).to_numpy(),
    }
    report = {"comparisons": [], "weighting": []}
    for name, star in stars.items():
        for label, mask in samples.items():
            row = compare_groups(q[mask], star[mask], label)
            report["comparisons"].append({"definition": name, **row})
        for share in FLOW_SHARES:
            for k in WEIGHTS:
                row = weighting(q, star, k, share)
                report["weighting"].append(
                    {
                        "definition": name,
                        "flow share": share,
                        "star contracts": k,
                        **row,
                    }
                )

    pd.set_option("display.width", 250)
    pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
    comp = pd.DataFrame(report["comparisons"])
    print(comp.drop(columns=["orders"]).to_string(index=False), "\n")
    print(pd.DataFrame(report["weighting"]).to_string(index=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=float))


if __name__ == "__main__":
    main()
