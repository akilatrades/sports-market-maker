"""Signed GET-only verification of both trading cohorts and shared budgets.

Does not arm service timers, modify risk files, submit, or cancel orders.
Requires production Kalshi reads and the two private journals.
"""

import json
import traceback
from datetime import UTC, datetime

from kalshi.trading import TradingError
from live.account_dashboard import ReadOnlyClient
from live.shared_account_risk import LIMITS, room, state_for


def report(client, now):
    if client.env != "prod" or not client.can_sign:
        raise TradingError("Signed production GET-only Kalshi access required")
    results = {}
    context = None
    for sport in ("nfl", "nba"):
        state, context = state_for(client, sport, now)
        results[sport] = {
            "resting_owned_orders": len(state["resting"]),
            "held_owned_markets": len(state["held"]),
            "active_reserved_attempts": len(state["active"]),
        }
    if context is None:
        raise TradingError("Missing shared account snapshot")
    checks = room(context["ownership"], context["active_client_ids"], 0.01, now)
    # A 1c hypothetical new order is only a *budget read*, NOT an order
    # or signal; do not present it as a launch eligibility prediction.
    return {
        "as_of_utc": now.isoformat(),
        "status": "SHARED_ACCOUNT_RECONCILED",
        "strategy_rows": results,
        "combined_caps_dollars": LIMITS,
        "account_realized_pnl": context["account_pnl"],
        "hypothetical_one_cent_budget_checks": checks,
        "note": "No orders, credentials, balances or market IDs exposed.",
    }


def main():
    try:
        now = datetime.now(UTC)
        # ReadOnlyClient enforces prod-only signed GET access in its constructor.
        client = ReadOnlyClient()
        print(json.dumps(report(client, now), indent=2, sort_keys=True))
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "RECONCILIATION_UNAVAILABLE_DO_NOT_ACTIVATE",
                    "reason_type": type(error).__name__,
                    "safe_trace": [
                        f"{frame.name}:{frame.lineno}"
                        for frame in traceback.extract_tb(error.__traceback__)
                        if "/sports-market-maker-prod-auto/" in frame.filename
                    ][-6:],
                }
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
