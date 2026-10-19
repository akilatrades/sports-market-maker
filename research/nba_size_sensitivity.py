"""Bounded NBA budget replays using the Oct 18 two-book *possible fills*.

WARNING: Input rows were preselected because a public print could have
filled a hypothetical maker order. Unfilled opportunities, actual queue,
four-hour book timestamps, contemporaneous injuries, pilot concurrency,
new-season role changes and 1h order expiry CANNOT be reconstructed here.
Results are conditional historical sensitivity, not a new holdout or a
prediction of opening-night profits. No exchange access or orders.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("outputs/bookline/fills_with_book.csv.gz")
OUT = Path("outputs/sizing/nba_oct2026_sensitivity.json")
SEED = 20261019


@dataclass(frozen=True)
class Policy:
    name: str
    lifetime: float
    order: float
    game: float
    team: float
    daily: float
    active: float
    contracts: int


POLICIES = (
    Policy("current_50_lifetime", 50.0, 3.0, 3.0, 3.0, 30.0, 15.0, 5),
    Policy("250_cash_unchanged_caps", 50.0, 3.0, 3.0, 3.0, 30.0, 15.0, 5),
    Policy("moderate_75_lifetime", 75.0, 4.5, 4.5, 4.5, 45.0, 22.5, 8),
    Policy("fivefold_250_lifetime", 250.0, 15.0, 15.0, 15.0, 150.0, 75.0, 25),
)


def fee_per_contract(price):
    # Conservative whole-contract rounding as in nba_launch_audit.py.
    return math.ceil(1.75 * price * (1 - price) - 1e-12) / 100


def prepare(raw, window=True):
    q = raw[
        raw.price.between(0.1, 0.9)
        & raw.book_edge.between(0, 0.15)
        & (raw.book_n >= 2)
    ].copy()
    strict_two_book_rows = len(q)
    if window:
        q = q[pd.to_numeric(q.hours_before, errors="coerce").between(2, 6)]
    window_rows = len(q)
    q = q[pd.to_numeric(q.filled_contracts, errors="coerce").fillna(0) > 0]
    q["price"] = pd.to_numeric(q.price)
    q["pnl"] = pd.to_numeric(q.pnl_no_fee) - q.price.map(fee_per_contract)
    q["filled_contracts"] = pd.to_numeric(q.filled_contracts)
    q["tip_utc"] = pd.to_datetime(q.tip_utc, utc=True)
    # Rank by contemporaneously assumed book_edge, not realized profit.
    # WARNING: historical book observations may have arrived after listing.
    q = q.sort_values(
        ["game_id", "book_edge", "hours_before", "ticker"],
        ascending=[True, False, False, True],
        kind="stable",
    ).drop_duplicates("game_id")
    q = q.sort_values(["tip_utc", "game_id"], kind="stable").reset_index(drop=True)
    return q, {
        "two_book_possible_fill_rows": strict_two_book_rows,
        "within_2_to_6_hours_possible_fill_rows": window_rows,
        "distinct_games_with_candidates": len(q),
    }


def max_contracts(price, limit, cap):
    if not math.isfinite(price) or not 0.1 <= price <= 0.9:
        return 0
    # Reserve cost rounded UP to cents, then check each cap.
    for n in range(cap, 0, -1):
        reserved = math.ceil(n * price * 1.1 * 100 - 1e-9) / 100
        if reserved <= limit + 1e-9:
            return n
    return 0


def replay(rows, policy, *, fill_capture=1.0, extra_drag_c=0.0):
    """One preselected historical possible fill per game, earliest game first.

    Submitting the order spends lifetime/day allowance even if unfilled.
    No cost recycling. This omits intraday active concurrency and feed/
    quote failures; cannot be used as a full live worker profit estimate.
    """
    remaining = policy.lifetime
    result = {"placed": 0, "filled": 0, "contracts": 0, "reserve": 0.0,
              "filled_cost": 0.0, "profit": 0.0, "games": 0,
              "days": set()}
    reserved_day = {}
    for r in rows:
        date = str(pd.Timestamp(r["tip_utc"]).date())
        left_day = policy.daily - reserved_day.get(date, 0.0)
        limit = min(
            remaining, left_day, policy.order, policy.game, policy.team,
            policy.active,
        )
        n = max_contracts(float(r["price"]), limit, policy.contracts)
        if n < 1:
            continue
        reserve = math.ceil(n * float(r["price"]) * 1.1 * 100 - 1e-9) / 100
        remaining = round(remaining - reserve, 5)
        reserved_day[date] = reserved_day.get(date, 0.0) + reserve
        result["placed"] += 1
        result["games"] += 1
        result["reserve"] += reserve
        result["days"].add(date)
        # Public print volume is NOT own fill probability. This is a
        # counterfactual capture fraction of historical traded volume.
        got = min(n, max(0, math.floor(fill_capture * float(r["filled_contracts"]))))
        if got:
            result["filled"] += 1
            result["contracts"] += got
            result["filled_cost"] += got * float(r["price"])
            result["profit"] += got * (float(r["pnl"]) - extra_drag_c / 100)
    result["days"] = len(result["days"])
    for k in ("reserve", "filled_cost", "profit"):
        result[k] = round(result[k], 2)
    return result


def boot_replay(rows, policy, n=800, seed=SEED):
    """Cluster bootstrap of *game candidates*, selected possible fills only.

    Samples independent games with replacement. Equal opportunity count,
    one game per synthetic date to avoid manufacturing repeated day caps.
    The uncertainty is CONDITIONAL on the contaminated filled-only sample.
    """
    rng = np.random.default_rng(seed)
    base = rows.to_dict("records")
    if not base:
        return {}
    vals = []
    for _ in range(n):
        sample = pd.DataFrame([base[i] for i in rng.integers(0, len(base), len(base))])
        sample["tip_utc"] = pd.date_range(
            "2025-10-01", periods=len(sample), freq="D", tz="UTC"
        )
        vals.append(replay(sample.to_dict("records"), policy)["profit"])
    return {
        "replications": n,
        "median_profit": round(float(np.median(vals)), 2),
        "p05_profit": round(float(np.percentile(vals, 5)), 2),
        "p95_profit": round(float(np.percentile(vals, 95)), 2),
        "fraction_negative": round(float(np.mean(np.asarray(vals) < 0)), 3),
        "warning": "Conditional-on-hypothetical-fill bootstrap; not a trading forecast.",
    }


def main():
    raw = pd.read_csv(DATA, low_memory=False)
    rows, diagnostic = prepare(raw, window=True)
    wider, diag_wide = prepare(raw, window=False)
    # 2-6h is the live policy; all-hours is an intentionally unsuitable
    # historical reference to show how much data ceases to be comparable.
    out = {
        "source": str(DATA),
        "selection": diagnostic,
        "reference_without_live_entry_window": diag_wide,
        "fee_assumption": "ceil to cent for one-contract 0.0175*p*(1-p)",
        "capital_vs_limits": "All scenarios assume $250 capital; only limits alter throughput.",
        "historical_replay_one_eligible_print_fill_per_game": {},
        "bootstrap_game_conditional": {},
        "drag_sensitivity": {},
        "capture_sensitivity": {},
        "not_reproduced": [
            "unfilled historical quote denominator",
            "actual queue priority",
            "one-hour order expiry and polling latency",
            "live quote/fee/roster/injury revalidation",
            "team-level correlation beyond one selected order per game",
            "live capital recycling or settled bankroll path",
        ],
    }
    for policy in POLICIES:
        out["historical_replay_one_eligible_print_fill_per_game"][policy.name] = replay(
            rows.to_dict("records"), policy
        )
        out["bootstrap_game_conditional"][policy.name] = boot_replay(rows, policy)
        out["drag_sensitivity"][policy.name] = {
            f"extra_{drag}c": replay(
                rows.to_dict("records"), policy, extra_drag_c=drag
            )["profit"] for drag in (0, 1, 2, 4)
        }
        out["capture_sensitivity"][policy.name] = {
            f"public_print_capture_{int(capture*100)}pct": replay(
                rows.to_dict("records"), policy, fill_capture=capture
            )
            for capture in (0.25, 0.5, 1.0)
        }
    print("NBA HISTORICAL SIZING REPLAY RESULTS (NOT LIVE/NOT OUT-OF-SAMPLE)")
    print(json.dumps(out, indent=2, allow_nan=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
