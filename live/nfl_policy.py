"""Shared NFL limits and account arithmetic, without analysis-library imports."""

import math
from pathlib import Path

from kalshi.trading import TradingError

MAX_GROSS_COST = 50.0
MAX_ORDER_COST = 3.0
MAX_ACTIVE_COST = 15.0
MAX_GAME_COST = 3.0
MAX_TEAM_COST = 3.0
MAX_DAILY_COST = 30.0
MAX_GAME_ORDERS = 2
MAX_CONTRACTS = 5
FEE_RESERVE = 1.10
STRATEGY_VERSION = "nfl-no-v2-reserved-edge"
MIN_RESERVED_EDGE = 0.03
STATE = Path("/home/trader/prod-nfl-auto")


def money(n):
    value = float(n)
    if not math.isfinite(value) or value < 0:
        raise TradingError(f"Invalid risk value {n!r}")
    return round(value, 4)


def reserve(cost):
    return math.ceil(money(cost) * FEE_RESERVE * 100 - 1e-8) / 100


def settlement_accounting(result):
    """Normalize the exchange's dollar costs/fees and cent revenue explicitly."""

    def amount(dollars_key, cents_key=None):
        value = result.get(dollars_key)
        divisor = 1
        if value is None and cents_key:
            value = result.get(cents_key)
            divisor = 100
        if value is None:
            return None
        try:
            parsed = float(value) / divisor
        except (TypeError, ValueError):
            return None
        return round(parsed, 6) if math.isfinite(parsed) and parsed >= 0 else None

    revenue = amount("revenue_dollars", "revenue")
    yes_cost = amount("yes_total_cost_dollars", "yes_total_cost")
    no_cost = amount("no_total_cost_dollars", "no_total_cost")
    fee = amount("fee_cost")  # API fee_cost is in dollars, including legacy costs.
    complete = all(v is not None for v in (revenue, yes_cost, no_cost, fee))
    return {
        "accounting_version": 2,
        "revenue_dollars": revenue,
        "yes_cost_dollars": yes_cost,
        "no_cost_dollars": no_cost,
        "fee_dollars": fee,
        "accounting_complete": complete,
        "net_profit_dollars": (
            round(revenue - yes_cost - no_cost - fee, 6) if complete else None
        ),
    }
