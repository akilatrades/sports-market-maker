"""Cross-sport ownership and budget checks. No exchange writes.

Import from the two production workers only while their existing account_lock
is held. Absent, ambiguous or unowned account data must stop new entries.
"""

from datetime import datetime
from pathlib import Path
import json
import math
from zoneinfo import ZoneInfo

from kalshi.trading import TradingError
from live.reconciled_attempts import rejected_client_ids

ROOT = Path("/home/trader")
# Cross-sport caps: NBA (larger fill-measurement sizing) plus NFL's own
# unchanged limits ($50 lifetime, $30 daily, $15 active).
LIMITS = {"lifetime": 1050.0, "daily": 105.0, "active": 90.0}
LOCAL_DAY = ZoneInfo("America/New_York")
# Realized-loss stops for the WHOLE account (NBA + NFL settled markets
# together). Each bot's own limits still apply on top of these.
ACCOUNT_LOSS_STOPS = {"daily": 20.0, "cumulative": 60.0}


def journal_events(sport):
    if sport not in ("nfl", "nba"):
        raise TradingError("Invalid production cohort")
    path = ROOT / f"prod-{sport}-auto" / "journal.jsonl"
    if not path.exists():
        raise TradingError("Missing other-cohort production journal")
    raw = path.read_text()
    if raw and not raw.endswith("\n"):
        raise TradingError("Incomplete production journal")
    try:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (ValueError, TypeError) as error:
        raise TradingError("Invalid production journal") from error


def ownership(events_by_sport):
    orders, tickers, attempts = {}, {}, []
    client_ids = set()
    rejected_tickers = set()
    rejected_by_sport = {}
    for sport in ("nfl", "nba"):
        events = events_by_sport[sport]
        intents = [e for e in events if e.get("event") == "intent"]
        accepted = [e for e in events if e.get("event") == "accepted"]
        rejected = rejected_client_ids(events)
        rejected_by_sport[sport] = rejected
        if any(
            e.get("event") == "unknown_outcome"
            and e.get("client_order_id") not in rejected
            for e in events
        ):
            raise TradingError("Ambiguous production order: HALT")
        by_id = {}
        for e in intents:
            cid, ticker = e.get("client_order_id"), e.get("ticker")
            if not cid or not ticker or cid in client_ids:
                raise TradingError("Duplicate or incomplete production intent")
            try:
                ts = datetime.fromisoformat(e["utc"])
                amount = float(e["cost"])
            except (ValueError, TypeError, KeyError) as error:
                raise TradingError("Invalid production intent") from error
            if ts.tzinfo is None or not math.isfinite(amount) or amount <= 0:
                raise TradingError("Invalid production intent fields")
            if ticker in tickers and tickers[ticker] != sport:
                raise TradingError("Overlapping markets between production bots")
            client_ids.add(cid)
            tickers[ticker] = sport
            by_id[cid] = e
            if cid in rejected:
                rejected_tickers.add(ticker)
            attempts.append({**e, "_cohort": sport})
        seen = set()
        for e in accepted:
            cid, oid = e.get("client_order_id"), e.get("order_id")
            if not oid or cid not in by_id or cid in seen or str(oid) in orders:
                raise TradingError("Invalid production acceptance")
            seen.add(cid)
            orders[str(oid)] = sport
        if seen != set(by_id) - rejected:
            raise TradingError("Unreconciled production submission: HALT")
    return {
        "orders": orders,
        "tickers": tickers,
        "attempts": attempts,
        "rejected_tickers": rejected_tickers,
        "rejected_by_sport": rejected_by_sport,
    }


