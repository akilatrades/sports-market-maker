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
from live import external_spread_closes as external_closes

ROOT = Path("/home/trader")
# Cross-sport caps: NBA v6 ($5,000 lifetime, $150 daily, $150 active) plus NFL's own
# unchanged limits ($50 lifetime, $30 daily, $15 active). Lifetime was $2,050
# before 2026-10-23 (RESEARCH_LOG.md, "NBA rules v6").
LIMITS = {"lifetime": 5050.0, "daily": 180.0, "active": 165.0}
LOCAL_DAY = ZoneInfo("America/New_York")
# Realized-loss stops for the WHOLE account (NBA + NFL + spread maker settled
# markets together; the spread maker joined on 2026-10-22, sizes unchanged).
# Each bot's own limits still apply on top of these. The total stop was -$60
# before 2026-10-23 (RESEARCH_LOG.md, "NBA rules v6").
ACCOUNT_LOSS_STOPS = {"daily": 20.0, "cumulative": 100.0}
REQUIRED_COHORTS = ("nfl", "nba")
SPREAD = "spread"
CAPPED_COHORTS = ("nfl", "nba")  # cohorts counted against LIMITS
SPREAD_REJECTION_EVIDENCE = "http_4xx_and_signed_get_absent"
# Owner-run reconciliation (live.prod_spread_auto --reconcile): no order with
# the client id in any status, at least 10 minutes after the intent.
SPREAD_ABSENT_EVIDENCE = "owner_signed_get_absent_all_statuses"
SPREAD_ABSENT_MIN_AGE_SECONDS = 600


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
    """Spread-maker placements proven never to have reached the book.

    ``rejected_4xx``: the exchange refused the request with an HTTP 4xx and
    a signed read found no order with that client id in any status (written
    by the worker at once). ``reconciled_absent``: the owner's signed
    reconciliation found no such order at least 10 minutes later, after an
    ambiguous outcome. Never used for NBA or NFL.
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
        kind = event.get("event")
        if kind not in ("rejected_4xx", "reconciled_absent"):
            continue
        cid = event.get("client_order_id")
        if not cid or cid not in intents or cid in accepted or cid in found:
            raise TradingError("Invalid or duplicate spread rejection: HALT")
        if kind == "rejected_4xx":
            status = event.get("http_status")
            valid = (
                cid not in unknown
                and type(status) is int
                and 400 <= status <= 499
                and event.get("evidence") == SPREAD_REJECTION_EVIDENCE
            )
        else:
            age = event.get("intent_age_seconds")
            valid = (
                event.get("evidence") == SPREAD_ABSENT_EVIDENCE
                and type(age) is int
                and age >= SPREAD_ABSENT_MIN_AGE_SECONDS
            )
        if not valid or not event.get("utc"):
            raise TradingError("Invalid or duplicate spread rejection: HALT")
        found.add(cid)
    return found


def _when(value, label):
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as error:
        raise TradingError(f"Undated spread {label}: HALT") from error
    if when.tzinfo is None:
        raise TradingError(f"Undated spread {label}: HALT")
    return when


def _amount(value, label, positive=False):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise TradingError(f"Unreadable spread {label}: HALT") from error
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        raise TradingError(f"Unreadable spread {label}: HALT")
    return number


def spread_ledger(events, fills, settlements, now):
    """Realized P&L of the spread maker from its own fills, and what it holds.

    Kalshi nets YES against NO in a market, so a YES+NO pair closes the
    moment its second leg fills and never reaches a settlement record. The
    bot's P&L therefore comes from its own fills, matched first in, first
    out per market: a closed pair realizes $1 minus both prices when the
    second leg fills; contracts still held at settlement realize their
    payout minus their price then. Fees count when charged. The fill's side
    and price must agree with the journaled order; anything that cannot be
    accounted for halts instead of being skipped.

    The bot's journal keeps a copy of every fill and settlement it has seen,
    merged here with the exchange's lists (duplicates removed), so a fill or
    settlement that ages out of the exchange's listing is never forgotten.
    """
    from live.nfl_policy import settlement_accounting

    intents = {
        e.get("client_order_id"): e for e in events if e.get("event") == "intent"
    }
    orders = {
        str(e.get("order_id")): intents[e.get("client_order_id")]
        for e in events
        if e.get("event") == "accepted" and e.get("client_order_id") in intents
    }
    tickers = {i.get("ticker") for i in intents.values()}
    journal_fills = [
        {**e, "created_time": e.get("utc")} for e in events if e.get("event") == "fill"
    ]
    journal_settlements = [
        {
            "market_ticker": e.get("ticker"),
            "settled_time": e.get("utc"),
            "market_result": e.get("market_result"),
            "revenue_dollars": e.get("revenue_dollars"),
        }
        for e in events
        if e.get("event") == "settlement"
    ]
    external = external_closes.approved(events, fills, now)
    rows = {}
    for fill in [*journal_fills, *fills]:
        intent = orders.get(str(fill.get("order_id")))
        if intent is None:
            continue
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid:
            raise TradingError("Spread fill without identity: HALT")
        side = intent.get("side")
        outcome = fill.get("outcome_side")
        book = fill.get("book_side")
        if (outcome is not None and outcome != side) or (
            book is not None and book != ("bid" if side == "yes" else "ask")
        ):
            raise TradingError("Spread fill direction disagrees with journal: HALT")
        expected = int(intent.get("price_cents")) / 100
        raw = fill.get(f"{side}_price_dollars")
        price = expected if raw is None else _amount(raw, "fill price")
        if abs(price - expected) > 0.005:
            raise TradingError("Spread fill price disagrees with journal: HALT")
        row = {
            "when": _when(fill.get("created_time"), "fill"),
            "fid": str(fid),
            "ticker": intent.get("ticker"),
            "side": side,
            "price": expected,
            "count": _amount(
                fill.get("count_fp")
                if fill.get("count_fp") is not None
                else fill.get("count"),
                "fill",
                True,
            ),
            "fee": _amount(fill.get("fee_cost") or 0, "fee"),
        }
        if row["fid"] in rows and rows[row["fid"]] != row:
            raise TradingError("Conflicting spread fill copies: HALT")
        rows[row["fid"]] = row
    for fid, row in external.items():
        if fid in rows:
            raise TradingError("External fill overlaps bot fill identity: HALT")
        rows[fid] = {
            "when": _when(row["when"], "external close"),
            "fid": fid,
            "ticker": row["ticker"],
            "side": row["side"],
            "price": float(row["price"]),
            "count": float(row["count"]),
            "fee": float(row["fee"]),
            "external_close": True,
        }
    settlement_times = {}
    for item in [*journal_settlements, *settlements]:
        ticker = item.get("market_ticker") or item.get("ticker")
        if ticker in tickers:
            at = _when(item.get("settled_time"), "settlement")
            settlement_times[ticker] = min(at, settlement_times.get(ticker, at))
    lots, realized = {}, []
    for row in sorted(rows.values(), key=lambda r: (r["when"], r["fid"])):
        queue = lots.setdefault(row["ticker"], [])
        left = row["count"]
        if row.get("external_close"):
            available = sum(q for side, _, q in queue if side != row["side"])
            if available + 1e-8 < left or (
                row["ticker"] in settlement_times
                and row["when"] >= settlement_times[row["ticker"]]
            ):
                raise TradingError(
                    "External close would open or exceed held risk: HALT"
                )
        if row["fee"]:
            realized.append((row["when"], -row["fee"]))
        while left > 1e-9 and queue and queue[0][0] != row["side"]:
            side, price, count = queue[0]
            matched = min(left, count)
            realized.append((row["when"], matched * (1 - row["price"] - price)))
            left -= matched
            if count - matched > 1e-9:
                queue[0] = (side, price, count - matched)
            else:
                queue.pop(0)
        if left > 1e-9:
            queue.append((row["side"], row["price"], left))
    seen, settled = {}, set()
    for item in [*journal_settlements, *settlements]:
        if not isinstance(item, dict):
            raise TradingError("Malformed settlement: HALT")
        ticker = item.get("market_ticker") or item.get("ticker")
        if ticker not in tickers:
            continue
        when = _when(item.get("settled_time"), "settlement")
        if (when - now).total_seconds() > 300:
            raise TradingError("Future spread settlement: HALT")
        result = str(item.get("market_result") or "").lower()
        revenue = settlement_accounting(item)["revenue_dollars"]
        key = (ticker, when.isoformat())
        if key in seen:
            if seen[key] != (result, revenue):
                raise TradingError("Conflicting settlement copies: HALT")
            continue
        seen[key] = (result, revenue)
        held = lots.pop(ticker, [])
        cost = sum(price * count for _, price, count in held)
        if result in ("yes", "no"):
            payout = sum(count for side, _, count in held if side == result)
            if revenue is not None and abs(revenue - payout) > 0.005:
                raise TradingError("Spread settlement disagrees with its fills: HALT")
        elif revenue is not None:
            payout = revenue
        else:
            raise TradingError("Unaccountable spread settlement: HALT")
        realized.append((when, payout - cost))
        settled.add(ticker)
    today = now.astimezone(LOCAL_DAY).date()
    by_day = {}
    for when, amount in realized:
        day = when.astimezone(LOCAL_DAY).date().isoformat()
        by_day[day] = by_day.get(day, 0.0) + amount
    return {
        "daily": round(by_day.get(today.isoformat(), 0.0), 4),
        "cumulative": round(sum(a for _, a in realized), 4),
        "by_day": {day: round(v, 4) for day, v in sorted(by_day.items())},
        "open": {t: q for t, q in lots.items() if q},
        "settled": settled,
        "fills": len(rows),
    }


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
        resolved = set(rejected_by_sport[sport])
        if sport == SPREAD:
            # A spread order with an ambiguous outcome is settled by the
            # owner's signed reconciliation: found (accepted) or absent.
            resolved |= {e.get("client_order_id") for e in accepted}
        if any(
            e.get("event") == "unknown_outcome"
            and e.get("client_order_id") not in resolved
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
            if cid in rejected and sport != SPREAD:
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


def _account_pnl_or_unavailable(settlements, owned_tickers, now, spread=None):
    """Never let a bad settlement record block the bots' safety cancels.

    The workers read shared state at the start of a pass, before they
    cancel unsafe resting orders. A malformed record is kept as a marker
    here and halts new orders only at the loss-stop check, after cancels.

    NBA and NFL markets count from settlement records; the spread maker's
    markets count from its fill ledger (``spread``: the ledger, or a
    ``{"unavailable": ...}`` marker), because its closed YES+NO pairs never
    reach a settlement record.
    """
    if isinstance(spread, dict) and spread.get("unavailable"):
        return {"unavailable": spread["unavailable"]}
    try:
        pnl = account_realized_pnl(settlements, owned_tickers, now)
    except TradingError as error:
        return {"unavailable": str(error)}
    if spread is not None:
        daily = pnl["daily_realized_pnl_dollars"] + spread["daily"]
        cumulative = pnl["cumulative_realized_pnl_dollars"] + spread["cumulative"]
        pnl.update(
            {
                "daily_realized_pnl_dollars": round(daily, 4),
                "cumulative_realized_pnl_dollars": round(cumulative, 4),
                "spread_daily_realized_pnl_dollars": spread["daily"],
                "spread_cumulative_realized_pnl_dollars": spread["cumulative"],
                "loss_stop": (
                    daily <= -ACCOUNT_LOSS_STOPS["daily"] + 1e-9
                    or cumulative <= -ACCOUNT_LOSS_STOPS["cumulative"] + 1e-9
                ),
            }
        )
    return pnl


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
    approvals = external_closes.approved(events.get(SPREAD) or [], fills, now)
    for fill in fills:
        ticker = fill.get("ticker") or fill.get("market_ticker")
        if (
            ticker in owner["tickers"]
            and str(fill.get("order_id")) not in owner["orders"]
            and not (
                owner["tickers"].get(ticker) == SPREAD
                and external_closes.recognized(fill, approvals)
            )
        ):
            raise TradingError("Unowned fill on pilot market: HALT")
    if approvals:
        external_ledger = spread_ledger(events[SPREAD], fills, settlements, now)
        expected_positions = {
            t: sum(q if side == "yes" else -q for side, _, q in lots)
            for t, lots in external_ledger["open"].items()
        }
        actual_positions = classified[SPREAD]["positions"]
        if any(
            abs(expected_positions.get(t, 0) - actual_positions.get(t, 0)) > 1e-6
            for t in set(expected_positions) | set(actual_positions)
        ):
            raise TradingError(
                "External-close ledger disagrees with signed positions: HALT"
            )
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
    ledger = None
    spread_tickers = set()
    if SPREAD in owner["cohorts"]:
        own = [a for a in attempts if a["_cohort"] == SPREAD]
        spread_tickers = {a["ticker"] for a in own}
        try:
            ledger = spread_ledger(events[SPREAD], fills, settlements, now)
        except TradingError as error:
            ledger = {"unavailable": str(error)}
        snapshots[SPREAD] = {
            "resting": classified[SPREAD]["resting"],
            "held": classified[SPREAD]["held"],
            "positions": classified[SPREAD]["positions"],
            "settled": settled & spread_tickers,
            "settlements": settlements,
            "attempts": own,
            "fills": fills,
            "ledger": ledger,
        }
    return snapshots[sport], {
        "ownership": owner,
        "active_client_ids": active_ids,
        "account_pnl": _account_pnl_or_unavailable(
            settlements, set(owner["tickers"]) - spread_tickers, now, ledger
        ),
    }


def fits(context, cost, now):
    return all(
        room(context["ownership"], context["active_client_ids"], cost, now).values()
    )
