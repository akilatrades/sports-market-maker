"""Research on two proposed NBA strategies (exploratory; RESEARCH_LOG.md,
"2026-10-22: Two proposed NBA strategies, ladder maker and totals maker").

    python -m research.two_strategies totals            # game totals (KXNBATOTAL)
    python -m research.two_strategies ladder [PUBLIC]   # ladder maker checks

``PUBLIC`` is a checkout of this repository with this season's public data
(data/kalshi/2027, outputs/books, outputs/projections/ladders). Writes
outputs/research/two_strategies_<part>.{json,md}. Everything is simulated
from public data; nothing here is live P&L or a forecast.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from research.fill_sizing_replay import clustered_mean_t

OUT = Path("outputs/research")
SCAN = Path("outputs/scan/orders_KXNBATOTAL.csv.gz")
GAMES = Path("data/games.parquet")
PROPS = Path("outputs/decompose/orders_no.csv.gz")
SPLIT = pd.Timestamp("2026-02-09").date()
FIT_SEASONS = (2021, 2022, 2023, 2024, 2025)  # 2020-21 to 2024-25; 2025-26 is 2026
EDGE = (0.0, 0.15)
BAND = (0.05, 0.95)
SHARES = (1.0, 0.25)
FEES = (0.0, 0.01)
CLIP = 0.005
ET = "America/New_York"


# ------------------------------------------------------------------ totals


def team_codes(props=PROPS):
    """Kalshi team code -> ESPN abbreviation, from the props replay file."""
    p = pd.read_csv(props, usecols=["away", "home", "away_espn", "home_espn"])
    p = p.drop_duplicates()
    codes = dict(zip(p.away, p.away_espn))
    codes.update(dict(zip(p.home, p.home_espn)))
    return codes


def split_matchup(code, codes):
    """'LALDEN' -> ('LAL', 'DEN') using known Kalshi team codes."""
    for i in (2, 3, 4):
        away, home = code[:i], code[i:]
        if away in codes and home in codes:
            return away, home
    return None, None


def load_games(path=GAMES):
    g = pd.read_parquet(path)
    g = g[g.completed & g.home_score.notna()].copy()
    g["final"] = g.home_score + g.away_score
    g["date_key"] = g.tip_utc.dt.tz_convert(ET).dt.strftime("%y%b%d").str.upper()
    return g


def residuals(games, seasons=FIT_SEASONS):
    """Final total minus ESPN's total, in the seasons used to fit the model."""
    g = games[games.season.isin(seasons) & games.total.notna()]
    return (g.final - g.total).to_numpy(float)


def p_over(strike, total, family, resid):
    """P(final > strike) given ESPN's total, from earlier seasons' residuals."""
    strike, total = np.asarray(strike, float), np.asarray(total, float)
    gap = strike - total  # final > strike  <=>  residual > gap
    if family == "normal":
        mu, sd = resid.mean(), resid.std(ddof=1)
        # Finals are whole numbers: final > strike means final >= strike + 1.
        return 1 - norm.cdf((gap + 0.5 - mu) / sd)
    if family == "empirical":
        r = np.sort(resid)
        above = len(r) - np.searchsorted(r, gap, side="right")
        return (above + 0.5) / (len(r) + 1)
    raise ValueError(family)


def load_totals(scan=SCAN, games=None, codes=None):
    """The scan's hourly KXNBATOTAL quotes, joined to ESPN's line and the final."""
    games = load_games() if games is None else games
    codes = team_codes() if codes is None else codes
    o = pd.read_csv(scan)
    o["strike"] = o.ticker.str.split("-").str[-1].astype(float)
    part = o.event_ticker.str.split("-").str[1]
    o["date_key"] = part.str[:7]
    teams = part.str[7:].map(lambda c: split_matchup(c, codes))
    o["away"] = teams.str[0].map(codes)
    o["home"] = teams.str[1].map(codes)
    cols = ["date_key", "away", "home", "final", "total", "game_id", "season"]
    o = o.merge(games[cols], on=["date_key", "away", "home"], how="left")
    o["day"] = pd.to_datetime(o.date).dt.date
    o["won"] = o.won.astype(float)  # 1 if this side's contract paid out
    return o


