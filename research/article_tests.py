"""Five market-making ideas replayed on the 2025-26 NBA NO orders (exploratory).

The plan, variants and pass bars were written down first: RESEARCH_LOG.md,
"2026-10-21: Market-making models applied to the NO seller (plan)". Every
number here is simulated and in-sample (the v5 rules were chosen on this
season), with fills read from public trade prints as if first in line, so it
is a planning aid, not a forecast.

1. Profit decomposition: entry edge, model error and adverse selection per
   filled contract, plus how much same-game fills move together.
2. Minimum edge (Glosten-Milgrom's adverse-selection spread).
3. Time to tip-off (Avellaneda-Stoikov's horizon term): post 2, 4 or 6 hours
   before tip, optionally asking for more edge the earlier the order goes up.
4. Same-game inventory penalty (Avellaneda-Stoikov's inventory term).
5. Choosing join / improve 1 cent / improve 2 cents by P(fill) x edge.

Fills: a one-contract order fills when at least one contract a YES taker
bought went through its price before tip-off. At ``flow_share`` 0.25 each such
contract reaches us with that chance; the same random numbers per market are
reused across variants (common random numbers), averaged over 10 draws.

    python -m research.article_tests   # about two minutes; writes outputs/research/article_tests.*
"""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_logit
from kalshi.stats import clustered_mean_t as plain_mean_t
from research.fill_sizing_replay import (
    SERIES,
    TRADES,
    Rules,
    _candidates,
    _Caps,
    _costs,
    clustered_mean_t,
    load_orders,
    through_volume,
)

CANDLES = tuple(Path(f"data/kalshi_history/candles_{s}.parquet") for s in SERIES)
OUT = Path("outputs/research")
SHARES = (1.0, 0.25)
DRAWS = 10
TICK = 0.01
BAR = 0.10  # "at least 10% better than control"
V5 = Rules(
    "v5-like",
    band=(0.05, 0.95),
    per_game=40,
    game_usd=25,
    team_usd=25,
    day_usd=150,
    day_stop=20,
)
MIN_EDGES = (0.0, 0.01, 0.02, 0.03, 0.04)
POST_HOURS = (2, 4, 6)
CONTROL_HOURS = 5
PER_HOUR = (0.0, 0.005)  # extra edge per hour before tip beyond 2
PENALTIES = (0.0, 0.001, 0.0025, 0.005)  # extra edge per order already in the game
OPTIONS = (("join", 0), ("improve1", 1), ("improve2", 2))


# --------------------------------------------------------------------- data


def load_trades(paths=TRADES):
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)


def load_candles(paths=CANDLES):
    c = pd.concat([pd.read_parquet(p) for p in paths if p.exists()], ignore_index=True)
    for col in ("end_ts", "yes_bid", "yes_ask", "open_interest"):
        c[col] = c[col].astype(float)
    c["end_ts"] = c.end_ts.astype("int64")
    return c