def classify(resting, positions, owner):
    """Return only cohort-owned open orders/NO positions; fail on manual risk."""
    if not isinstance(resting, list) or not isinstance(positions, list):
        raise TradingError("Invalid production account snapshot")
    result = {s: {"resting": [], "held": []} for s in ("nfl", "nba")}
    for row in resting:
        sport = owner["orders"].get(str(row.get("order_id")))
        if sport not in result:
            raise TradingError("Unowned resting order: HALT")
        result[sport]["resting"].append(row)
    for row in positions:
        try:
            raw = row.get("position_fp")
            if raw is None:
                raw = row.get("position")
            qty = float(raw)
        except (TypeError, ValueError) as error:
            raise TradingError("Unreadable account position") from error
        if not math.isfinite(qty):
            raise TradingError("Nonfinite account position")
        if abs(qty) < 1e-9:
            continue
        ticker = row.get("market_ticker") or row.get("ticker")
        sport = owner["tickers"].get(ticker)
        if ticker in owner.get("rejected_tickers", set()):
            raise TradingError("Position appeared for reconciled rejected order: HALT")
        if sport not in result or qty > 0:
            raise TradingError("Unowned or wrong-side account position: HALT")
        owned_count = sum(
            float(a["count"]) for a in owner["attempts"] if a["ticker"] == ticker
        )
        if abs(qty) > owned_count + 1e-8:
            raise TradingError("Held inventory exceeds accepted intent: HALT")
        result[sport]["held"].append(ticker)
    return result


def room(owner, active_client_ids, cost, now):
    """Global admission requires previously verified active-order identities."""
    if now.tzinfo is None:
        raise TradingError("Current timestamp has no timezone")
    attempts = owner["attempts"]
    ids = {a["client_order_id"] for a in attempts}
    if not isinstance(active_client_ids, set) or not active_client_ids <= ids:
        raise TradingError("Unreconciled shared active capacity")
    from live.nfl_policy import reserve

    try:
        proposed = reserve(cost)
        lifetime = sum(reserve(a["cost"]) for a in attempts)
        active = sum(
            reserve(a["cost"])
            for a in attempts
            if a["client_order_id"] in active_client_ids
        )
        local_date = now.astimezone(LOCAL_DAY).date()
        daily = sum(
            reserve(a["cost"])
            for a in attempts
            if datetime.fromisoformat(a["utc"]).astimezone(LOCAL_DAY).date()
            == local_date
        )
    except (ValueError, TypeError, KeyError) as error:
        raise TradingError("Invalid shared risk input") from error
    return {
        "shared_lifetime": lifetime + proposed <= LIMITS["lifetime"] + 1e-9,
        "shared_daily": daily + proposed <= LIMITS["daily"] + 1e-9,
        "shared_active": active + proposed <= LIMITS["active"] + 1e-9,
    }


def account_realized_pnl(settlements, owned_tickers, now):
    """Settled P&L across both bots' markets. Fails closed on bad records.

    Only exchange settlements of markets in either bot's journal count; a
    duplicate page cannot double a loss, and an incomplete, undated or
    future-dated record halts new orders instead of being skipped.
    """
    from live.nfl_policy import settlement_accounting

    if not isinstance(settlements, list):
        raise TradingError("Unverified settlement ledger: HALT")
    today = now.astimezone(LOCAL_DAY).date()
    seen = {}
    daily = cumulative = 0.0
    for item in settlements:
        if not isinstance(item, dict):
            raise TradingError("Malformed settlement: HALT")
        ticker = item.get("market_ticker") or item.get("ticker")
        if ticker not in owned_tickers:
            continue
        accounted = settlement_accounting(item)
        amount = accounted.get("net_profit_dollars")
        try:
            when = datetime.fromisoformat(
                str(item["settled_time"]).replace("Z", "+00:00")
            )
        except (ValueError, TypeError, KeyError) as error:
            raise TradingError("Undated settlement: HALT") from error
        if (
            not accounted["accounting_complete"]
            or amount is None
            or not math.isfinite(float(amount))
            or when.tzinfo is None
            or (when - now).total_seconds() > 300
        ):
            raise TradingError("Incomplete or future settlement: HALT")
        key = (str(ticker), when.isoformat())
        if key in seen:
            if seen[key] != accounted:
                raise TradingError("Conflicting settlement copies: HALT")
            continue
        seen[key] = accounted
        cumulative += float(amount)
        if when.astimezone(LOCAL_DAY).date() == today:
            daily += float(amount)
    return {
        "daily_realized_pnl_dollars": round(daily, 4),
        "cumulative_realized_pnl_dollars": round(cumulative, 4),
        "settlement_records": len(seen),
        "loss_stop": (
            daily <= -ACCOUNT_LOSS_STOPS["daily"] + 1e-9
            or cumulative <= -ACCOUNT_LOSS_STOPS["cumulative"] + 1e-9
        ),
    }


