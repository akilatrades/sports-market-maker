"""Fill and sizing replay for resting NBA NO orders, 2025-26 (exploratory).

Answers "how many fills a night, how much profit and how big a drawdown,
under rule set X?" for the passive-NO rule, by replaying every order the
rule would have posted last season against Kalshi's public trade prints.

Assumptions, all of which make the numbers optimistic:

- In-sample: the rules were chosen on this same season.
- Fills: an order fills up to the contracts that traded at or through its
  price before tip-off, as if it were first in line. ``flow_share`` < 1
  gives each traded contract only that chance of reaching us.
- One snapshot per market (mostly five hours before tip), resting to tip.
- Other traders do not react to our orders, however large.

Results are a planning aid, not a forecast. See RESEARCH_LOG.md
(2026-10-21: fill and sizing replay).

    python -m research.fill_sizing_replay            # both tables
    python -m research.fill_sizing_replay rules      # live rules vs alternatives
    python -m research.fill_sizing_replay capacity   # contracts-per-order sweep
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ORDERS = Path("outputs/decompose/orders_no.csv.gz")
SERIES = ("KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT")
TRADES = tuple(Path(f"data/kalshi_history/trades_{s}.parquet") for s in SERIES)
RESERVE = 1.10  # the live bots reserve price x 1.10 per contract


@dataclass(frozen=True)
class Rules:
    """One rule set. ``None`` switches a limit off."""

    name: str
    contracts: int = 1
    min_edge: float = 0.0
    edge_cap: float | None = 0.15
    band: tuple[float, float] = (0.10, 0.90)
    per_game: int | None = None  # orders per game
    game_usd: float | None = None  # reserved dollars per game
    team_usd: float | None = None  # reserved dollars per team per day
    day_usd: float | None = None  # reserved dollars placed per day
    cum_stop: float | None = None  # stop for the season after this loss
    flow_share: float = 1.0
    edge_shave: float = 0.0  # subtract from every contract's result


RULE_SETS = (
    Rules(
        "Live now: 2 contracts, 3c edge, 10/game, $75 a night",
        contracts=2,
        min_edge=0.03,
        per_game=10,
        game_usd=15,
        team_usd=10,
        day_usd=75,
        cum_stop=60,
    ),
    Rules(
        "2 contracts, 0c edge, 25/game, $150 a night",
        contracts=2,
        per_game=25,
        game_usd=30,
        team_usd=30,
        day_usd=150,
        cum_stop=75,
    ),
    Rules(
        "Most fills: 1 contract, 0c edge, 5-95c, 40/game, $150 a night",
        band=(0.05, 0.95),
        per_game=40,
        game_usd=25,
        team_usd=25,
        day_usd=150,
        cum_stop=75,
    ),
)
CAPACITY_SIZES = (1, 2, 5, 10, 25, 100, 250, 1000)


def load_orders(orders_path=ORDERS, trade_paths=TRADES):
    """One candidate order per market, with traded-through volume and result."""
    o = pd.read_csv(orders_path, low_memory=False)
    for col in ("over", "p_model", "price", "tip_ts", "end_ts", "yes_level"):
        o[col] = o[col].astype(float)
    o["improved"] = o.improved.astype(str).str.lower().eq("true")
    o = o.drop_duplicates("ticker").copy()
    o["edge"] = (1 - o.p_model) - o.price  # NBA props charge no maker fee
    o["day"] = (
        pd.to_datetime(o.tip_ts, unit="s", utc=True)
        .dt.tz_convert("America/New_York")
        .dt.date
    )
    o["pnl_c"] = (1 - o.over) - o.price  # per filled contract
    trades = pd.concat([pd.read_parquet(p) for p in trade_paths], ignore_index=True)
    o["through"] = through_volume(o, trades)
    return o


def through_volume(orders, trades):
    """Contracts a YES taker bought at or through each order's price, pre-tip."""
    t = trades.copy()
    created = pd.to_datetime(t.created_time, utc=True, format="ISO8601")
    # Unix seconds, whatever resolution pandas chose for the parsed times.
    t["ts"] = created.dt.tz_convert(None).to_numpy().astype("datetime64[s]")
    t["ts"] = t.ts.astype("int64")
    t["yes_price"] = t.yes_price.astype(float)
    t["count"] = t["count"].astype(float)
    cols = ["ticker", "end_ts", "tip_ts", "yes_level", "improved"]
    tt = t.merge(orders[cols], on="ticker")
    tt = tt[(tt.ts > tt.end_ts) & (tt.ts <= tt.tip_ts)]
    same = (tt.yes_price - tt.yes_level).abs() < 1e-6
    better = tt.yes_price > tt.yes_level + 1e-6
    # At an equal price we only count trades when we improved the quote,
    # i.e. were alone at that level.
    hit = tt.taker_outcome_side.eq("yes") & (better | (same & tt.improved))
    by_ticker = tt[hit].groupby("ticker")["count"].sum()
    return orders.ticker.map(by_ticker).fillna(0.0).to_numpy()