def season_split(orders):
    """Median game date: games before it are the first half."""
    days = np.sort(orders.drop_duplicates("game_id").day.to_numpy())
    return days[len(days) // 2]


def uniforms(tickers, draws=DRAWS, seed=0):
    """One row of random numbers per market, shared by every variant."""
    keys = np.sort(pd.unique(np.asarray(tickers)))
    return pd.DataFrame(
        np.random.default_rng(seed).random((len(keys), draws)), index=keys
    )


def fill_matrix(frame, share, u):
    """0/1 fill of a one-contract order, one column per draw (one if share is 1)."""
    n = np.floor(frame.through.to_numpy(float))
    if share >= 1:
        return (n >= 1).astype(float)[:, None]
    chance = 1 - (1 - share) ** n  # at least one of n contracts reaches us
    return (u.loc[frame.ticker.to_numpy()].to_numpy() < chance[:, None]).astype(float)


def quote(frame, ticks):
    """NO order ``ticks`` cents above the NO bid (1 - yes ask), with its edge."""
    q = frame.copy()
    q["price"] = (1 - q.yes_ask + ticks * TICK).round(4)
    q["improved"] = ticks > 0
    q["yes_level"] = (1 - q.price).round(4)
    q["edge"] = (1 - q.p_model) - q.price  # NBA props: no maker fee assumed
    q["pnl_c"] = (1 - q.over) - q.price
    return q


def rebuild(base, candles, trades, hours):
    """The base markets' orders as if posted ``hours`` before tip-off.

    Same construction as the original replay orders: the last hourly candle
    ending at least that long before tip, two-sided, one cent inside the NO
    bid when the spread is 2 cents or more (else joining it), resting from the
    candle's end to tip-off. Trade prints on file start 6 hours before tip.
    """
    c = candles.merge(base[["ticker", "tip_ts"]], on="ticker")
    c = c[c.end_ts <= c.tip_ts - hours * 3600].sort_values("end_ts")
    last = c.drop_duplicates("ticker", keep="last")
    last = last[["ticker", "end_ts", "yes_bid", "yes_ask", "open_interest"]]
    drop = ["end_ts", "yes_bid", "yes_ask", "price", "improved", "yes_level"]
    drop += ["edge", "pnl_c", "through", "open_interest"]
    q = base.drop(columns=[c for c in drop if c in base]).merge(last, on="ticker")
    spread = (q.yes_ask - q.yes_bid).round(4)
    q = q[(q.yes_bid > 0) & (q.yes_ask < 1) & (spread > 0)].copy()
    improve = (q.yes_ask - q.yes_bid).round(4) >= 2 * TICK - 1e-9
    q = pd.concat([quote(q[~improve], 0), quote(q[improve], 1)]).sort_index()
    q["hours_posted"] = (q.tip_ts - q.end_ts) / 3600
    q["through"] = through_volume(q, trades)
    return q.reset_index(drop=True)


# ------------------------------------------------------------- the season


def run(orders, rules, fill, penalty=0.0):
    """One season under capped rules for one fill draw (one contract per order).

    Mirrors ``fill_sizing_replay.simulate``: orders are placed night by night
    in the bot's order (tip-off, then edge), caps skip what does not fit, and
    a night losing ``day_stop`` blocks the next night. ``penalty`` asks the
    k-th order in a game for (k - 1) x penalty more edge.
    Returns the placed orders (with their fill) and P&L by night.
    """
    assert rules.contracts == 1
    q = _candidates(orders.assign(fill=np.asarray(fill, float)), rules)
    fill = q.fill.to_numpy()
    pnl = q.pnl_c.to_numpy() - rules.edge_shave
    edge = q.edge.to_numpy()
    games, teams, days = q.game_id.to_numpy(), q.team.to_numpy(), q.day.to_numpy()
    cost = _costs(q, rules)
    caps, placed = _Caps(rules), np.zeros(len(q), dtype=bool)
    nightly, blocked, stopped, total = {}, False, False, 0.0
    for day in sorted(set(days)):
        if stopped:
            break
        if blocked:
            blocked = False
            continue
        rows = np.flatnonzero(days == day)
        for i in rows:
            if penalty:
                need = rules.min_edge + penalty * caps.per_game.get(games[i], 0)
                if edge[i] < need - 1e-9:
                    continue
            placed[i] = caps.admit(games[i], teams[i], day, cost[i])
        night = float((fill[rows] * pnl[rows] * placed[rows]).sum())
        if placed[rows].any():
            nightly[day] = night
        total += night
        blocked = rules.day_stop is not None and night <= -rules.day_stop
        stopped = rules.cum_stop is not None and total <= -rules.cum_stop
    return q[placed], pd.Series(nightly, dtype=float)


def sharpe(nights):
    """Mean over standard deviation of nightly P&L (per night, not annualised)."""
    return (
        float(nights.mean() / nights.std())
        if len(nights) > 2 and nights.std() > 0
        else np.nan
    )


def season_stats(placed, nights, split):
    mean, t = clustered_mean_t(placed.pnl_c, placed.fill, placed.game_id)
    first, second = nights[nights.index < split], nights[nights.index >= split]
    curve = nights.cumsum().to_numpy()
    peak = np.maximum.accumulate(np.r_[0.0, curve])[1:]
    return {
        "orders": float(len(placed)),
        "fills": float(placed.fill.sum()),
        "cents_per_contract": 100 * mean,
        "t": t,
        "pnl": float(nights.sum()),
        "pnl_h1": float(first.sum()),
        "pnl_h2": float(second.sum()),
        "sharpe": sharpe(nights),
        "sharpe_h1": sharpe(first),
        "sharpe_h2": sharpe(second),
        "worst_night": float(nights.min()) if len(nights) else 0.0,
        "max_drawdown": float((curve - peak).min()) if len(nights) else 0.0,
        "nights": float(len(nights)),
    }


def evaluate(orders, rules, share, u, split, penalty=0.0):
    """Season statistics averaged over the fill draws."""
    draws = fill_matrix(orders, share, u)
    rows = [
        season_stats(*run(orders, rules, draws[:, d], penalty), split)
        for d in range(draws.shape[1])
    ]
    return {k: float(np.nanmean([r[k] for r in rows])) for k in rows[0]}


def beats(value, control, bar=BAR):
    """``value`` at least ``bar`` (10%) better than ``control``, sign-safe."""
    return bool(value >= control + bar * abs(control))


# ------------------------------------------------------ 1. decomposition


def clustered_difference(y, flag, clusters):
    """Difference in means (flag 1 minus flag 0) and its game-clustered t."""
    y, flag = np.asarray(y, float), np.asarray(flag, float)
    X = np.column_stack([np.ones(len(y)), flag])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    bread = np.linalg.inv(X.T @ X)
    scores = pd.DataFrame(X * resid[:, None]).groupby(np.asarray(clusters)).sum()
    g = len(scores)
    cov = bread @ (scores.to_numpy().T @ scores.to_numpy()) @ bread * g / (g - 1)
    se = float(np.sqrt(cov[1, 1]))
    return float(beta[1]), float(beta[1] / se) if se > 0 else np.nan


def correlation(placed, nights):
    """How much same-game fills move together, from filled contracts."""
    f = placed[placed.fill > 0]
    r = f.pnl_c - f.pnl_c.mean()
    by_game = r.groupby(f.game_id.to_numpy()).sum()
    sizes = f.groupby("game_id").size()
    deff = float((by_game**2).sum() / (r**2).sum())
    m_w = float((sizes**2).sum() / sizes.sum())
    # Nightly swings around the model's expectation, against the sum of each
    # contract's own variance (what independent contracts would give).
    expected = (f.edge).groupby(f.day.to_numpy()).sum()
    var_alone = (f.p_model * (1 - f.p_model)).groupby(f.day.to_numpy()).sum()
    swing = ((nights.reindex(expected.index) - expected) ** 2).sum()
    return {
        "design_effect": deff,
        "fills_per_game_weighted": m_w,
        "within_game_correlation": (deff - 1) / (m_w - 1) if m_w > 1 else np.nan,
        "nightly_variance_vs_independent": float(swing / var_alone.sum()),
    }


def decomposition(orders, u, split):
    """Test 1: per filled contract, profit = edge + model error + adverse selection."""
    out = {}
    for share in SHARES:
        draws = fill_matrix(orders, share, u)
        rows = []
        for d in range(draws.shape[1]):
            placed, nights = run(orders, V5, draws[:, d])
            surprise = placed.p_model - placed.over  # NO outcome minus fair NO
            filled = placed.fill > 0
            gap, t_gap = clustered_difference(surprise, filled, placed.game_id)
            mean, t = clustered_mean_t(placed.pnl_c, placed.fill, placed.game_id)
            row = {
                "filled_contracts": float(filled.sum()),
                "unfilled_orders": float((~filled).sum()),
                "cents_per_contract": 100 * mean,
                "t": t,
                "entry_edge": 100 * float(placed.edge[filled].mean()),
                "model_error_unfilled": 100 * float(surprise[~filled].mean()),
                "adverse_selection": 100 * gap,
                "t_adverse_selection": t_gap,
                "fill_rate_edge_0_3": float(filled[placed.edge < 0.03].mean()),
                "fill_rate_edge_3_15": float(filled[placed.edge >= 0.03].mean()),
            }
            for kind, mask in (
                ("improved", placed.improved),
                ("joined", ~placed.improved),
            ):
                g, tg = clustered_difference(
                    surprise[mask], filled[mask], placed.game_id[mask]
                )
                row[f"adverse_selection_{kind}"] = 100 * g
                row[f"t_adverse_selection_{kind}"] = tg
            row.update(correlation(placed, nights))
            rows.append(row)
        out[str(share)] = {k: float(np.nanmean([r[k] for r in rows])) for k in rows[0]}
    # Every market in the replay, no caps or edge filter, first in line.
    filled = orders.through >= 1
    gap, t_gap = clustered_difference(
        orders.p_model - orders.over, filled, orders.game_id
    )
    out["all_orders_uncapped"] = {
        "orders": len(orders),
        "fill_rate": float(filled.mean()),
        "adverse_selection": 100 * gap,
        "t_adverse_selection": t_gap,
    }
    return out


# ------------------------------------------------------- 2-4. rule tests


def min_edge_test(orders, u, split):
    rows = {}
    for m in MIN_EDGES:
        rules = replace(V5, name=f"min edge {100 * m:g}c", min_edge=m)
        rows[rules.name] = {
            str(s): evaluate(orders, rules, s, u, split) for s in SHARES
        }
    control = rows["min edge 0c"]
    for name, r in rows.items():
        if name == "min edge 0c":
            continue
        r["passes"] = all(
            beats(r[s][k], control[s][k])
            for s in map(str, SHARES)
            for k in ("pnl", "pnl_h1", "pnl_h2")
        ) and all(r[str(s)]["t"] >= 2 for s in SHARES)
    return rows


def posting_time_test(base, candles, trades, u, split):
    built = {h: rebuild(base, candles, trades, h) for h in (*POST_HOURS, CONTROL_HOURS)}
    rows = {}
    control_name = f"posted {CONTROL_HOURS}h, 0c (control)"
    rows[control_name] = {
        str(s): evaluate(built[CONTROL_HOURS], V5, s, u, split) for s in SHARES
    }
    for h in POST_HOURS:
        for b in PER_HOUR:
            name = f"posted {h}h, +{100 * b:g}c per hour beyond 2h"
            if h == 2 and b > 0:
                rows[name] = {"same_as": "posted 2h, +0c per hour beyond 2h"}
                continue
            rules = replace(V5, name=name, min_edge=b * (h - 2))
            rows[name] = {
                str(s): evaluate(built[h], rules, s, u, split) for s in SHARES
            }
    control = rows[control_name]
    for name, r in rows.items():
        if name == control_name or "same_as" in r:
            continue
        r["passes"] = all(
            beats(r[s][k], control[s][k])
            for s in map(str, SHARES)
            for k in ("pnl", "pnl_h1", "pnl_h2")
        )
    rows["_hours_posted_median"] = {
        f"{h}h": float(built[h].hours_posted.median()) for h in built
    }
    rows["_markets_with_a_quote"] = {f"{h}h": len(built[h]) for h in built}
    return rows


def inventory_test(orders, u, split):
    rows = {}
    for c in PENALTIES:
        name = f"penalty {100 * c:g}c per order already in the game"
        rows[name] = {
            str(s): evaluate(orders, V5, s, u, split, penalty=c) for s in SHARES
        }
    control = rows["penalty 0c per order already in the game"]
    for name, r in rows.items():
        if r is control:
            continue
        r["passes"] = all(
            beats(r[s][k], control[s][k])
            for s in map(str, SHARES)
            for k in ("sharpe", "sharpe_h1", "sharpe_h2")
        ) and all(
            r[s]["pnl"] >= control[s]["pnl"] - BAR * abs(control[s]["pnl"])
            for s in map(str, SHARES)
        )
    return rows


# ------------------------------------------------------ 5. quote choice


def admissible(q, rules=V5):
    lo, hi = rules.band
    return (
        (q.edge >= rules.min_edge - 1e-9)
        & (q.edge <= rules.edge_cap + 1e-9)
        & q.price.between(lo, hi)
    )


def option_rows(base, trades, candles):
    """Every order's join / improve1 / improve2 versions, where the spread allows."""
    oi = candles[["ticker", "end_ts", "open_interest"]].drop_duplicates(
        ["ticker", "end_ts"]
    )
    b = base.drop(columns=[c for c in ("open_interest",) if c in base]).merge(
        oi, on=["ticker", "end_ts"], how="left"
    )
    b["spread"] = (b.yes_ask - b.yes_bid).round(4)
    b = b[(b.yes_bid > 0) & (b.yes_ask < 1) & (b.spread > 0)]
    stacked = []
    for name, ticks in OPTIONS:
        avail = b.spread >= (ticks + 1) * TICK - 1e-9
        q = quote(b[avail], ticks).assign(option=name)
        q["through"] = through_volume(q, trades)
        stacked.append(q)
    q = pd.concat(stacked, ignore_index=True)
    q["control"] = np.where(
        q.spread >= 2 * TICK - 1e-9, q.option == "improve1", q.option == "join"
    )
    q["ok"] = admissible(q)
    return q


def features(q):
    oi = q.open_interest.fillna(q.open_interest.median())
    return np.column_stack(
        [
            q.option.eq("improve1"),
            q.option.eq("improve2"),
            100 * q.spread.clip(upper=0.10),
            q.price,
            (q.tip_ts - q.end_ts) / 3600,
            np.log1p(oi.clip(lower=0)),
        ]
    ).astype(float)


def quote_choice_test(base, trades, candles, u, split):
    q = option_rows(base, trades, candles)
    eligible = set(q.ticker[q.control & q.ok])
    q = q[q.ok & q.ticker.isin(eligible)].reset_index(drop=True)
    first = q.day < split
    out = {}
    for share in SHARES:
        filled = fill_matrix(q, share, u).mean(
            axis=1
        )  # per-row fill, averaged over draws
        beta, _ = clustered_logit(filled[first], features(q[first]), q.game_id[first])
        x = np.column_stack([np.ones(len(q)), features(q)])
        p_hat = 1 / (1 + np.exp(-x @ beta))
        test = q[~first].assign(p_hat=p_hat[~first], fill=filled[~first])
        test["score"] = test.p_hat * test.edge
        chosen = test.loc[test.groupby("ticker").score.idxmax()].set_index("ticker")
        control = test[test.control].set_index("ticker").loc[chosen.index]
        pnl_choice = chosen.fill * chosen.pnl_c
        pnl_control = control.fill * control.pnl_c
        diff = pnl_choice - pnl_control
        mean_d, t_d = plain_mean_t(diff, chosen.game_id)
        _, t_c = plain_mean_t(pnl_choice, chosen.game_id)
        _, t_k = plain_mean_t(pnl_control, chosen.game_id)
        calib = test.groupby("option").agg(
            predicted=("p_hat", "mean"), actual=("fill", "mean")
        )
        out[str(share)] = {
            "eligible_orders_second_half": len(chosen),
            "choice_per_100_orders_cents": float(100 * 100 * pnl_choice.mean()),
            "t_choice": t_c,
            "control_per_100_orders_cents": float(100 * 100 * pnl_control.mean()),
            "t_control": t_k,
            "difference_per_100_orders_cents": float(100 * 100 * mean_d),
            "t_difference": t_d,
            "chosen_share": chosen.option.value_counts(normalize=True)
            .round(3)
            .to_dict(),
            "fill_rate_choice": float(chosen.fill.mean()),
            "fill_rate_control": float(control.fill.mean()),
            "fit_coefficients": dict(
                zip(
                    [
                        "intercept",
                        "improve1",
                        "improve2",
                        "spread_c",
                        "price",
                        "hours",
                        "log_oi",
                    ],
                    np.round(beta, 4).tolist(),
                )
            ),
            "calibration_second_half": calib.round(3).to_dict("index"),
        }
    a, b = out["1.0"], out["0.25"]
    out["passes"] = bool(
        beats(a["choice_per_100_orders_cents"], a["control_per_100_orders_cents"])
        and a["t_difference"] >= 2
        and b["choice_per_100_orders_cents"] > b["control_per_100_orders_cents"]
    )
    return out


# -------------------------------------------------------------- report


def table(rows, keys, label="Variant"):
    head = [label, "flow share", *keys]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for name, r in rows.items():
        if name.startswith("_") or "same_as" in r:
            continue
        for s in map(str, SHARES):
            cells = [
                f"{r[s][k]:,.0f}" if k in ("orders", "fills") else f"{r[s][k]:,.2f}"
                for k in keys
            ]
            flag = (
                ""
                if "passes" not in r or s != "1.0"
                else (" ✅" if r["passes"] else " ❌")
            )
            lines.append(f"| {name}{flag} | {s} | " + " | ".join(cells) + " |")
    return lines


def report(results):
    d = results["1_decomposition"]
    lines = [
        "# Market-making ideas on the 2025-26 replay (simulated, in-sample)",
        "",
        "Plan: RESEARCH_LOG.md, 2026-10-21. One contract per order, v5-like caps,",
        "fills as if first in line (flow share 1.0) and with a quarter of the",
        "trading reaching us (0.25, 10 draws). ✅/❌ = the plan's pass bar.",
        "",
        "## 1. Where the profit per filled contract comes from (cents)",
        "",
        "| Flow share | Filled | ¢ per contract | Entry edge | Model error (unfilled) | Adverse selection (filled − unfilled) | t | Design effect | Within-game corr. |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in map(str, SHARES):
        r = d[s]
        lines.append(
            f"| {s} | {r['filled_contracts']:,.0f} | {r['cents_per_contract']:+.2f} | "
            f"{r['entry_edge']:+.2f} | {r['model_error_unfilled']:+.2f} | "
            f"{r['adverse_selection']:+.2f} | {r['t_adverse_selection']:.2f} | "
            f"{r['design_effect']:.2f} | {r['within_game_correlation']:.3f} |"
        )
    a = d["all_orders_uncapped"]
    lines += [
        "",
        (
            f"All {a['orders']:,} replay orders, no caps: adverse selection "
            f"{a['adverse_selection']:+.2f}¢ (t {a['t_adverse_selection']:.2f})."
        ),
        "",
        "## 2. Minimum edge",
        "",
        *table(
            results["2_min_edge"],
            [
                "fills",
                "cents_per_contract",
                "t",
                "pnl",
                "pnl_h1",
                "pnl_h2",
                "max_drawdown",
            ],
        ),
        "",
        "## 3. Posting time",
        "",
        *table(
            results["3_posting_time"],
            ["orders", "fills", "cents_per_contract", "t", "pnl", "pnl_h1", "pnl_h2"],
        ),
        "",
        "## 4. Same-game inventory penalty",
        "",
        *table(
            results["4_inventory"],
            [
                "fills",
                "pnl",
                "sharpe",
                "sharpe_h1",
                "sharpe_h2",
                "worst_night",
                "max_drawdown",
            ],
        ),
        "",
        "## 5. Quote choice by P(fill) × edge (second half only)",
        "",
        "| Flow share | Orders | Choice ¢/100 orders | Control ¢/100 | Difference | t | Chosen |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    q = results["5_quote_choice"]
    for s in map(str, SHARES):
        r = q[s]
        lines.append(
            f"| {s} | {r['eligible_orders_second_half']:,} | {r['choice_per_100_orders_cents']:+.1f} | "
            f"{r['control_per_100_orders_cents']:+.1f} | {r['difference_per_100_orders_cents']:+.1f} | "
            f"{r['t_difference']:.2f} | {r['chosen_share']} |"
        )
    lines += ["", f"Passes: {'✅' if q['passes'] else '❌'}", ""]
    return "\n".join(lines)


def main():
    orders = load_orders()
    trades = load_trades()
    candles = load_candles()
    split = season_split(orders)
    u = uniforms(orders.ticker)
    results = {
        "split_date": str(split),
        "1_decomposition": decomposition(orders, u, split),
        "2_min_edge": min_edge_test(orders, u, split),
        "3_posting_time": posting_time_test(orders, candles, trades, u, split),
        "4_inventory": inventory_test(orders, u, split),
        "5_quote_choice": quote_choice_test(orders, trades, candles, u, split),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "article_tests.json").write_text(
        json.dumps(results, indent=1, default=float) + "\n"
    )
    text = report(results)
    (OUT / "article_tests.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
