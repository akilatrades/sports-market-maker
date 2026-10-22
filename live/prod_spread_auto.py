"""Spread maker (spread-maker-v1): two-sided quotes one cent inside wide spreads.

Plan: RESEARCH_LOG.md, "2026-10-22: Spread maker pilot, shadow and small
live (plan)". For open markets in the allowed series whose expected
expiration is 4 to 7 hours away and whose spread is 8c or more, quote a YES
bid one cent above the best YES bid and a NO bid one cent above the best NO
bid, one contract each, post-only, expiring after 65 minutes. Hold fills to
settlement; never quote a side already held in that market.

Modes (``--auto`` picks live only when armed, else shadow):
- ``--shadow``: public data only. Writes the quotes it would post to
  STATE/shadow.jsonl and scores them later from Kalshi's public trade prints
  and results. No credentials, no orders.
- ``--live``: real orders, under the shared account lock, inside the shared
  account risk checks (live/shared_account_risk.py) and the pilot caps
  (live/spread_policy.py). Requires KALSHI_ENV=prod,
  ALLOW_PRODUCTION_TRADING=YES, SPREAD_AUTO_ARM=YES, shared-account mode and
  the owner-created marker /etc/market-maker-spread.enabled. The shadow
  ledger keeps running beside it.
- ``--status``: summary of both ledgers.

Every order and cancel is journaled before it is sent. An exchange HTTP 4xx
refusal is recorded as rejected only after a signed read finds no order with
that client id; any other failure halts all bots until the owner reconciles.
A KILL file in STATE cancels this bot's resting orders.
"""

import argparse
import fcntl
import json
import math
import os
import re
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from kalshi import api as kalshi_api
from kalshi import shard_funding
from kalshi.trading import Order, TradingClient, TradingError

# Every module a pass can need is loaded when the process starts (including
# the two modules the shared account check loads), so a code release landing
# mid-pass cannot mix old and new code inside one pass.
from live import nfl_policy, prod_nba_auto, prod_nfl_auto, production_lock  # noqa: F401
from live import shared_account_risk as shared
from live import spread_policy as P

NY = ZoneInfo("America/New_York")
REQUIRED = {
    "KALSHI_ENV": "prod",
    "ALLOW_PRODUCTION_TRADING": "YES",
    "SPREAD_AUTO_ARM": "YES",
}


# --------------------------------------------------------------- journal


def write_event(path, data):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_events(path):
    if not path.exists():
        return []
    raw = path.read_text()
    if raw and not raw.endswith("\n"):
        raise TradingError("Incomplete spread journal: HALT")
    try:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (ValueError, TypeError) as error:
        raise TradingError("Invalid spread journal: HALT") from error


def records(events):
    """Intents by client id, accepted order ids, and refused client ids."""
    intents = {}
    for e in events:
        if e.get("event") != "intent":
            continue
        cid = e.get("client_order_id")
        if not cid or cid in intents:
            raise TradingError("Duplicate or incomplete spread intent: HALT")
        intents[cid] = e
    if any(e.get("event") == "unknown_outcome" for e in events):
        raise TradingError("Ambiguous spread order: HALT, reconcile manually")
    accepted = {}
    for e in events:
        if e.get("event") == "accepted":
            cid, oid = e.get("client_order_id"), e.get("order_id")
            if cid not in intents or not oid or cid in accepted:
                raise TradingError("Invalid spread acceptance: HALT")
            accepted[cid] = str(oid)
    refused = shared.spread_rejected_ids(events)
    if set(intents) != set(accepted) | refused:
        raise TradingError("Unreconciled spread submission: HALT")
    return intents, accepted, refused


# ------------------------------------------------------------ the market


