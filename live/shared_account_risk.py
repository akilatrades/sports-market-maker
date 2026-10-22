"""Cross-bot ownership and budget checks. No exchange writes.

Import from the production workers only while their existing account_lock
is held. Absent, ambiguous or unowned account data must stop new entries.

Cohorts: NBA and NFL (always), and the spread maker (``spread``) once its
journal exists on the server (RESEARCH_LOG.md, 2026-10-22, spread maker
pilot). The spread maker buys YES and NO, so its positions may have either
sign; NBA and NFL positions must still be NO only. The shared lifetime,
daily and active caps (``LIMITS``) are computed from NBA and NFL orders
only; the spread maker has its own caps (live/spread_policy.py). The
account-wide realized-loss stops count all three bots' settled markets.
"""

from datetime import datetime
from pathlib import Path
import json
import math
from zoneinfo import ZoneInfo

from kalshi.trading import TradingError
from live.reconciled_attempts import rejected_client_ids

ROOT = Path("/home/trader")
# Cross-sport caps: NBA v5 ($2,000 lifetime, $150 daily, $150 active) plus NFL's own
# unchanged limits ($50 lifetime, $30 daily, $15 active).
LIMITS = {"lifetime": 2050.0, "daily": 180.0, "active": 165.0}
LOCAL_DAY = ZoneInfo("America/New_York")
# Realized-loss stops for the WHOLE account (NBA + NFL + spread maker settled
# markets together; the spread maker joined on 2026-10-22, sizes unchanged).
# Each bot's own limits still apply on top of these.
ACCOUNT_LOSS_STOPS = {"daily": 20.0, "cumulative": 60.0}
REQUIRED_COHORTS = ("nfl", "nba")
SPREAD = "spread"
CAPPED_COHORTS = ("nfl", "nba")  # cohorts counted against LIMITS
SPREAD_REJECTION_EVIDENCE = "http_4xx_and_signed_get_absent"


def journal_events(sport):
    """A cohort's journal events; ``None`` only for an undeployed spread maker."""
    if sport not in (*REQUIRED_COHORTS, SPREAD):
        raise TradingError("Invalid production cohort")
    path = ROOT / f"prod-{sport}-auto" / "journal.jsonl"
    if not path.exists():
        if sport == SPREAD:
            return None  # not deployed: no spread orders can be recognised
        raise TradingError("Missing other-cohort production journal")
    raw = path.read_text()
    if raw and not raw.endswith("\n"):
        raise TradingError("Incomplete production journal")
    try:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (ValueError, TypeError) as error:
        raise TradingError("Invalid production journal") from error


def spread_rejected_ids(events):
    """Spread-maker placements the exchange refused with an HTTP 4xx.

    Recorded by the spread worker only after a signed read of the market's
    resting orders found no order with that client id. Never used for NBA
    or NFL, whose rejections still need the owner's reconciliation tool.
    """
    intents = {e.get("client_order_id") for e in events if e.get("event") == "intent"}
    accepted = {
        e.get("client_order_id") for e in events if e.get("event") == "accepted"
    }
    unknown = {
        e.get("client_order_id") for e in events if e.get("event") == "unknown_outcome"
    }
    found = set()
    for event in events:
        if event.get("event") != "rejected_4xx":
            continue
        cid = event.get("client_order_id")
        status = event.get("http_status")
        if (
            not cid
            or cid not in intents
            or cid in accepted
            or cid in unknown
            or cid in found
            or type(status) is not int
            or not 400 <= status <= 499
            or event.get("evidence") != SPREAD_REJECTION_EVIDENCE
            or not event.get("utc")
        ):
            raise TradingError("Invalid or duplicate spread rejection: HALT")
        found.add(cid)
    return found


def cohorts_of(events_by_sport):
    present = [s for s in REQUIRED_COHORTS]
    if events_by_sport.get(SPREAD) is not None:
        present.append(SPREAD)
    return tuple(present)