def _account_pnl_or_unavailable(settlements, owned_tickers, now):
    """Never let a bad settlement record block the bots' safety cancels.

    The workers read shared state at the start of a pass, before they
    cancel unsafe resting orders. A malformed record is kept as a marker
    here and halts new orders only at the loss-stop check, after cancels.
    """
    try:
        return account_realized_pnl(settlements, owned_tickers, now)
    except TradingError as error:
        return {"unavailable": str(error)}


def account_loss_stop(context):
    """True when the whole-account realized-loss stop blocks new orders.

    Raises (no new orders) when the account P&L could not be verified.
    """
    if context is None:
        return False
    pnl = context.get("account_pnl")
    if isinstance(pnl, dict) and pnl.get("unavailable"):
        raise TradingError(f"Shared account P&L unverifiable ({pnl['unavailable']})")
    if not isinstance(pnl, dict) or "loss_stop" not in pnl:
        raise TradingError("Shared account P&L unavailable: HALT")
    return bool(pnl["loss_stop"])


def dual_mode(env):
    """Opt-in requires both an env setting and an owner-created root marker."""
    requested = env.get("SMM_DUAL_MARKET", "") == "YES"
    if env.get("SMM_DUAL_MARKET", "") not in ("", "NO", "YES"):
        raise TradingError("Invalid shared-account configuration")
    marker = Path("/etc/market-maker-shared-account.enabled")
    if requested and not marker.exists():
        raise TradingError("Owner has not enabled shared-account mode")
    return requested


def state_for(client, sport, now):
    """Read both journals and the entire exchange under the shared process lock.

    All known orders and held positions must belong to exactly one journal.
    Release an expired unfilled order from active capacity only through the
    legacy verified-expiry function, using signed fills and account holdings.
    Lifetime and daily submission charges are never recycled.
    """
    if sport not in ("nfl", "nba"):
        raise TradingError("Unknown shared account cohort")
    from live import prod_nba_auto, prod_nfl_auto

    modules = {"nfl": prod_nfl_auto, "nba": prod_nba_auto}
    events = {name: journal_events(name) for name in modules}
    owner = ownership(events)
    resting = client.orders("resting")
    positions = client.positions()
    classified = classify(resting, positions, owner)
    attempts = owner["attempts"]
    settlements = client.settlements() if attempts else []
    if not isinstance(settlements, list):
        raise TradingError("Missing signed settlement history")
    start = (
        min(int(datetime.fromisoformat(a["utc"]).timestamp()) for a in attempts) - 60
        if attempts
        else int(now.timestamp()) - 60
    )
    fills = client.fills(min_ts=start) if attempts else []
    if not isinstance(fills, list):
        raise TradingError("Missing signed fill history")
    for fill in fills:
        ticker = fill.get("ticker") or fill.get("market_ticker")
        if (
            ticker in owner["tickers"]
            and str(fill.get("order_id")) not in owner["orders"]
        ):
            raise TradingError("Unowned fill on pilot market: HALT")
    settled = {
        r.get("market_ticker") or r.get("ticker")
        for r in settlements
        if isinstance(r, dict)
    }
    snapshots = {}
    active_ids = set()
    for name, module in modules.items():
        own = [a for a in attempts if a["_cohort"] == name]
        accepted = {
            e["client_order_id"]: e
            for e in events[name]
            if e.get("event") == "accepted"
        }
        own_tickers = {a["ticker"] for a in own}
        state = {
            "resting": classified[name]["resting"],
            "held": classified[name]["held"],
            "settled": settled & own_tickers,
            "settlements": settlements,
            "active": [
                a
                for a in own
                if a["ticker"] not in settled
                and a["client_order_id"] not in owner["rejected_by_sport"][name]
            ],
            "rejected_client_ids": owner["rejected_by_sport"][name],
        }
        if name == "nba":
            active, _ = module.reconcile_expired_unfilled(
                own, accepted, state, fills, now, events=events[name]
            )
        else:
            active, _ = module.reconcile_expired_unfilled(
                own, accepted, state, fills, now
            )
        state["active"] = active
        snapshots[name] = state
        active_ids.update(a["client_order_id"] for a in active)
    return snapshots[sport], {
        "ownership": owner,
        "active_client_ids": active_ids,
        "account_pnl": _account_pnl_or_unavailable(
            settlements, set(owner["tickers"]), now
        ),
    }


def fits(context, cost, now):
    return all(
        room(context["ownership"], context["active_client_ids"], cost, now).values()
    )