def _cents(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    cents = round(number * 100)
    return cents if abs(cents - number * 100) < 1e-6 else None


def excluded(ticker, other_tickers):
    return str(ticker).startswith(P.EXCLUDED_PREFIXES) or ticker in other_tickers


def quote_prices(yes_bid_cents, yes_ask_cents):
    """(YES bid price, NO bid price) one cent inside, or None if not eligible."""
    if yes_bid_cents is None or yes_ask_cents is None:
        return None
    if not 0 < yes_bid_cents < yes_ask_cents < 100:
        return None
    if yes_ask_cents - yes_bid_cents < P.MIN_SPREAD_CENTS:
        return None
    yes_price = yes_bid_cents + 1
    no_price = (100 - yes_ask_cents) + 1
    lo, hi = P.PRICE_RANGE_CENTS
    if not (lo <= yes_price <= hi and lo <= no_price <= hi):
        return None
    # Both stay strictly inside the spread: post-only, never crossing.
    if not (yes_price < yes_ask_cents and 100 - no_price > yes_bid_cents):
        return None
    return yes_price, no_price


def eligible_markets(markets, series, now, other_tickers=frozenset()):
    """Open markets in the window with a wide two-sided quote."""
    rows = []
    for m in markets:
        ticker = m.get("ticker")
        if not ticker or excluded(ticker, other_tickers):
            continue
        if series in P.MAKER_FEE_SERIES or m.get("status") not in ("active", "open"):
            continue
        expires = pd.to_datetime(
            m.get("expected_expiration_time"), utc=True, errors="coerce"
        )
        if pd.isna(expires):
            continue
        hours = (expires.to_pydatetime() - now).total_seconds() / 3600
        if not P.WINDOW_HOURS[0] <= hours <= P.WINDOW_HOURS[1]:
            continue
        bid, ask = _cents(m.get("yes_bid_dollars")), _cents(m.get("yes_ask_dollars"))
        prices = quote_prices(bid, ask)
        if prices is None:
            continue
        rows.append(
            {
                "ticker": ticker,
                "series": series,
                "event_ticker": m.get("event_ticker", ""),
                "yes_bid": bid,
                "yes_ask": ask,
                "spread": ask - bid,
                "yes_price": prices[0],
                "no_price": prices[1],
                "expiration_utc": expires.isoformat(),
            }
        )
    return rows


def book_quote(book, own=()):
    """(best YES bid, best YES offer) in cents from a public order book, with
    our own resting quotes taken out so the bot never prices off itself.

    ``own`` holds (side, price_cents, count) for our resting quotes in that
    market. Our NO bid at q shows in the book's NO bids at q.
    """
    if not isinstance(book, dict):
        return None, None
    depth = {}
    for side in ("yes", "no"):
        levels = {}
        for entry in book.get(f"{side}_dollars") or []:
            try:
                price, quantity = _cents(entry[0]), float(entry[1])
            except (TypeError, ValueError, IndexError, KeyError):
                return None, None
            if price is None or not math.isfinite(quantity):
                return None, None
            levels[price] = levels.get(price, 0.0) + quantity
        depth[side] = levels
    for side, price, count in own:
        if price in depth.get(side, {}):
            depth[side][price] -= count
    yes = [p for p, q in depth["yes"].items() if q > 1e-9]
    no = [p for p, q in depth["no"].items() if q > 1e-9]
    return (max(yes) if yes else None), (100 - max(no) if no else None)


def _dollars(cents, default):
    return f"{(default if cents is None else cents) / 100:.2f}"


def universe(fetch_markets, now, other_tickers=frozenset(), own=None, fetch_book=None):
    """Eligible markets, widest spread first.

    For markets where we already rest quotes (``own``: ticker -> list of
    (side, price_cents, count)), the listed best bid and offer may be ours, so
    the quote comes from the order book with our orders removed; a market
    whose book cannot be read is left out this pass (its quotes are pulled).
    """
    own = own or {}
    rows = []
    for series in P.SERIES:
        try:
            markets = fetch_markets(series, status="open") or []
        except Exception:  # one bad series must not stop the others
            continue
        adjusted = []
        for m in markets:
            ticker = m.get("ticker")
            if ticker in own:
                try:
                    bid, ask = book_quote(fetch_book(ticker), own[ticker])
                except Exception:
                    continue
                m = {
                    **m,
                    "yes_bid_dollars": _dollars(bid, 0),
                    "yes_ask_dollars": _dollars(ask, 100),
                }
            adjusted.append(m)
        rows.extend(eligible_markets(adjusted, series, now, other_tickers))
    return sorted(rows, key=lambda r: (-r["spread"], r["ticker"]))


# ---------------------------------------------------------------- shadow


def shadow_post(events, markets, now):
    """At most one shadow quote per market and side per hour."""
    recent = {}
    for e in events:
        if e.get("event") == "shadow_quote":
            key = (e["ticker"], e["side"])
            recent[key] = max(recent.get(key, ""), e["posted_utc"])
    cutoff = (now - timedelta(minutes=P.SHADOW_REPOST_MINUTES)).isoformat()
    new = []
    for m in markets:
        for side, price in (("yes", m["yes_price"]), ("no", m["no_price"])):
            if recent.get((m["ticker"], side), "") > cutoff:
                continue
            new.append(
                {
                    "event": "shadow_quote",
                    "id": str(uuid.uuid4()),
                    "ticker": m["ticker"],
                    "series": m["series"],
                    "event_ticker": m["event_ticker"],
                    "side": side,
                    "price_cents": price,
                    "spread": m["spread"],
                    "posted_utc": now.isoformat(),
                    "expires_utc": (
                        now + timedelta(minutes=P.SHADOW_REPOST_MINUTES)
                    ).isoformat(),
                    "market_expiration_utc": m["expiration_utc"],
                }
            )
    return new


def contracts_through(trades, side, price_cents, start, end):
    """Contracts a taker traded at or through our price in (start, end].

    A YES bid at p is hit by YES sellers (taker side "no") at p or below; a NO
    bid at q is a YES offer at 1 - q, hit by YES buyers at 1 - q or above. We
    were one cent inside, so trades at exactly our price count. Block trades
    never meet resting orders and are ignored.
    """
    total = 0.0
    level = price_cents / 100 if side == "yes" else (100 - price_cents) / 100
    for t in trades:
        if t.get("is_block_trade"):
            continue
        when = pd.to_datetime(t.get("created_time"), utc=True, errors="coerce")
        if pd.isna(when) or not start < when.to_pydatetime() <= end:
            continue
        taker = str(t.get("taker_outcome_side") or "").lower()
        price = t.get("yes_price")
        if price is None or not math.isfinite(float(price)):
            continue
        if side == "yes" and taker == "no" and float(price) <= level + 1e-9:
            total += float(t.get("count") or 0)
        if side == "no" and taker == "yes" and float(price) >= level - 1e-9:
            total += float(t.get("count") or 0)
    return total


def shadow_score(events, now, fetch_trades):
    """Fill counts for shadow quotes whose hour has ended."""
    scored = {e["id"] for e in events if e.get("event") == "shadow_fill"}
    due = [
        e
        for e in events
        if e.get("event") == "shadow_quote"
        and e["id"] not in scored
        and e["expires_utc"] <= now.isoformat()
    ]
    out = []
    by_ticker = {}
    for e in due:
        by_ticker.setdefault(e["ticker"], []).append(e)
    for ticker, quotes in by_ticker.items():
        start = min(datetime.fromisoformat(q["posted_utc"]) for q in quotes)
        end = max(datetime.fromisoformat(q["expires_utc"]) for q in quotes)
        try:
            trades = fetch_trades(ticker, int(start.timestamp()), int(end.timestamp()))
        except Exception:
            continue  # try again next pass
        for q in quotes:
            through = contracts_through(
                trades,
                q["side"],
                q["price_cents"],
                datetime.fromisoformat(q["posted_utc"]),
                datetime.fromisoformat(q["expires_utc"]),
            )
            out.append({"event": "shadow_fill", "id": q["id"], "through": through})
    return out


def shadow_settle(events, fetch_market):
    """Market results for shadow quotes that would have filled."""
    filled = {
        e["id"]
        for e in events
        if e.get("event") == "shadow_fill" and float(e.get("through", 0)) >= 1
    }
    done = {e["ticker"] for e in events if e.get("event") == "shadow_result"}
    tickers = {
        e["ticker"]
        for e in events
        if e.get("event") == "shadow_quote" and e["id"] in filled
    }
    out = []
    for ticker in sorted(tickers - done):
        try:
            market = fetch_market(ticker) or {}
        except Exception:
            continue
        result = market.get("result")
        if result in ("yes", "no"):
            out.append({"event": "shadow_result", "ticker": ticker, "result": result})
    return out


def shadow_summary(events, flow=0.25):
    quotes = {e["id"]: e for e in events if e.get("event") == "shadow_quote"}
    fills = {
        e["id"]: float(e["through"]) for e in events if e.get("event") == "shadow_fill"
    }
    results = {
        e["ticker"]: e["result"] for e in events if e.get("event") == "shadow_result"
    }
    rows = []
    for qid, through in fills.items():
        q = quotes.get(qid)
        if q is None:
            continue
        result = results.get(q["ticker"])
        won = None if result is None else float(result == q["side"])
        rows.append(
            {
                "ticker": q["ticker"],
                "event_ticker": q["event_ticker"],
                "filled": through >= 1,
                "expected": 1 - (1 - flow) ** math.floor(through),
                "pnl": None if won is None else won - q["price_cents"] / 100,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {"quotes": len(quotes), "scored": 0}
    settled = frame[frame.filled & frame.pnl.notna()]
    out = {
        "quotes": len(quotes),
        "scored": len(frame),
        "fill_rate": float(frame.filled.mean()),
        "filled": int(frame.filled.sum()),
        "settled_fills": len(settled),
    }
    if len(settled):
        out["cents_per_contract"] = 100 * float(settled.pnl.mean())
        weights = frame.loc[settled.index, "expected"]
        if weights.sum() > 0:
            out[f"cents_per_contract_flow_{flow:g}"] = 100 * float(
                (settled.pnl * weights).sum() / weights.sum()
            )
        out["dollars_one_contract"] = float(settled.pnl.sum())
    return out


def run_shadow(state_dir, now, public, markets=None):
    path = state_dir / "shadow.jsonl"
    events = load_events(path)
    for e in shadow_score(events, now, public["fetch_trades"]):
        write_event(path, e)
    events = load_events(path)
    for e in shadow_settle(events, public["fetch_market"]):
        write_event(path, e)
    if markets is None:
        markets = universe(public["fetch_markets"], now)
    for e in shadow_post(load_events(path), markets, now):
        write_event(path, e)
    return shadow_summary(load_events(path))


# ------------------------------------------------------------------ live


def guard(env, client):
    for name, expected in REQUIRED.items():
        if env.get(name) != expected:
            raise TradingError(f"Unarmed spread maker: {name} must be {expected}")
    if not P.ARM_MARKER.exists():
        raise TradingError("Owner has not enabled the spread maker")
    if not shared.dual_mode(env):
        raise TradingError("Spread maker requires shared-account mode")
    if client.env != "prod" or client.dry_run or not client.can_sign:
        raise TradingError("Signed production execution client required")


def armed(env):
    return env.get("SPREAD_AUTO_ARM") == "YES" and P.ARM_MARKER.exists()


def own_realized(settlements, tickers, now):
    """Daily and cumulative realized P&L on this bot's settled markets."""
    today = now.astimezone(NY).date()
    seen, daily, total = set(), 0.0, 0.0
    for item in settlements:
        ticker = item.get("market_ticker") or item.get("ticker")
        if ticker not in tickers:
            continue
        accounted = nfl_policy.settlement_accounting(item)
        amount = accounted.get("net_profit_dollars")
        if not accounted["accounting_complete"] or amount is None:
            raise TradingError("Incomplete spread settlement: HALT")
        key = (ticker, str(item.get("settled_time")))
        if key in seen:
            continue
        seen.add(key)
        total += float(amount)
        when = pd.to_datetime(item.get("settled_time"), utc=True, errors="coerce")
        if pd.notna(when) and when.to_pydatetime().astimezone(NY).date() == today:
            daily += float(amount)
    return round(daily, 4), round(total, 4)


def held_cost(positions, fills, owned_orders):
    """Dollars at risk in held contracts: |net| x average price paid, else $1."""
    paid = {}
    for f in fills:
        if str(f.get("order_id")) not in owned_orders:
            continue
        ticker = f.get("ticker") or f.get("market_ticker")
        side = str(f.get("side") or "").lower()
        key = "yes_price_dollars" if side == "yes" else "no_price_dollars"
        try:
            price, count = float(f.get(key)), float(f.get("count_fp") or f.get("count"))
        except (TypeError, ValueError):
            continue
        cost, n = paid.get((ticker, side), (0.0, 0.0))
        paid[(ticker, side)] = (cost + price * count, n + count)
    total = 0.0
    for ticker, qty in positions.items():
        side = "yes" if qty > 0 else "no"
        cost, n = paid.get((ticker, side), (0.0, 0.0))
        average = cost / n if n > 0 else 1.0
        total += abs(qty) * average
    return round(total, 4)


def desired_quotes(markets, positions):
    """{(ticker, side): price} after the inventory cap."""
    out = {}
    for m in markets:
        net = positions.get(m["ticker"], 0.0)
        if net < P.MAX_NET_PER_MARKET - 1e-9:
            out[(m["ticker"], "yes")] = m["yes_price"]
        if net > -P.MAX_NET_PER_MARKET + 1e-9:
            out[(m["ticker"], "no")] = m["no_price"]
    return out


def cancel_order(client, journal, order_id, ticker, reason, now):
    write_event(
        journal,
        {
            "event": "cancel_intent",
            "utc": now.isoformat(),
            "order_id": order_id,
            "ticker": ticker,
            "reason": reason,
        },
    )
    try:
        client.cancel(order_id, ticker=ticker)
    except Exception as error:
        # A quote can fill or expire between our read and the cancel. Accept
        # that only when a signed read shows the order is no longer resting.
        if is_http_4xx(error) is not None:
            still = [
                o
                for o in client.orders("resting", ticker=ticker)
                if str(o.get("order_id")) == str(order_id)
            ]
            if not still:
                write_event(
                    journal,
                    {
                        "event": "cancel_moot",
                        "utc": datetime.now(UTC).isoformat(),
                        "order_id": order_id,
                        "detail": str(error)[:200],
                    },
                )
                return
        raise TradingError("Cannot confirm spread cancellation: HALT") from error
    write_event(
        journal,
        {
            "event": "cancel_accepted",
            "utc": datetime.now(UTC).isoformat(),
            "order_id": order_id,
        },
    )


def cancel_all_owned(client, journal, resting, reason, now):
    for order in resting:
        cancel_order(client, journal, order["order_id"], order["ticker"], reason, now)
    return len(resting)


def record_execution(journal, events, owned_orders, fills, settlements, tickers):
    seen_fills = {e.get("fill_id") for e in events if e.get("event") == "fill"}
    seen_settled = {
        (e.get("ticker"), e.get("utc"))
        for e in events
        if e.get("event") == "settlement"
    }
    for fill in fills:
        oid = str(fill.get("order_id"))
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid or fid in seen_fills or oid not in owned_orders:
            continue
        write_event(
            journal,
            {
                "event": "fill",
                "fill_id": str(fid),
                "order_id": oid,
                "utc": str(fill.get("created_time", "")),
                "ticker": str(fill.get("ticker") or fill.get("market_ticker") or ""),
                "side": str(fill.get("side", "")),
                "count": str(fill.get("count_fp", fill.get("count", ""))),
                "yes_price": str(fill.get("yes_price_dollars", "")),
                "no_price": str(fill.get("no_price_dollars", "")),
                "fee": str(fill.get("fee_cost", "")),
                "is_taker": fill.get("is_taker"),
            },
        )
        seen_fills.add(fid)
    for item in settlements:
        ticker = item.get("market_ticker") or item.get("ticker")
        key = (ticker, str(item.get("settled_time", "")))
        if ticker not in tickers or key in seen_settled:
            continue
        write_event(
            journal,
            {
                "event": "settlement",
                "ticker": ticker,
                "utc": key[1],
                **nfl_policy.settlement_accounting(item),
            },
        )
        seen_settled.add(key)


def is_http_4xx(error):
    match = re.search(r"-> HTTP ([0-9]{3})", str(error))
    return int(match.group(1)) if match and match.group(1).startswith("4") else None


def place_quote(client, journal, market, side, price, now, require_shard):
    """Journal, place, and record one post-only quote. Returns the outcome."""
    order = Order(
        ticker=market["ticker"],
        side=side,
        count=P.CONTRACTS,
        price_cents=int(price),
        expiration_ts=int(
            (now + timedelta(minutes=P.ORDER_LIFETIME_MINUTES)).timestamp()
        ),
        post_only=True,
        client_order_id=f"smm-spread-{uuid.uuid4()}",
    )
    cost = round(P.CONTRACTS * price / 100, 2)
    try:
        order.exchange_index = require_shard(client, order.ticker, cost)
    except TradingError as error:
        if str(error).startswith("SHARD_UNFUNDED_"):
            return "shard_unfunded"
        raise
    write_event(
        journal,
        {
            "event": "intent",
            "utc": now.isoformat(),
            "client_order_id": order.client_order_id,
            "ticker": order.ticker,
            "series": market["series"],
            "event_ticker": market["event_ticker"],
            "side": side,
            "price_cents": int(price),
            "count": P.CONTRACTS,
            "cost": cost,
            "spread": market["spread"],
            "market_expiration_utc": market["expiration_utc"],
            "strategy_version": P.STRATEGY_VERSION,
        },
    )
    try:
        result = client.place(order)
    except Exception as error:
        status = is_http_4xx(error)
        if status is not None:
            # The exchange refused the request. Confirm with a signed read that
            # no such order exists before treating it as never placed.
            resting = client.orders("resting", ticker=order.ticker)
            match = [
                o for o in resting if o.get("client_order_id") == order.client_order_id
            ]
            if not match:
                write_event(
                    journal,
                    {
                        "event": "rejected_4xx",
                        "utc": datetime.now(UTC).isoformat(),
                        "client_order_id": order.client_order_id,
                        "http_status": status,
                        "evidence": shared.SPREAD_REJECTION_EVIDENCE,
                        "detail": str(error)[:200],
                    },
                )
                return "rejected"
            result = {"order_id": match[0].get("order_id")}
        else:
            write_event(
                journal,
                {
                    "event": "unknown_outcome",
                    "utc": datetime.now(UTC).isoformat(),
                    "client_order_id": order.client_order_id,
                    "type": type(error).__name__,
                },
            )
            raise TradingError(
                "Ambiguous spread submission: all bots halt until manual audit"
            ) from error
    if not result.get("order_id"):
        write_event(
            journal,
            {
                "event": "unknown_outcome",
                "utc": datetime.now(UTC).isoformat(),
                "client_order_id": order.client_order_id,
                "type": "missing_order_id",
            },
        )
        raise TradingError("Spread placement returned no order id: HALT")
    write_event(
        journal,
        {
            "event": "accepted",
            "utc": datetime.now(UTC).isoformat(),
            "client_order_id": order.client_order_id,
            "order_id": str(result["order_id"]),
        },
    )
    return "accepted"


def fresh_prices(public, ticker, own=()):
    """Our quote prices from a fresh read of the book, without our own quotes."""
    market = public["fetch_market"](ticker) or {}
    if market.get("status") not in ("active", "open"):
        return None
    return quote_prices(*book_quote(public["fetch_orderbook"](ticker), own))


def pass_live(client, env, now, state_dir, public, require_shard=None):
    """One live pass: (report for last_scan.json, eligible markets or None)."""
    require_shard = require_shard or shard_funding.require_funded_shard
    guard(env, client)
    journal = state_dir / "journal.jsonl"
    events = load_events(journal)
    intents, accepted, _ = records(events)
    state, context = shared.state_for(client, "spread", now)
    order_to_cid = {oid: cid for cid, oid in accepted.items()}
    owned_orders = set(order_to_cid)
    own_tickers = {i["ticker"] for i in intents.values()}
    record_execution(
        journal, events, owned_orders, state["fills"], state["settlements"], own_tickers
    )
    report = Counter()
    resting = [
        {"order_id": str(o["order_id"]), "ticker": o.get("ticker")}
        for o in state["resting"]
    ]
    daily, total = own_realized(state["settlements"], own_tickers, now)
    if daily <= -P.DAILY_LOSS_STOP + 1e-9 or total <= -P.CUMULATIVE_LOSS_STOP + 1e-9:
        report["canceled"] = cancel_all_owned(
            client, journal, resting, "loss_stop", now
        )
        return {
            "decision": "spread_loss_stop",
            "daily": daily,
            "total": total,
            **report,
        }, None
    if shared.account_loss_stop(context):
        report["canceled"] = cancel_all_owned(
            client, journal, resting, "account_loss_stop", now
        )
        return {"decision": "account_loss_stop", **report}, None
    others = {
        t for t, cohort in context["ownership"]["tickers"].items() if cohort != "spread"
    }
    resting_intents = []
    own = {}
    for order in resting:
        intent = intents.get(order_to_cid.get(order["order_id"]))
        if intent is None:
            raise TradingError("Resting order missing from spread journal: HALT")
        resting_intents.append((order, intent))
        own.setdefault(intent["ticker"], []).append(
            (intent["side"], int(intent["price_cents"]), float(intent["count"]))
        )
    markets = universe(
        public["fetch_markets"], now, others, own, public["fetch_orderbook"]
    )
    by_ticker = {m["ticker"]: m for m in markets}
    positions = state["positions"]
    wanted = desired_quotes(markets, positions)
    # Cancel quotes that are stale, too old, or no longer wanted.
    keep = {}
    oldest = (now - timedelta(minutes=P.ORDER_LIFETIME_MINUTES - 5)).isoformat()
    for order, intent in resting_intents:
        key = (intent["ticker"], intent["side"])
        if (
            wanted.get(key) == intent["price_cents"]
            and intent["utc"] > oldest
            and key not in keep
        ):
            keep[key] = intent
            continue
        cancel_order(
            client, journal, order["order_id"], intent["ticker"], "requote", now
        )
        report["canceled"] += 1
    # Exposure: kept resting quotes at cost plus held contracts at cost.
    exposure = sum(float(i["cost"]) for i in keep.values()) + held_cost(
        positions, state["fills"], owned_orders
    )
    today = now.astimezone(NY).date()
    submitted_today = sum(
        datetime.fromisoformat(i["utc"]).astimezone(NY).date() == today
        for i in intents.values()
    )
    placed = 0
    # Our quotes resting in each market (kept, then placed this pass), taken
    # out of every fresh book read.
    mine = {}
    for (ticker, _), intent in keep.items():
        mine.setdefault(ticker, []).append(
            (intent["side"], int(intent["price_cents"]), float(intent["count"]))
        )
    for (ticker, side), price in wanted.items():
        if (ticker, side) in keep:
            continue
        if placed >= P.MAX_ORDERS_PER_PASS:
            report["skip_pass_cap"] += 1
            break
        if submitted_today + placed >= P.MAX_SUBMISSIONS_PER_DAY:
            report["skip_daily_cap"] += 1
            break
        cost = P.CONTRACTS * price / 100
        if exposure + cost > P.MAX_ACTIVE_COST + 1e-9:
            report["skip_active_cap"] += 1
            continue
        try:
            fresh = fresh_prices(public, ticker, mine.get(ticker, []))
        except Exception:
            fresh = None
        if fresh is None or fresh[0 if side == "yes" else 1] != price:
            report["skip_quote_moved"] += 1
            continue
        # The pass start time: expirations are then a little early, never late.
        outcome = place_quote(
            client, journal, by_ticker[ticker], side, price, now, require_shard
        )
        report[outcome] += 1
        if outcome == "shard_unfunded":
            break
        placed += 1
        if outcome == "accepted":
            exposure += cost
            mine.setdefault(ticker, []).append((side, int(price), float(P.CONTRACTS)))
    return {
        "decision": "quoted",
        "eligible_markets": len(markets),
        "resting_kept": len(keep),
        "placed": placed,
        "exposure_dollars": round(exposure, 2),
        "realized_today": daily,
        "realized_total": total,
        **report,
    }, markets


def cancel_owned_on_kill(client, journal):
    events = load_events(journal)
    ids = {e["order_id"] for e in events if e.get("event") == "accepted"}
    cids = {e["client_order_id"] for e in events if e.get("event") == "intent"}
    now = datetime.now(UTC)
    canceled = 0
    for item in client.orders("resting"):
        if item.get("order_id") not in ids and item.get("client_order_id") not in cids:
            continue
        cancel_order(client, journal, item["order_id"], item["ticker"], "kill", now)
        canceled += 1
    print(f"SPREAD MAKER HALTED: canceled {canceled} owned resting orders")
    return canceled


# ------------------------------------------------------------------ main


def public_api():
    return {
        "fetch_markets": kalshi_api.fetch_markets,
        "fetch_market": kalshi_api.fetch_market,
        "fetch_orderbook": kalshi_api.fetch_orderbook,
        "fetch_trades": kalshi_api.fetch_trades,
    }


def write_report(state_dir, report):
    target = state_dir / "last_scan.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, default=str) + "\n")
    temporary.chmod(0o600)
    temporary.replace(target)


def preflight(client, env, now, state_dir, public):
    """Signed GET-only readiness check before arming. Never places or cancels.

    Checks production settings (except this bot's arm switch), that the
    spread journal reconciles, that all three bots' journals together own
    every order and position in the account, and how many markets qualify
    right now. Prints counts only: no balances, ids or prices.
    """
    failures = []
    for name in ("KALSHI_ENV", "ALLOW_PRODUCTION_TRADING"):
        if env.get(name) != REQUIRED[name]:
            failures.append(f"{name} is not {REQUIRED[name]}")
    if not shared.dual_mode(env):
        failures.append("shared-account mode is off")
    if client.env != "prod" or client.dry_run or not client.can_sign:
        failures.append("no signed production client")
    if failures:
        return {"ready": False, "failures": failures}
    journal = state_dir / "journal.jsonl"
    journal.touch(mode=0o600, exist_ok=True)
    intents, accepted, refused = records(load_events(journal))
    state, context = shared.state_for(client, "spread", now)
    for sport in ("nba", "nfl"):
        shared.state_for(client, sport, now)  # the other bots still reconcile
    others = {
        t for t, cohort in context["ownership"]["tickers"].items() if cohort != "spread"
    }
    markets = universe(public["fetch_markets"], now, others)
    return {
        "ready": True,
        "failures": [],
        "armed": armed(env),
        "spread_orders_journaled": len(intents),
        "spread_resting": len(state["resting"]),
        "spread_markets_held": len(state["positions"]),
        "account_loss_stop": bool(shared.account_loss_stop(context)),
        "eligible_markets_now": len(markets),
    }


def status(state_dir):
    journal = load_events(state_dir / "journal.jsonl")
    print("Live intents:", sum(e.get("event") == "intent" for e in journal))
    print("Live accepted:", sum(e.get("event") == "accepted" for e in journal))
    print("Live refused (4xx):", sum(e.get("event") == "rejected_4xx" for e in journal))
    print("Live fills:", sum(e.get("event") == "fill" for e in journal))
    settled = [e for e in journal if e.get("event") == "settlement"]
    net = sum(float(e.get("net_profit_dollars") or 0) for e in settled)
    print(f"Live settled markets: {len(settled)}, net ${net:+.2f}")
    print(
        "Shadow:", json.dumps(shadow_summary(load_events(state_dir / "shadow.jsonl")))
    )
    last = state_dir / "last_scan.json"
    if last.exists():
        print("Last pass:", last.read_text())


def prefetch(public):
    """Read every series' open markets once, before taking the account lock,
    so the other bots wait only for the signed part of a pass."""
    listings = {}
    for series in P.SERIES:
        try:
            listings[series] = public["fetch_markets"](series, status="open") or []
        except Exception:  # one bad series must not stop the others
            continue
    return {
        **public,
        "fetch_markets": lambda series, status="open": listings.get(series, []),
    }


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ("--shadow", "--live", "--auto", "--status", "--preflight"):
        mode.add_argument(flag, action="store_true")
    args = parser.parse_args()
    state_dir = P.STATE
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.status:
        status(state_dir)
        return
    if args.preflight:
        public = prefetch(public_api())
        with production_lock.account_lock():
            client = TradingClient(dry_run=False, env="prod")
            result = preflight(client, os.environ, datetime.now(UTC), state_dir, public)
        print("SPREAD PREFLIGHT", json.dumps(result, sort_keys=True))
        if not result["ready"]:
            raise SystemExit(2)
        return
    live = args.live or (args.auto and armed(os.environ))
    journal = state_dir / "journal.jsonl"
    if live:
        journal.touch(mode=0o600, exist_ok=True)
    kill = (state_dir / "KILL").exists() and journal.exists()
    with (state_dir / "lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if kill:  # cancels only; works even after the owner disarms the bot
            with production_lock.account_lock():
                client = TradingClient(dry_run=False, env="prod")
                if client.env != "prod" or not client.can_sign:
                    raise TradingError("KILL needs signed production credentials")
                cancel_owned_on_kill(client, journal)
            return
        started = datetime.now(UTC)
        report = {"run_utc": started.isoformat(), "mode": "live" if live else "shadow"}
        public = prefetch(public_api())
        markets = None
        if live:
            try:
                with production_lock.account_lock():
                    client = TradingClient(dry_run=False, env="prod")
                    report["live"], markets = pass_live(
                        client, os.environ, datetime.now(UTC), state_dir, public
                    )
            except Exception as error:
                report["live"] = {"decision": "halt", "error": str(error)[:300]}
                write_report(state_dir, report)
                raise
        # The shadow ledger needs no lock: public reads and its own file only.
        report["shadow"] = run_shadow(state_dir, started, public, markets)
        write_report(state_dir, report)
        print("SPREAD MAKER", json.dumps(report, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
