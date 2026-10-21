"""Fill and sizing replay for resting NBA NO orders, 2025-26 (exploratory).

Answers "how many fills a night, how much profit and how big a drawdown,
under rule set X?" for the passive-NO rule, by replaying every order the
rule would have posted last season against Kalshi's public trade prints.

Assumptions, all of which make the numbers optimistic:

- In-sample: the rules were chosen on this same season.
- Fills: an order fills up to the contracts a YES taker bought at a better
  price than ours (or at our price, when our quote improved the market and
  we were alone there) before tip-off, as if first in line. ``flow_share``
  below 1 gives each such contract only that chance of reaching us.
- No maker fee: NBA prop series reported no maker fee in October 2026
  metadata. Earlier research-log entries charged a quarter of the taker fee.
- One snapshot per market (mostly five hours before tip), resting to tip.
- Other traders do not react to our orders, however large.

Loss stops are approximated per night: settlements land after the games, so
a night that loses ``day_stop`` or more blocks the next night, and a
cumulative loss of ``cum_stop`` ends the season.

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
    life_usd: float | None = None  # reserved dollars placed, ever (never resets)
    day_stop: float | None = None  # a night losing this much blocks the next night
    cum_stop: float | None = None  # stop for the season after this total loss
    flow_share: float = 1.0
    edge_shave: float = 0.0  # subtract from every contract's result


RULE_SETS = (
    Rules(
        "Live now: 2 contracts, 3c edge, 10/game, $75 a night, $1,000 lifetime",
        contracts=2,
        min_edge=0.03,
        per_game=10,
        game_usd=15,
        team_usd=10,
        day_usd=75,
        life_usd=1000,
        day_stop=20,
        cum_stop=60,
    ),
    Rules(
        "Live now without the $1,000 lifetime allowance",
        contracts=2,
        min_edge=0.03,
        per_game=10,
        game_usd=15,
        team_usd=10,
        day_usd=75,
        day_stop=20,
        cum_stop=60,
    ),
    Rules(
        "2 contracts, 0c edge, 25/game, $150 a night",
        contracts=2,
        per_game=25,
        game_usd=30,
        team_usd=30,
        day_usd=150,
        day_stop=25,
        cum_stop=75,
    ),
    Rules(
        "Most fills: 1 contract, 0c edge, 5-95c, 40/game, $150 a night",
        band=(0.05, 0.95),
        per_game=40,
        game_usd=25,
        team_usd=25,
        day_usd=150,
        day_stop=25,
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
    o["edge"] = (1 - o.p_model) - o.price  # NBA props: no maker fee assumed
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
    """Contracts a YES taker bought through each order's price, pre-tip."""
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


def _candidates(orders, rules):
    """Orders passing the filters, in the live bot's placement order."""
    q = orders[orders.edge >= rules.min_edge - 1e-9]
    if rules.edge_cap is not None:
        q = q[q.edge <= rules.edge_cap + 1e-9]
    q = q[q.price.between(*rules.band)]
    return q.sort_values(["day", "tip_ts", "edge"], ascending=[True, True, False])


class _Caps:
    """Running cap usage; an order that does not fit is skipped, not resized."""

    def __init__(self, rules):
        self.rules = rules
        self.per_game, self.game_usd, self.team_usd, self.day_usd = {}, {}, {}, {}
        self.lifetime = 0.0

    def admit(self, game, team, day, cost):
        r, key = self.rules, (team, day)
        checks = (
            r.per_game and self.per_game.get(game, 0) >= r.per_game,
            r.game_usd and self.game_usd.get(game, 0) + cost > r.game_usd + 1e-9,
            r.team_usd and self.team_usd.get(key, 0) + cost > r.team_usd + 1e-9,
            r.day_usd and self.day_usd.get(day, 0) + cost > r.day_usd + 1e-9,
            r.life_usd and self.lifetime + cost > r.life_usd + 1e-9,
        )
        if any(checks):
            return False
        self.per_game[game] = self.per_game.get(game, 0) + 1
        self.game_usd[game] = self.game_usd.get(game, 0) + cost
        self.team_usd[key] = self.team_usd.get(key, 0) + cost
        self.day_usd[day] = self.day_usd.get(day, 0) + cost
        self.lifetime += cost
        return True


def _costs(q, rules):
    return np.round(rules.contracts * q.price.to_numpy() * RESERVE, 2)


def select(orders, rules):
    """Orders the rules would place over the season, ignoring loss stops."""
    q = _candidates(orders, rules)
    caps = _Caps(rules)
    rows = zip(q.game_id.to_numpy(), q.team.to_numpy(), q.day.to_numpy())
    keep = [caps.admit(g, t, d, c) for (g, t, d), c in zip(rows, _costs(q, rules))]
    return q[np.asarray(keep, dtype=bool)]


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
    q = _candidates(orders, rules)
    traded = np.floor(q.through.to_numpy()).astype(np.int64)
    if rules.flow_share < 1:
        traded = np.random.default_rng(seed).binomial(traded, rules.flow_share)
    filled = np.minimum(traded, rules.contracts).astype(float)
    per_contract = q.pnl_c.to_numpy() - rules.edge_shave
    games, teams, days = q.game_id.to_numpy(), q.team.to_numpy(), q.day.to_numpy()
    cost = _costs(q, rules)
    caps, placed = _Caps(rules), np.zeros(len(q), dtype=bool)
    nightly, blocked, stopped, total = {}, False, False, 0.0
    for day in sorted(set(days)):
        if stopped:
            break
        if blocked:  # yesterday's settled losses hit the daily stop
            blocked = False
            continue
        rows = np.flatnonzero(days == day)
        for i in rows:
            placed[i] = caps.admit(games[i], teams[i], day, cost[i])
        night = float((filled[rows] * per_contract[rows] * placed[rows]).sum())
        if placed[rows].any():
            nightly[day] = night
        total += night
        blocked = rules.day_stop is not None and night <= -rules.day_stop
        stopped = rules.cum_stop is not None and total <= -rules.cum_stop
    pnl = pd.Series(nightly, dtype=float)
    nights = max(len(pnl), 1)
    got = filled * placed
    mean, t = clustered_mean_t(per_contract[placed], got[placed], games[placed])
    curve = pnl.cumsum().to_numpy()
    peak = np.maximum.accumulate(np.r_[0.0, curve])[1:]  # drawdown from $0
    return {
        "rules": rules.name,
        "nights with orders": len(pnl),
        "orders a night": round(placed.sum() / nights, 1),
        "filled orders a night": round((got > 0).sum() / nights, 1),
        "contracts filled": int(got.sum()),
        "cents per contract": round(100 * mean, 2),
        "t (game-clustered)": round(t, 2),
        "season P&L $": round(float(pnl.sum()), 2),
        "worst night $": round(float(pnl.min()), 2) if len(pnl) else 0.0,
        "max drawdown $": round(float((curve - peak).min()), 2) if len(pnl) else 0.0,
        "placed, lifetime $": round(caps.lifetime, 2),
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
