"""Private, read-only NBA forward-validation progress from authenticated account data.

This reports observations, not a profit forecast or statistical proof.
No trade placement, risk-limit reset or exchange write is available here.
"""

import math
from datetime import UTC, datetime, timedelta

from kalshi.trading import TradingError
from live.nfl_policy import reserve
from live.reconciled_attempts import rejected_client_ids

WINDOW_DAYS = 30
NBA_LIFETIME_RESERVE = 50.0
CLOSED_STATES = {"fully_filled", "partially_filled_closed", "confirmed_unfilled"}
FILLED_STATES = {"fully_filled", "partially_filled_resting", "partially_filled_closed"}


def _time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise TradingError("NBA validation has an invalid timestamp") from error
    if dt.tzinfo is None:
        raise TradingError("NBA validation timestamp missing timezone")
    return dt.astimezone(UTC)


def summarize_nba_validation(events, audit, pnl, now):
    """Combine the private NBA journal and *signed* exchange audit only.

    Missing exchange data is unknown, never a zero fill or positive return.
    Submission reserve counts audited rejects, matching the live risk policy.
    """
    if now.tzinfo is None or not isinstance(events, list):
        raise TradingError("Invalid NBA forward-validation input")
    if not isinstance(audit, dict) or not isinstance(pnl, dict):
        raise TradingError("Missing NBA validation sources")
    now = now.astimezone(UTC)
    intents = {}
    accepted = {}
    accepted_clients = set()
    spent = 0.0
    for event in events:
        if not isinstance(event, dict):
            raise TradingError("Invalid journal event")
        if event.get("event") == "intent":
            cid = event.get("client_order_id")
            if not cid or cid in intents:
                raise TradingError("Duplicate or missing NBA intent ID")
            amount = event.get("cost")
            try:
                cost = float(amount)
            except (TypeError, ValueError) as error:
                raise TradingError("Invalid NBA intent cost") from error
            if not math.isfinite(cost) or cost <= 0:
                raise TradingError("Invalid NBA intent cost")
            _time(event.get("utc"))
            spent += reserve(cost)
            intents[cid] = event
        elif event.get("event") == "accepted":
            cid = event.get("client_order_id")
            oid = str(event.get("order_id") or "")
            if (
                cid not in intents
                or not oid
                or oid in accepted
                or cid in accepted_clients
            ):
                raise TradingError("Unreconciled NBA acceptance")
            accepted_clients.add(cid)
            accepted[oid] = (intents[cid], _time(event.get("utc")))
    # An unresolved submission can be live on the exchange even if absent from
    # the accepted journal. Never present that situation as healthy collection.
    rejected = rejected_client_ids(events)
    unresolved = set(intents) - accepted_clients - rejected
    first = min((t for _, t in accepted.values()), default=None)
    if first is not None and first > now + timedelta(minutes=1):
        raise TradingError("NBA journal acceptance timestamp is in the future")
    end = first + timedelta(days=WINDOW_DAYS) if first else None
    basic = {
        "status": "needs_submission_reconciliation"
        if unresolved
        else "awaiting_first_accepted_order"
        if first is None
        else "awaiting_exchange_audit",
        "start_utc": first.isoformat() if first else None,
        "review_due_utc": end.isoformat() if end else None,
        "days_elapsed": max(0, (now - first).days) if first else None,
        "window_days": WINDOW_DAYS,
        "accepted_orders": len(accepted),
        "attempted_orders": len(intents),
        "unresolved_submission_attempts": len(unresolved),
        "reserved_submissions_dollars": round(spent, 2),
        "lifetime_limit_dollars": NBA_LIFETIME_RESERVE,
        "lifetime_allowance_remaining_dollars": round(
            max(0, NBA_LIFETIME_RESERVE - spent), 2
        ),
        "closed_known_orders": None,
        "closed_order_fill_rate": None,
        "confirmed_zero_fill_orders": None,
        "open_orders": None,
        "unknown_orders": None,
        "filled_contracts": None,
        "maker_share": None,
        "independent_games_accepted": None,
        "independent_games_filled": None,
        "settled_profit_dollars": (
            pnl.get("settled_profit_dollars")
            if pnl.get("status") == "verified"
            and isinstance(pnl.get("settled_profit_dollars"), (int, float))
            else None
        ),
        "settled_markets": pnl.get("settled_markets")
        if pnl.get("status") == "verified"
        else None,
        "profit_source": pnl.get("status", "unavailable"),
        "proof_of_edge": False,
        "note": "Descriptive live study; no automatic risk reset. No statistical significance claimed.",
    }
    if first is None:
        return basic
    if audit.get("status") != "verified_snapshot" or not isinstance(
        audit.get("orders"), list
    ):
        return basic
    rows = audit["orders"]
    by_id = {str(row.get("order_id")): row for row in rows if isinstance(row, dict)}
    if len(by_id) != len(rows) or set(by_id) != set(accepted):
        basic["status"] = (
            "needs_submission_reconciliation"
            if unresolved
            else "incomplete_exchange_order_history"
        )
        return basic
    filled = []
    closed = []
    unknown = []
    waiting = []
    for oid, row in by_id.items():
        state = row.get("state")
        count = row.get("filled_contracts")
        maker_count = row.get("maker_filled_contracts")
        if (
            count is None
            or not isinstance(count, (int, float))
            or not math.isfinite(count)
            or count < 0
            or (state in {"resting_no_fill", "confirmed_unfilled"} and count != 0)
            or (
                isinstance(maker_count, (int, float))
                and (
                    not math.isfinite(maker_count)
                    or maker_count < 0
                    or maker_count > count
                )
            )
        ):
            unknown.append(oid)
            continue
        if state in FILLED_STATES and count > 0:
            filled.append(oid)
        elif state in FILLED_STATES:
            unknown.append(oid)
            continue
        elif state not in CLOSED_STATES | {"resting_no_fill"}:
            unknown.append(oid)
        if state in CLOSED_STATES:
            closed.append(oid)
        elif state == "resting_no_fill" or state == "partially_filled_resting":
            waiting.append(oid)
    games_accepted = {intent.get("game_id") for intent, _ in accepted.values()}
    games_filled = {accepted[oid][0].get("game_id") for oid in filled}
    games_complete = None not in games_accepted and all(bool(g) for g in games_accepted)
    filled_games_complete = None not in games_filled and all(
        bool(g) for g in games_filled
    )
    fully_observed = not unknown
    filled_counts = [by_id[oid]["filled_contracts"] for oid in by_id]
    makers = [by_id[oid].get("maker_filled_contracts") for oid in filled]
    maker_known = all(
        isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in makers
    )
    maker_known = maker_known and fully_observed
    full_qty = sum(filled_counts) if fully_observed else None
    basic.update(
        status=(
            "needs_submission_reconciliation"
            if unresolved
            else "needs_exchange_reconciliation"
            if unknown
            else "30_day_review_due"
            if now >= end
            else "collecting_live_outcomes"
        ),
        closed_known_orders=len(closed),
        closed_order_fill_rate=(
            round(sum(oid in filled for oid in closed) / len(closed), 4)
            if closed
            else None
        ),
        confirmed_zero_fill_orders=sum(
            by_id[oid]["state"] == "confirmed_unfilled" for oid in closed
        ),
        open_orders=len(waiting),
        unknown_orders=len(unknown),
        filled_contracts=round(full_qty, 4) if full_qty is not None else None,
        maker_share=(
            round(sum(makers) / full_qty, 4) if maker_known and full_qty else None
        ),
        independent_games_accepted=len(games_accepted) if games_complete else None,
        independent_games_filled=len(games_filled) if filled_games_complete else None,
    )
    return basic
