"""NBA rules v5 (1 contract) against v6 (3 contracts) on the 2025-26 replay
(exploratory, simulated, in-sample).

RESEARCH_LOG.md, "2026-10-23: NBA rules v6". Built on
``research.fill_sizing_replay``: every order the rule would have posted, filled
from public trade prints first in line (flow share 1) or with each traded
contract reaching us with probability 0.25 (20 random draws, medians). The
live caps are applied in placement order; an order that does not fit is
skipped (the live bot shrinks it instead, so this slightly undercounts fills
near a cap). Loss stops are per night: a night losing $20 or more blocks the
next night; the total stop ends the season.

    python -m research.nba_v6_replay   # outputs/research/nba_v6_replay.{json,md}
"""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from research import fill_sizing_replay as R

OUT = Path("outputs/research")
V5 = R.Rules(
    "v5: 1 contract",
    contracts=1,
    band=(0.05, 0.95),
    per_game=40,
    game_usd=25,
    team_usd=25,
    day_usd=150,
    life_usd=2000,
    day_stop=20,
    cum_stop=60,
)
V6 = replace(
    V5, name="v6: 3 contracts", contracts=3, game_usd=50, life_usd=5000, cum_stop=100
)
V6_SEASON = replace(V6, name="v6 without the lifetime allowance", life_usd=None)
DRAWS = 20


def run(orders, rules, seed=0):
    """One season under ``rules``, with loss-stop and allowance counters."""
    q = R._candidates(orders, rules)
    traded = np.floor(q.through.to_numpy()).astype(np.int64)
    if rules.flow_share < 1:
        traded = np.random.default_rng(seed).binomial(traded, rules.flow_share)
    filled = np.minimum(traded, rules.contracts).astype(float)
    per_contract = q.pnl_c.to_numpy()
    games, teams, days = q.game_id.to_numpy(), q.team.to_numpy(), q.day.to_numpy()
    cost = R._costs(q, rules)
    caps, placed = R._Caps(rules), np.zeros(len(q), dtype=bool)
    nightly, blocked, total = {}, False, 0.0
    day_stops, stop_night, allowance_night = 0, None, None
    for day in sorted(set(days)):
        if stop_night is not None:
            break
        if blocked:
            blocked = False
            continue
        rows = np.flatnonzero(days == day)
        for i in rows:
            placed[i] = caps.admit(games[i], teams[i], day, cost[i])
        night = float((filled[rows] * per_contract[rows] * placed[rows]).sum())
        if placed[rows].any():
            nightly[day] = night
        if (
            rules.life_usd
            and allowance_night is None
            and caps.lifetime > rules.life_usd - rules.contracts * R.RESERVE
        ):
            allowance_night = len(nightly)
        total += night
        blocked = night <= -rules.day_stop
        day_stops += int(blocked)
        if total <= -rules.cum_stop:
            stop_night = len(nightly)
    pnl = pd.Series(nightly, dtype=float)
    got = filled * placed
    mean, t = R.clustered_mean_t(per_contract[placed], got[placed], games[placed])
    curve = pnl.cumsum().to_numpy()
    peak = np.maximum.accumulate(np.r_[0.0, curve])[1:]
    return {
        "nights traded": len(pnl),
        "filled orders": int((got > 0).sum()),
        "contracts filled": int(got.sum()),
        "cents per contract": round(100 * mean, 2),
        "t (game-clustered)": round(t, 2),
        "P&L $": round(float(pnl.sum()), 2),
        "worst night $": round(float(pnl.min()), 2),
        "max drawdown $": round(float((curve - peak).min()), 2),
        "nights the daily stop fired": day_stops,
        "total stop hit on night": stop_night,
        "allowance used up by night": allowance_night,
    }


def cautious(orders, rules):
    """Medians over DRAWS runs at flow share 0.25, plus the spread of outcomes."""
    d = pd.DataFrame(
        [run(orders, replace(rules, flow_share=0.25), s) for s in range(DRAWS)]
    )
    out = {k: round(float(v), 2) for k, v in d.median(numeric_only=True).items()}
    out["P&L $, 10th percentile"] = round(float(d["P&L $"].quantile(0.1)), 2)
    out["max drawdown $, worst draw"] = round(float(d["max drawdown $"].min()), 2)
    out["share of draws hitting the total stop"] = float(
        d["total stop hit on night"].notna().mean()
    )
    return out


def main():
    orders = R.load_orders()
    result = {
        "note": "SIMULATED, in-sample, exploratory; 2025-26 NBA NO orders",
        "rules": {},
    }
    for rules in (V5, V6, V6_SEASON):
        result["rules"][rules.name] = {
            "flow share 1 (first in line)": run(orders, rules),
            f"flow share 0.25 (median of {DRAWS} draws)": cautious(orders, rules),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nba_v6_replay.json").write_text(json.dumps(result, indent=1) + "\n")
    lines = [
        "# NBA v5 against v6 (SIMULATED, in-sample, exploratory)",
        "",
        "| Rules | Flow share | P&L $ | ¢/contract (t) | Filled orders | Contracts | Worst night $ | Max drawdown $ | Daily stops |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, block in result["rules"].items():
        for flow, r in block.items():
            lines.append(
                f"| {name} | {flow} | {r['P&L $']:.2f} | {r['cents per contract']:.2f} "
                f"({r['t (game-clustered)']:.2f}) | {r['filled orders']:,.0f} | "
                f"{r['contracts filled']:,.0f} | {r['worst night $']:.2f} | "
                f"{r['max drawdown $']:.2f} | {r['nights the daily stop fired']:g} |"
            )
    (OUT / "nba_v6_replay.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