def select(orders, rules):
    """Orders the rules would place, charging caps in the live bot's order."""
    q = orders[orders.edge >= rules.min_edge - 1e-9]
    if rules.edge_cap is not None:
        q = q[q.edge <= rules.edge_cap + 1e-9]
    q = q[q.price.between(*rules.band)]
    q = q.sort_values(["day", "tip_ts", "edge"], ascending=[True, True, False])
    cost = np.round(rules.contracts * q.price.to_numpy() * RESERVE, 2)
    per_game, game_usd, team_usd, day_usd = {}, {}, {}, {}
    keep = np.zeros(len(q), dtype=bool)
    rows = zip(q.game_id.to_numpy(), q.team.to_numpy(), q.day.to_numpy(), cost)
    for i, (game, team, day, c) in enumerate(rows):
        if rules.per_game and per_game.get(game, 0) >= rules.per_game:
            continue
        if rules.game_usd and game_usd.get(game, 0) + c > rules.game_usd + 1e-9:
            continue
        key = (team, day)
        if rules.team_usd and team_usd.get(key, 0) + c > rules.team_usd + 1e-9:
            continue
        if rules.day_usd and day_usd.get(day, 0) + c > rules.day_usd + 1e-9:
            continue
        per_game[game] = per_game.get(game, 0) + 1
        game_usd[game] = game_usd.get(game, 0) + c
        team_usd[key] = team_usd.get(key, 0) + c
        day_usd[day] = day_usd.get(day, 0) + c
        keep[i] = True
    return q[keep]


def clustered_mean_t(values, weights, clusters):
    """Weighted mean and game-clustered t; equals kalshi.stats on repeated rows."""
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    total = weights.sum()
    if total < 2:
        return np.nan, np.nan
    mean = (weights * values).sum() / total
    sums = pd.Series(weights * (values - mean)).groupby(np.asarray(clusters)).sum()
    g = len(sums)
    se = np.sqrt((sums**2).sum() * g / (g - 1)) / total if g > 1 else np.nan
    return mean, mean / se if se and se > 0 else np.nan


def simulate(orders, rules, seed=0):
    """Season result for one rule set (one random draw if flow_share < 1)."""
    q = select(orders, rules)
    nights = q.day.nunique()
    traded = np.floor(q.through.to_numpy()).astype(np.int64)
    if rules.flow_share < 1:
        traded = np.random.default_rng(seed).binomial(traded, rules.flow_share)
    filled = np.minimum(traded, rules.contracts).astype(float)
    per_contract = q.pnl_c.to_numpy() - rules.edge_shave
    pnl = pd.Series(filled * per_contract).groupby(q.day.to_numpy()).sum()
    stopped = False
    if rules.cum_stop is not None:
        hit = pnl.cumsum() <= -rules.cum_stop
        if hit.any():
            stopped = True
            pnl = pnl[pnl.index <= hit.idxmax()]
    played = q.day.isin(pnl.index).to_numpy()
    mean, t = clustered_mean_t(
        per_contract[played], filled[played], q.game_id.to_numpy()[played]
    )
    curve = pnl.cumsum()
    return {
        "rules": rules.name,
        "orders a night": round(len(q) / nights, 1),
        "filled orders a night": round((filled > 0).sum() / nights, 1),
        "contracts filled": int(filled[played].sum()),
        "cents per contract": round(100 * mean, 2),
        "t (game-clustered)": round(t, 2),
        "season P&L $": round(float(pnl.sum()), 2),
        "worst night $": round(float(pnl.min()), 2),
        "max drawdown $": round(float((curve - curve.cummax()).min()), 2),
        "loss stop hit": stopped,
    }


def rules_table(orders):
    return pd.DataFrame([simulate(orders, r) for r in RULE_SETS]).set_index("rules")


def capacity_table(orders, flow_shares=(1.0, 0.25)):
    """Contracts per order vs profit, with no cash limits (25 orders/game)."""
    rows = []
    for share in flow_shares:
        for n in CAPACITY_SIZES:
            rules = Rules(
                f"{n} contracts, flow share {share:g}",
                contracts=n,
                per_game=25,
                flow_share=share,
            )
            rows.append(simulate(orders, rules))
    return pd.DataFrame(rows).set_index("rules")


def main(argv):
    which = argv[0] if argv else "all"
    orders = load_orders()
    pd.set_option("display.width", 200)
    if which in ("all", "rules"):
        print(rules_table(orders).T.to_string(), "\n")
    if which in ("all", "capacity"):
        cols = ["filled orders a night", "contracts filled", "cents per contract"]
        cols += ["t (game-clustered)", "season P&L $", "max drawdown $"]
        print(capacity_table(orders)[cols].to_string())


if __name__ == "__main__":
    main(sys.argv[1:])
