"""Read-only audit of funded Kalshi orders that did not receive fills.

This is NOT a counterfactual execution engine. Signed account orders/fills
establish actual status; public trade prints describe potential contra flow,
not a fill that was guaranteed to reach our position in the queue.

Never upload these rows, client IDs, tickers, or trade data to public Pages.
"""

import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime

from kalshi.trading import TradingError

CLOSED_STATUSES = {"canceled", "cancelled", "executed", "expired"}
OPEN_STATUSES = {"resting", "pending"}


def amount(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def instant(value):
    if value is None:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts.astimezone(UTC) if ts.tzinfo is not None else None


def filled_count(order):
    """Kalshi has used several quantity field names. Missing is unknown."""
    for key in ("fill_count_fp", "filled_count_fp", "fill_count", "filled_count"):
        if order.get(key) is not None:
            return amount(order[key])
    return None


def contra_volume(prints, no_price, started, ended):
    """Count YES-taker prints at/through our NO maker price, not missed fills.

    Buy NO is a passive sell YES at (1 - no_price). A YES aggressor can
    trade into that price if our resting order actually has queue priority.
    """
    if started is None or ended is None or no_price is None:
        return None
    if ended < started or not 0 < no_price < 1:
        return None
    total = 0.0
    for row in prints:
        if not isinstance(row, dict):
            return None
        at = instant(row.get("created_time"))
        yes = amount(row.get("yes_price_dollars", row.get("yes_price")))
        qty = amount(row.get("count_fp", row.get("count")))
        side = row.get("taker_outcome_side") or row.get("taker_side")
        if at is None or yes is None or qty is None or side is None:
            return None  # Cannot assert zero when public prints are incomplete.
        if row.get("is_block_trade"):
            continue  # Block prints are not resting queue flow.
        if started <= at <= ended and str(side).lower() == "yes":
            if yes + 1e-9 >= 1 - no_price:
                total += qty
    return round(total, 4)


# Bound the optional public market-print reads. These are observation-only
# and never authorize, cancel, or modify any production order.
_MAX_PRINT_ORDERS = 6
_PRINT_CACHE = {}


def trade_through_samples(client, events, exchange_orders, now):
    """Get bounded recent public trades during *known* resting lifetimes.

    Closed orders without an exchange-reported stop timestamp have unknown
    opportunity windows and are intentionally excluded. A cache prevents a
    successful immutable window from being queried every account refresh.
    All errors result in missing coverage, never a false zero.
    """
    active = {
        str(order["order_id"]): order
        for order in exchange_orders
        if isinstance(order, dict) and order.get("order_id")
    }
    intents = {
        e.get("client_order_id"): e for e in events if e.get("event") == "intent"
    }
    matched = []
    for e in events:
        if e.get("event") != "accepted":
            continue
        intent = intents.get(e.get("client_order_id"))
        if not intent:
            continue
        oid = str(e.get("order_id"))
        order = active.get(oid)
        start = instant(e.get("utc")) or instant(intent.get("utc"))
        if not order or start is None or (now - start).total_seconds() > 3 * 86400:
            continue
        status = str(order.get("status", "")).lower()
        expiry = instant(intent.get("tip_utc"))
        if intent.get("expiration_ts") is not None:
            try:
                expiry = datetime.fromtimestamp(int(intent["expiration_ts"]), UTC)
            except (TypeError, ValueError, OSError, OverflowError):
                continue
        if status == "resting":
            end = min(now, expiry) if expiry is not None else now
        elif status in CLOSED_STATUSES:
            end = None
            for key in ("canceled_time", "last_update_time", "updated_time"):
                end = instant(order.get(key))
                if end is not None:
                    break
            if end is not None and expiry is not None:
                end = min(end, expiry)
        else:
            continue
        if end is None or end <= start:
            continue
        ticker = intent.get("ticker")
        if not ticker or not isinstance(ticker, str):
            continue
        matched.append(
            (start, oid, ticker, int(start.timestamp()), int(end.timestamp()), end)
        )
    matched.sort(reverse=True)
    results = {}
    for _start, oid, ticker, first, last, end in matched[:_MAX_PRINT_ORDERS]:
        key = (ticker, first, last)
        if key in _PRINT_CACHE:
            rows = _PRINT_CACHE[key]
        else:
            rows, cursor, seen = [], "", set()
            try:
                for _ in range(6):
                    params = {
                        "ticker": ticker,
                        "min_ts": first,
                        "max_ts": last,
                        "limit": 200,
                    }
                    if cursor:
                        params["cursor"] = cursor
                    page = client._request("GET", "/markets/trades", params)
                    batch = page.get("trades")
                    if not isinstance(batch, list):
                        raise TradingError("Missing public trade prints")
                    rows.extend(batch)
                    cursor = page.get("cursor") or ""
                    if not cursor:
                        break
                    if cursor in seen:
                        raise TradingError("Duplicate public trade cursor")
                    seen.add(cursor)
                else:
                    raise TradingError("Public trade history truncated")
            except Exception:
                continue
            if len(_PRINT_CACHE) > 120:
                _PRINT_CACHE.clear()
            _PRINT_CACHE[key] = rows
        results[oid] = {"trades": rows, "end_utc": end.isoformat()}
    return results


_CLOSED_ORDER_CACHE = {}


def backfill_owned_orders(client, cohorts, exchange_orders, *, limit=30):
    """Read older owned order IDs missing from the general order list.

    Kalshi may paginate or age out records from the aggregate listing; a
    missing result is unknown, never proof of no fill. Only GET is allowed.
    Cache terminal states to avoid repeated account requests each minute.
    """
    found = {str(row["order_id"]): row for row in exchange_orders
             if isinstance(row, dict) and row.get("order_id")}
    missing = []
    for events in cohorts.values():
        if events is None:
            continue
        for event in reversed(events):
            if event.get("event") != "accepted":
                continue
            oid = str(event.get("order_id", ""))
            if oid in found:
                continue
            if oid in _CLOSED_ORDER_CACHE:
                found[oid] = _CLOSED_ORDER_CACHE[oid]
            elif oid and re.fullmatch(r"[A-Za-z0-9-]{1,128}", oid):
                missing.append(oid)
    for oid in list(dict.fromkeys(missing))[:limit]:
        try:
            page = client._request("GET", f"/portfolio/orders/{oid}")
            record = page.get("order")
            if not isinstance(record, dict) or str(record.get("order_id")) != oid:
                continue
            found[oid] = record
            if str(record.get("status", "")).lower() in CLOSED_STATUSES:
                if len(_CLOSED_ORDER_CACHE) > 512:
                    _CLOSED_ORDER_CACHE.clear()
                _CLOSED_ORDER_CACHE[oid] = record
        except Exception:
            continue  # Authenticated missing order still remains uncertain.
    return list(found.values())


def audit_cohort(events, exchange_orders, fills, *, sport, now, prints_by_order=None):
    """Count actual accepted orders, partials, no-fills, and unknowns.

    A missing exchange order or unsigned/incomplete fill evidence is never
    labelled as a confirmed unfilled trade. Order status is exchange-sourced.
    Public contra prints are optional and are explicitly not our own fills.
    """
    if not isinstance(events, list) or not isinstance(exchange_orders, list):
        raise TradingError("Incomplete order audit sources")
    if not isinstance(fills, list):
        raise TradingError("Incomplete signed fill history")
    if now.tzinfo is None:
        raise TradingError("Audit requires UTC time")
    if sport not in {"nfl", "nba"}:
        raise TradingError("Invalid audit cohort")

    intents = {}
    accepted = {}
    queue = defaultdict(list)
    for event in events:
        kind = event.get("event")
        if kind == "intent":
            cid = event.get("client_order_id")
            if not cid or cid in intents:
                raise TradingError("Ambiguous production order intent")
            intents[cid] = event
        elif kind == "accepted":
            cid, oid = event.get("client_order_id"), event.get("order_id")
            if cid not in intents or not oid or str(oid) in accepted:
                raise TradingError("Unreconciled production acceptance")
            accepted[str(oid)] = intents[cid]
        elif kind == "queue" and event.get("order_id"):
            queue[str(event["order_id"])].append(event)
    orders = {
        str(order["order_id"]): order
        for order in exchange_orders
        if isinstance(order, dict) and order.get("order_id")
    }
    found = defaultdict(dict)
    for fill in fills:
        if not isinstance(fill, dict):
            raise TradingError("Invalid exchange fill")
        oid = str(fill.get("order_id", ""))
        if oid not in accepted:
            continue
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid:
            raise TradingError("Signed fill has no fill ID")
        found[oid][str(fid)] = fill
    rows = []
    for oid, intent in accepted.items():
        exchange = orders.get(oid)
        qty = amount(intent.get("count"))
        price = amount(intent.get("price_cents"))
        opened = instant(
            next(
                (
                    e.get("utc")
                    for e in events
                    if e.get("event") == "accepted" and str(e.get("order_id")) == oid
                ),
                None,
            )
        ) or instant(intent.get("utc"))
        expiry = (
            instant(intent.get("expiration_ts"))
            if isinstance(intent.get("expiration_ts"), str)
            else None
        )
        if expiry is None and intent.get("expiration_ts") is not None:
            try:
                expiry = datetime.fromtimestamp(int(intent["expiration_ts"]), UTC)
            except (ValueError, OverflowError, TypeError):
                pass
        if expiry is None:
            expiry = instant(intent.get("tip_utc"))
        chunks = list(found.get(oid, {}).values())
        measured = [amount(f.get("count_fp", f.get("count"))) for f in chunks]
        actual = (
            round(sum(measured), 4) if all(v is not None for v in measured) else None
        )
        # Historical fills are not just counts: retain their price, fee,
        # maker/taker classification and time. Unknown is never a fake zero.
        prices = [amount(f.get("no_price_dollars")) for f in chunks]
        fees = [amount(f.get("fee_cost")) for f in chunks]
        fee_total = (
            round(sum(fees), 6)
            if chunks and all(v is not None for v in fees)
            else None
        )
        vwap = (
            round(sum(n * p for n, p in zip(measured, prices, strict=True)) / actual, 6)
            if actual and all(n is not None for n in measured)
            and all(p is not None for p in prices)
            else None
        )
        maker = (
            round(sum(n for n, f in zip(measured, chunks, strict=True)
                      if f["is_taker"] is False), 4)
            if chunks and all(n is not None for n in measured)
            and all("is_taker" in f and isinstance(f["is_taker"], bool)
                    for f in chunks)
            else None
        )
        filled_times = [instant(f.get("created_time")) for f in chunks]
        observed_times = [t for t in filled_times if t is not None]
        status = str(exchange.get("status", "")).lower() if exchange else "not_returned"
        exchange_filled = filled_count(exchange) if exchange else None
        if (
            exchange_filled is not None
            and actual is not None
            and abs(exchange_filled - actual) > 1e-5
        ):
            state = "unreconciled_fill_count"
        elif qty is None or qty <= 0 or actual is None or actual > qty + 1e-5:
            state = "unreconciled_fill_count"
        elif exchange is None:
            state = "exchange_order_unavailable"
        elif status not in OPEN_STATUSES | CLOSED_STATUSES:
            state = "exchange_status_unknown"
        elif status == "pending":
            state = "pending"
        elif actual >= qty - 1e-5:
            state = "fully_filled"
        elif actual > 0:
            state = (
                "partially_filled_resting"
                if status == "resting"
                else "partially_filled_closed"
            )
        elif status == "resting":
            state = "resting_no_fill"
        elif exchange_filled == 0:
            state = "confirmed_unfilled"
        else:
            # An empty recent GET /fills is insufficient proof that an
            # older closed order never traded; await explicit zero count.
            state = "unconfirmed_unfilled"

        observations = queue.get(oid, [])
        valid_ahead = [amount(q.get("ahead")) for q in observations]
        valid_ahead = [v for v in valid_ahead if v is not None]
        flow = None
        if prints_by_order is not None and oid in prints_by_order:
            sample = prints_by_order[oid]
            trade_rows = sample.get("trades") if isinstance(sample, dict) else sample
            end = instant(sample.get("end_utc")) if isinstance(sample, dict) else None
            if trade_rows is not None:
                flow = contra_volume(
                    trade_rows,
                    price / 100 if price is not None else None,
                    opened,
                    end or (min(now, expiry) if expiry is not None else now),
                )
        rows.append(
            {
                "cohort": sport,
                "ticker": intent.get("ticker"),
                "player": intent.get("player") or intent.get("ticker"),
                "stat": intent.get("stat"),
                "submitted_utc": opened.isoformat() if opened else None,
                "expiration_utc": expiry.isoformat() if expiry else None,
                "exchange_status": status,
                "state": state,
                "ordered_contracts": qty,
                "filled_contracts": actual,
                "fill_records": len(chunks),
                "vwap_no_price_dollars": vwap,
                "fill_fees_dollars": fee_total,
                "maker_filled_contracts": maker,
                "first_fill_utc": min(observed_times).isoformat() if observed_times else None,
                "last_fill_utc": max(observed_times).isoformat() if observed_times else None,
                "price_dollars": price / 100 if price is not None else None,
                "queue_ahead_initial": valid_ahead[0] if valid_ahead else None,
                "queue_ahead_latest": valid_ahead[-1] if valid_ahead else None,
                "public_contra_contracts": flow,
                "public_flow_is_not_guaranteed_fill": True,
            }
        )
    rows.sort(key=lambda r: r["submitted_utc"] or "", reverse=True)
    counts = Counter(row["state"] for row in rows)
    return {
        "status": "verified_snapshot",
        "accepted_orders": len(rows),
        "confirmed_unfilled": counts["confirmed_unfilled"],
        "unconfirmed_unfilled": counts["unconfirmed_unfilled"],
        "resting_no_fill": counts["resting_no_fill"],
        "partially_filled": counts["partially_filled_resting"]
        + counts["partially_filled_closed"],
        "fully_filled": counts["fully_filled"],
        "fill_records": sum(r["fill_records"] for r in rows),
        "filled_contracts": (
            round(sum(r["filled_contracts"] for r in rows), 4)
            if all(r["filled_contracts"] is not None for r in rows)
            else None
        ),
        "unknown_or_unreconciled": sum(
            v
            for k, v in counts.items()
            if k
            in {
                "unreconciled_fill_count",
                "exchange_order_unavailable",
                "exchange_status_unknown",
                "pending",
                "unconfirmed_unfilled",
            }
        ),
        "orders": rows,
        "note": "Actual outcomes from signed Kalshi orders/fills. Public YES-taker volume is possible contra flow, not a proven missed fill.",
    }