def ownership(events_by_sport):
    orders, tickers, attempts = {}, {}, []
    client_ids = set()
    rejected_tickers = set()
    rejected_by_sport = {}
    for sport in cohorts_of(events_by_sport):
        events = events_by_sport[sport]
        rejected = rejected_client_ids(events)
        if sport == SPREAD:
            refused = spread_rejected_ids(events)
            # A refused quote never existed; the market may still hold
            # contracts from earlier fills, so it is not a rejected ticker.
            rejected_by_sport[sport] = rejected | refused
        else:
            refused = set()
            rejected_by_sport[sport] = rejected
        intents = [e for e in events if e.get("event") == "intent"]
        accepted = [e for e in events if e.get("event") == "accepted"]
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
            attempts.append({**e, "_cohort": sport, "_refused": cid in refused})
        seen = set()
        for e in accepted:
            cid, oid = e.get("client_order_id"), e.get("order_id")
            if not oid or cid not in by_id or cid in seen or str(oid) in orders:
                raise TradingError("Invalid production acceptance")
            seen.add(cid)
            orders[str(oid)] = sport
        if seen != set(by_id) - rejected_by_sport[sport]:
            raise TradingError("Unreconciled production submission: HALT")
    return {
        "orders": orders,
        "tickers": tickers,
        "attempts": attempts,
        "rejected_tickers": rejected_tickers,
        "rejected_by_sport": rejected_by_sport,
        "cohorts": cohorts_of(events_by_sport),
    }


def classify(resting, positions, owner):
    """Return only cohort-owned open orders and positions; fail on manual risk.

    NBA and NFL may only hold NO (negative) positions. The spread maker may
    hold either side, never more contracts than it ordered in that market.
    """
    if not isinstance(resting, list) or not isinstance(positions, list):
        raise TradingError("Invalid production account snapshot")
    cohorts = owner.get("cohorts", REQUIRED_COHORTS)
    result = {s: {"resting": [], "held": [], "positions": {}} for s in cohorts}
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
        if sport not in result or (qty > 0 and sport != SPREAD):
            raise TradingError("Unowned or wrong-side account position: HALT")
        owned_count = sum(
            float(a["count"])
            for a in owner["attempts"]
            if a["ticker"] == ticker and not a.get("_refused")
        )
        if abs(qty) > owned_count + 1e-8:
            raise TradingError("Held inventory exceeds accepted intent: HALT")
        result[sport]["held"].append(ticker)
        result[sport]["positions"][ticker] = qty
    return result


def room(owner, active_client_ids, cost, now):
    """Global admission requires previously verified active-order identities."""
    if now.tzinfo is None:
        raise TradingError("Current timestamp has no timezone")
    # LIMITS cover NBA and NFL; the spread maker has its own caps.
    attempts = [
        a for a in owner["attempts"] if a.get("_cohort", "nba") in CAPPED_COHORTS
    ]
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
    """Read every cohort's journal and the entire exchange under the shared lock.

    All known orders and held positions must belong to exactly one journal.
    Release an expired unfilled order from active capacity only through the
    legacy verified-expiry function, using signed fills and account holdings.
    Lifetime and daily submission charges are never recycled.
    """
    if sport not in (*REQUIRED_COHORTS, SPREAD):
        raise TradingError("Unknown shared account cohort")
    from live import prod_nba_auto, prod_nfl_auto

    modules = {"nfl": prod_nfl_auto, "nba": prod_nba_auto}
    events = {name: journal_events(name) for name in modules}
    events[SPREAD] = journal_events(SPREAD)
    if sport == SPREAD and events[SPREAD] is None:
        raise TradingError("Missing spread production journal")
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
    if SPREAD in owner["cohorts"]:
        own = [a for a in attempts if a["_cohort"] == SPREAD]
        own_tickers = {a["ticker"] for a in own}
        snapshots[SPREAD] = {
            "resting": classified[SPREAD]["resting"],
            "held": classified[SPREAD]["held"],
            "positions": classified[SPREAD]["positions"],
            "settled": settled & own_tickers,
            "settlements": settlements,
            "attempts": own,
            "fills": fills,
        }
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