def calibration(no, resid):
    """Log loss at each market's first quote: model, Kalshi mid, both families."""
    first = no.sort_values("end_ts").drop_duplicates("ticker")
    first = first[first.total.notna() & first.result.isin(["yes", "no"])]
    y = first.result.eq("yes").to_numpy(float)
    mid = (first.yes_bid + first.yes_ask).to_numpy(float) / 2
    sources = {"Kalshi mid": mid}
    for family in ("normal", "empirical"):
        sources[f"ESPN line, {family}"] = p_over(
            first.strike, first.total, family, resid
        )
    losses = {k: _log_loss(v, y) for k, v in sources.items()}
    out = {"markets": len(first), "games": int(first.game_id.nunique())}
    for k, v in losses.items():
        out[k] = float(v.mean())
    for family in ("normal", "empirical"):
        key = f"ESPN line, {family}"
        diff = losses[key] - losses["Kalshi mid"]
        mean, t = clustered_mean_t(diff, np.ones(len(diff)), first.game_id)
        out[f"{key} minus mid"] = {"mean": float(mean), "t": float(t)}
    return out


def _log_loss(p, y):
    p = np.clip(np.asarray(p, float), CLIP, 1 - CLIP)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def replay_totals(no, fair, share, fee, filtered=True):
    """One contract per market: rows in time order until the first fill.

    Each scan row is an order resting one hour. Returns per-row expected
    fills (the chance this row is the market's first fill) and results.
    """
    q = no.assign(fair=fair).sort_values(["ticker", "end_ts"])
    edge = (1 - q.fair) - q.price
    ok = q.price.between(*BAND)
    if filtered:
        ok &= edge.between(EDGE[0] - 1e-9, EDGE[1] + 1e-9) & q.fair.notna()
    q = q[ok].copy()
    n = np.floor(q.traded.to_numpy(float))
    chance = (n >= 1).astype(float) if share >= 1 else 1 - (1 - share) ** n
    # Probability that no earlier row of the same market filled.
    survive = np.ones(len(q))
    left = {}
    for i, t in enumerate(q.ticker.to_numpy()):
        survive[i] = left.get(t, 1.0)
        left[t] = survive[i] * (1 - chance[i])
    q["fill"] = survive * chance
    q["pnl_c"] = q.won - q.price - fee
    q["edge"] = edge[ok]
    return q


def summarise(q):
    if q.fill.sum() < 2:
        return {"orders": len(q), "fills": float(q.fill.sum())}
    mean, t = clustered_mean_t(q.pnl_c, q.fill, q.game_id.fillna(-1))
    out = {
        "markets": int(q.ticker.nunique()),
        "games": int(q.game_id.nunique()),
        "fills": float(q.fill.sum()),
        "cents_per_contract": 100 * float(mean),
        "t": float(t),
        "stated_edge_cents": 100 * float((q.fill * q.edge).sum() / q.fill.sum()),
        "pnl_usd": float((q.fill * q.pnl_c).sum()),
    }
    for half, part in (
        ("first_half", q[q.day < SPLIT]),
        ("second_half", q[q.day >= SPLIT]),
    ):
        if part.fill.sum() >= 2:
            m, tt = clustered_mean_t(part.pnl_c, part.fill, part.game_id.fillna(-1))
            out[half] = {
                "fills": float(part.fill.sum()),
                "cents": 100 * float(m),
                "t": float(tt),
            }
    return out


def scan_rescore(o):
    """The archived scan, NO side, every hourly row as its own order."""
    no = o[o.side.eq("no")]
    f = no[np.floor(no.traded) >= 1]
    out = {"rows": len(no), "fills": len(f), "games": int(f.game_id.nunique())}
    for fee in FEES:
        mean, t = clustered_mean_t(
            f.won - f.price - fee, np.ones(len(f)), f.game_id.fillna(-1)
        )
        out[f"fee_{fee:g}"] = {"cents": 100 * float(mean), "t": float(t)}
    out["scan_fee_as_saved"] = 100 * float(f.pnl.mean())
    return out


def props_correlation(games, props=PROPS):
    """How player points props move with the game total (same games)."""
    p = pd.read_csv(
        props, low_memory=False, usecols=["series", "game_id", "over", "p_model"]
    )
    p = p[p.series.eq("KXNBAPTS")]
    g = games[games.total.notna()][["game_id", "final", "total"]]
    m = p.merge(g, on="game_id")
    x = (m.final - m.total).to_numpy(float)  # game total surprise, points
    y = (m.over - m.p_model).to_numpy(float)  # prop surprise for the over
    slope = np.polyfit(x, y, 1)[0]
    return {
        "props": len(m),
        "games": int(m.game_id.nunique()),
        "corr": float(np.corrcoef(x, y)[0, 1]),
        "over_rate_change_per_10_points": float(10 * slope),
    }


