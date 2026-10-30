"""Price Kalshi NBA prop lines from nearby sportsbook lines (RESEARCH_LOG.md, 2026-10-30).

Per game, player and stat, fit a negative binomial whose mean matches the books'
de-vigged over probabilities at every quoted line, then price Kalshi's line from
the fitted curve. Dispersion per stat comes from 2017-18 to 2024-25 box scores.

    python -m research.line_translation          # offline; writes outputs/line_translation/
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom

from kalshi.stats import clustered_mean_t
from research.bookline_backtest import FEE_SHARE, difference, maker_fee, summary

OUT = Path("outputs/line_translation")
STATS = {"points": "points", "rebounds": "rebounds", "assists": "assists", "threes": "threes"}
MAX_GAP = {"points": 3.0, "rebounds": 2.0, "assists": 2.0, "threes": 1.0}
MIN_QUOTES = 2


def dispersion(path="data/player_games.parquet", last_season=2025):
    """Pooled negative-binomial size r per stat: var = mu + mu^2 / r."""
    p = pd.read_parquet(path)
    p = p[(p.season <= last_season) & ~p.did_not_play.astype(bool) & (p.minutes > 0)]
    out = {}
    for stat, col in STATS.items():
        g = p.groupby(["player_id", "season"])[col].agg(["mean", "var", "size"])
        g = g[(g["size"] >= 20) & (g["mean"] > 0)]
        excess = (g["var"] - g["mean"]).clip(lower=1e-9)
        out[stat] = float((g["mean"] ** 2).sum() / excess.sum())
    return out


def p_over(mu, r, line):
    """P(stat > line) for a half-point line under NB(mean mu, size r)."""
    return float(nbinom.sf(np.floor(line), r, r / (r + mu)))


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_mu(lines, probs, weights, r):
    def loss(mu):
        model = np.array([p_over(mu, r, x) for x in lines])
        return float(np.sum(weights * (logit(model) - logit(probs)) ** 2))

    # The loss is flat where every fitted probability saturates, so a bounded
    # Brent search alone can stall at the upper bound: grid first, then refine.
    grid = np.geomspace(0.05, 90.0, 160)
    best = int(np.argmin([loss(m) for m in grid]))
    lo, hi = grid[max(best - 1, 0)], grid[min(best + 1, len(grid) - 1)]
    res = minimize_scalar(loss, bounds=(lo, hi), method="bounded")
    return res.x


def translate(quotes, line, stat, r, exclude_exact=True):
    """Translated over probability for `line`, or None when the rules say no."""
    q = quotes
    if exclude_exact:
        q = q[(q.line - line).abs() > 1e-6]
    if q.empty:
        return None, None
    if (q.line - line).abs().min() > MAX_GAP[stat] + 1e-9 or q.book_n.sum() < MIN_QUOTES:
        return None, None
    mu = fit_mu(q.line.to_numpy(float), q.p_book.to_numpy(float), q.book_n.to_numpy(float), r)
    nb = p_over(mu, r, line)
    # sensitivity: logit interpolation between the two nearest lines (flat beyond the ends)
    srt = q.sort_values("line")
    xs, ys = srt.line.to_numpy(float), logit(srt.p_book.to_numpy(float))
    interp = float(1 / (1 + np.exp(-np.interp(line, xs, ys)))) if len(xs) >= 2 else None
    return nb, interp


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 0.01, 0.99)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired_logloss(frame, a, b):
    d = logloss(frame[a], frame.over) - logloss(frame[b], frame.over)
    mean, t = clustered_mean_t(pd.Series(d, index=frame.index), frame.game_id)
    return {"mean": round(float(mean), 4), "t": round(float(t), 2), "fills": int(len(frame))}


def main():
    r = dispersion()
    fills = pd.read_csv("outputs/bookline/fills_with_book.csv.gz")
    book = pd.read_csv("outputs/bookline/book_lines.csv.gz")
    book["line"] = book.line.round(1)
    fills["line"] = fills.line.round(1)
    groups = {k: g for k, g in book.groupby(["game_id", "player_key", "stat"])}
    nb, interp = [], []
    for row in fills.itertuples():
        q = groups.get((row.game_id, row.player_key, row.stat))
        if q is None or row.stat not in r:
            nb.append(None), interp.append(None)
            continue
        a, b = translate(q, row.line, row.stat, r[row.stat])
        nb.append(a), interp.append(b)
    fills["p_tr"] = pd.to_numeric(pd.Series(nb, index=fills.index), errors="coerce")
    fills["p_interp"] = pd.to_numeric(pd.Series(interp, index=fills.index), errors="coerce")
    fills["mid"] = fills["mid"].astype(float)
    fee = maker_fee(fills.price.astype(float), FEE_SHARE)
    for col, src in (("tr_edge", "p_tr"), ("interp_edge", "p_interp"), ("book_edge", "p_book")):
        fills[col] = (1 - fills[src]) - fills.price - fee

    exact = fills.p_book.notna()
    has_tr = fills.p_tr.notna()
    res = {"dispersion_r": {k: round(v, 3) for k, v in r.items()},
           "coverage": {"fills": int(len(fills)),
                        "exact_quote": round(float(exact.mean()), 3),
                        "no_exact_but_translated": round(float((~exact & has_tr).mean()), 3),
                        "neither": round(float((~exact & ~has_tr).mean()), 3)}}

    # 1. validation where both exist (exact line left out of the fit)
    v = fills[exact & has_tr].copy()
    res["validation"] = {
        "fills": int(len(v)),
        "mean_abs_gap_to_exact_cents": round(100 * float((v.p_tr - v.p_book).abs().mean()), 2),
        "logloss": {k: round(float(logloss(v[k], v.over).mean()), 4) for k in ("p_tr", "p_book", "mid", "p_model")},
        "translated_minus_mid": paired_logloss(v, "p_tr", "mid"),
        "translated_minus_model": paired_logloss(v, "p_tr", "p_model"),
        "exact_minus_mid": paired_logloss(v, "p_book", "mid"),
    }
    # 2. primary: no exact quote, translated price available
    u = fills[~exact & has_tr]
    keep, cut = u[u.tr_edge >= 0], u[u.tr_edge < 0]
    res["primary"] = {
        "all": summary(u, "no exact quote, translated"),
        "kept": summary(keep, "kept by translated veto"),
        "removed": summary(cut, "removed by translated veto"),
        "kept_minus_removed": difference(keep, cut),
        "logloss": {k: round(float(logloss(u[k], u.over).mean()), 4) for k in ("p_tr", "mid", "p_model")},
        "translated_minus_mid": paired_logloss(u, "p_tr", "mid"),
        "translated_minus_model": paired_logloss(u, "p_tr", "p_model"),
    }
    d = res["primary"]["kept_minus_removed"]
    res["primary"]["pass"] = bool(d and d["cents"] >= 1 and (d["t"] or 0) >= 2 and len(u) >= 1000)
    # sensitivity: logit interpolation
    ui = fills[~exact & fills.p_interp.notna() & has_tr]
    res["sensitivity_interp"] = {"kept_minus_removed": difference(ui[ui.interp_edge >= 0], ui[ui.interp_edge < 0]),
                                 "fills": int(len(ui))}
    # combined coverage: exact where available, else translated
    fills["p_best"] = fills.p_book.fillna(fills.p_tr)
    fills["best_edge"] = (1 - fills.p_best) - fills.price - fee
    c = fills[fills.p_best.notna()]
    res["combined"] = {"kept": summary(c[c.best_edge >= 0], "kept, exact or translated"),
                       "removed": summary(c[c.best_edge < 0], "removed"),
                       "kept_minus_removed": difference(c[c.best_edge >= 0], c[c.best_edge < 0]),
                       "everything_unfiltered": summary(fills, "all fills, no veto")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return fills


if __name__ == "__main__":
    main()
