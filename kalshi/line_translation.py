"""Price a Kalshi prop line from the sportsbooks' nearby lines.

RESEARCH_LOG.md, 2026-10-30, "Price Kalshi props from nearby sportsbook
lines": per game, player and stat, fit a negative binomial whose mean matches
the books' de-vigged over probabilities at every quoted line (least squares on
the logit, weighted by books), then read Kalshi's line off the fitted curve.
Validated against exact book quotes (2.2c apart on average, same log loss).
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom

# Negative-binomial size per stat (var = mu + mu^2 / r), pooled player-season
# moments, 2017-18 to 2024-25 box scores, players with 20+ games
# (research/line_translation.py dispersion(); nothing from 2025-26).
DISPERSION = {"points": 5.924, "rebounds": 10.042, "assists": 11.155, "threes": 7.628}
# Only translate when a quoted line is this close to Kalshi's line.
MAX_GAP = {"points": 3.0, "rebounds": 2.0, "assists": 2.0, "threes": 1.0}
MIN_QUOTES = 2  # book quotes (books x lines) that go into one fit


def p_over(mu, r, line):
    """P(stat > line) for a half-point line under NB(mean mu, size r)."""
    return float(nbinom.sf(np.floor(line), r, r / (r + mu)))


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_mu(lines, probs, weights, r):
    def loss(mu):
        model = np.array([p_over(mu, r, x) for x in lines])
        return float(np.sum(weights * (logit(model) - logit(probs)) ** 2))

    # The loss is flat where every fitted probability saturates, so a bounded
    # search alone can stall at a bound: grid first, then refine.
    grid = np.geomspace(0.05, 90.0, 160)
    best = int(np.argmin([loss(m) for m in grid]))
    lo, hi = grid[max(best - 1, 0)], grid[min(best + 1, len(grid) - 1)]
    return minimize_scalar(loss, bounds=(lo, hi), method="bounded").x


def translate(quotes, line, stat, exclude_exact=True):
    """(NB probability, logit-interpolated probability) for ``line``, or (None, None).

    ``quotes`` has columns line, p_book (over probability) and book_n.
    """
    if stat not in DISPERSION:
        return None, None
    q = quotes
    if exclude_exact:
        q = q[(q.line - line).abs() > 1e-6]
    if q.empty:
        return None, None
    if (q.line - line).abs().min() > MAX_GAP[
        stat
    ] + 1e-9 or q.book_n.sum() < MIN_QUOTES:
        return None, None
    mu = fit_mu(
        q.line.to_numpy(float),
        q.p_book.to_numpy(float),
        q.book_n.to_numpy(float),
        DISPERSION[stat],
    )
    nb = p_over(mu, DISPERSION[stat], line)
    srt = q.sort_values("line")
    xs, ys = srt.line.to_numpy(float), logit(srt.p_book.to_numpy(float))
    interp = float(1 / (1 + np.exp(-np.interp(line, xs, ys)))) if len(xs) >= 2 else None
    return nb, interp


def attach_translated(frame, book):
    """Fill missing ``p_book`` from the same game's nearby lines.

    ``frame`` comes from ``kalshi.books.attach`` (player_key, stat, line,
    tip_utc, p_book, book_n). ``book`` is the multi-line book log with
    player_key, stat, line, p_book, book_n, updated_utc and commence_utc,
    already filtered for freshness. Rows priced from an exact line keep
    ``book_source`` "exact"; translated rows get "translated", ``book_n`` = the
    book quotes in the fit, and the oldest contributing update time.
    """
    from kalshi.books import game_day

    out = frame.copy()
    out["book_source"] = np.where(
        pd.to_numeric(out.p_book, errors="coerce").notna(), "exact", ""
    )
    if book is None or book.empty or out.empty or "tip_utc" not in out:
        return out
    b = book.copy()
    b["line"] = pd.to_numeric(b.line, errors="coerce").round(1)
    b["p_book"] = pd.to_numeric(b.p_book, errors="coerce")
    b["book_n"] = pd.to_numeric(b.book_n, errors="coerce").fillna(0)
    b = b[b.line.notna() & b.p_book.between(0, 1) & b.book_n.gt(0)]
    if b.empty:
        return out
    b["game_day"] = game_day(b.commence_utc)
    b = b.drop_duplicates(["game_day", "player_key", "stat", "line"], keep=False)
    groups = {k: g for k, g in b.groupby(["game_day", "player_key", "stat"])}
    days = game_day(out.tip_utc)
    for i in out.index[out.book_source.eq("")]:
        q = groups.get((days.loc[i], out.at[i, "player_key"], out.at[i, "stat"]))
        if q is None:
            continue
        line = float(out.at[i, "line"])
        p, _ = translate(q, line, out.at[i, "stat"], exclude_exact=False)
        if p is None:
            continue
        near = q[(q.line - line).abs() <= MAX_GAP[out.at[i, "stat"]] + 1e-9]
        out.at[i, "p_book"] = round(p, 6)
        out.at[i, "book_n"] = int(q.book_n.sum())
        out.at[i, "book_source"] = "translated"
        if "updated_utc" in q:
            oldest = pd.to_datetime(q.updated_utc, utc=True, errors="coerce").min()
            out.at[i, "book_updated_utc"] = (
                None if pd.isna(oldest) else oldest.isoformat()
            )
        if "commence_utc" in q:
            out.at[i, "book_commence_utc"] = near.commence_utc.iloc[0]
    return out