def totals():
    games = load_games()
    resid = residuals(games)
    o = load_totals(games=games)
    no = o[o.side.eq("no") & o.total.notna()].copy()
    season = games[games.season.eq(2026) & games.total.notna()]
    r26 = (season.final - season.total).to_numpy(float)
    results = {
        "fit_seasons": list(FIT_SEASONS),
        "residual_fit": {
            "games": len(resid),
            "mean": float(resid.mean()),
            "sd": float(resid.std(ddof=1)),
        },
        "residual_2025_26": {
            "games": len(r26),
            "mean": float(r26.mean()),
            "sd": float(r26.std(ddof=1)),
        },
        "matched_share": float(o.total.notna().mean()),
        "scan_rescore": scan_rescore(o),
        "calibration": calibration(no, resid),
        "replay": {},
        "props_correlation": props_correlation(games),
    }
    for share in SHARES:
        for fee in FEES:
            key = f"flow {share:g}, fee {100 * fee:g}c"
            row = {
                "no model filter": summarise(
                    replay_totals(no, np.nan, share, fee, filtered=False)
                )
            }
            for family in ("normal", "empirical"):
                fair = p_over(no.strike, no.total, family, resid)
                row[f"ESPN line, {family}"] = summarise(
                    replay_totals(no, fair, share, fee)
                )
            results["replay"][key] = row
    write("totals", results, totals_md(results))


def totals_md(r):
    c, s = r["calibration"], r["scan_rescore"]
    lines = [
        "# NBA game totals (KXNBATOTAL): proposed totals maker (exploratory, simulated)",
        "",
        "Kalshi quotes: the archived scan's hourly NO quotes 1-4.5 hours before tip,",
        "each resting one hour, fills from public trade prints as if first in line.",
        "Fair value from ESPN's game total (one number per game, probably near the",
        "close: **an upper bound**, see RESEARCH_LOG) and the residual distribution",
        f"fitted on {r['residual_fit']['games']:,} games from 2020-21 to 2024-25 "
        f"(mean {r['residual_fit']['mean']:+.2f}, sd {r['residual_fit']['sd']:.2f} points; "
        f"2025-26: {r['residual_2025_26']['mean']:+.2f}, {r['residual_2025_26']['sd']:.2f}).",
        "",
        "## The archived scan, re-scored (every hourly NO row as its own order)",
        "",
        f"{s['fills']:,} fills in {s['games']} games: no fee {s['fee_0']['cents']:+.2f}¢ "
        f"(t {s['fee_0']['t']:.2f}); 1¢ fee {s['fee_0.01']['cents']:+.2f}¢ "
        f"(t {s['fee_0.01']['t']:.2f}); the scan's own fee {s['scan_fee_as_saved']:+.2f}¢.",
        "",
        "## Calibration at each market's first quote (log loss, lower is better)",
        "",
        f"{c['markets']:,} markets, {c['games']} games.",
        "",
        "| Source | Log loss | minus Kalshi mid (t) |",
        "|---|---:|---:|",
        f"| Kalshi mid | {c['Kalshi mid']:.4f} | |",
    ]
    for fam in ("normal", "empirical"):
        k = f"ESPN line, {fam}"
        d = c[f"{k} minus mid"]
        lines.append(f"| {k} | {c[k]:.4f} | {d['mean']:+.4f} ({d['t']:.2f}) |")
    lines += [
        "",
        "## Replay: one contract per market, edge 0-15¢, NO 5-95¢",
        "",
        "| Flow, fee | Fair value | Markets | Fills | Stated edge | ¢/contract | t | 1st half ¢ (t) | 2nd half ¢ (t) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, row in r["replay"].items():
        for src, x in row.items():
            if "cents_per_contract" not in x:
                continue
            h1 = x.get("first_half", {})
            h2 = x.get("second_half", {})
            lines.append(
                f"| {key} | {src} | {x['markets']:,} | {x['fills']:,.0f} | "
                f"{x['stated_edge_cents']:+.2f} | {x['cents_per_contract']:+.2f} | {x['t']:.2f} | "
                f"{h1.get('cents', float('nan')):+.2f} ({h1.get('t', float('nan')):.2f}) | "
                f"{h2.get('cents', float('nan')):+.2f} ({h2.get('t', float('nan')):.2f}) |"
            )
    pc = r["props_correlation"]
    lines += [
        "",
        "## Overlap with player-points props",
        "",
        f"Across {pc['props']:,} points props in {pc['games']:,} games, every 10 points "
        f"the game total beats ESPN's line raises the props' over rate by "
        f"{100 * pc['over_rate_change_per_10_points']:+.1f} points (correlation "
        f"{pc['corr']:.2f}). NO on a total and NO on points overs in the same game lose "
        "together.",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ output


def write(part, results, text):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"two_strategies_{part}.json").write_text(
        json.dumps(results, indent=1, default=float) + "\n"
    )
    (OUT / f"two_strategies_{part}.md").write_text(text)
    print(text)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    part = args[0] if args else "totals"
    if part == "totals":
        totals()
    elif part == "ladder":
        from research.two_strategies_ladder import ladder

        ladder(args[1] if len(args) > 1 else ".")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
