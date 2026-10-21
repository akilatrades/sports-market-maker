"""Bounded unattended NBA production worker (shares one account with NFL).

Limits are the MAX_* constants below (lifetime gross-cost budget MAX_GROSS_COST,
including a fee buffer) plus the account-wide caps in shared_account_risk. At
most MAX_NEW_ORDERS_PER_PASS new post-only orders per pass, each charged to
every cap before the next is considered; no automatic re-arming, and durable
journal before each network write. Fail closed on inconsistent balances,
orders, positions, fills or model data.
"""

import argparse
import fcntl
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.api import fetch_market
from kalshi.paper_props import candidate_orders
from kalshi.shard_funding import require_funded_shard
from kalshi.trading import Order, TradingClient, TradingError
from live.nfl_policy import settlement_accounting
from live.nba_inputs import MODEL_VERSION
from live.reconciled_attempts import rejected_client_ids

STRATEGY_VERSION = "nba-no-v5-one-contract-breadth"
# Earlier versions whose resting orders are left untouched to expire while
# new orders wait (see legacy_resting_count); any other version HALTs.
PRIOR_VERSIONS = frozenset(
    {
        "nba-no-v2-opening-audit",
        "nba-no-v3-long-resting-throughput",
        "nba-no-v4-smaller-orders-edge3-baseline",
    }
)

# Owner-approved v5 sizing for a $250 account (2026-10-21, RESEARCH_LOG.md
# "NBA rules v5"): many one-contract orders so the edge can be measured on
# about 1,900 fills. Pricing is unchanged. Submitted cost is charged to the
# daily and lifetime allowances even when an order expires unfilled; the
# realized-loss stops below are the binding money limit (-$60 total is 24% of
# the account).
MAX_GROSS_COST = 2000.0  # lifetime submitted allowance (pauses for review)
MAX_ORDER_COST = 4.0
MAX_ACTIVE_COST = 150.0  # orders rest until their games end, so ~ one day
MAX_GAME_COST = 25.0
MAX_TEAM_COST = 25.0  # per team per New York day
MAX_DAILY_COST = 150.0
MAX_GAME_ORDERS = 40
MAX_CONTRACTS = 1  # one contract per order: more separate fills, same cash
MAX_NEW_ORDERS_PER_PASS = 3
PRICE_BAND_CENTS = (5, 95)  # NO price, inclusive
# systemd stops a pass after TimeoutStartSec=240. A stop between an order's
# journal intent and its acceptance halts all future orders, so no new order
# starts after this many seconds of process runtime (main() sets the clock).
NEW_ORDER_DEADLINE_SECONDS = 150
PROCESS_START = None
# Queue position is telemetry: observe each resting order at most this often.
QUEUE_OBSERVATION_MINUTES = 10
# The NBA's official injury report (published every 15 minutes) adds vetoes
# on top of ESPN's feed. It is ignored, and the scan says so, when it cannot
# be read in OFFICIAL_REPORT_SECONDS or is older than the limit below.
OFFICIAL_REPORT_SECONDS = 20
OFFICIAL_REPORT_MAX_AGE_MINUTES = 60
# P&L circuit breakers: no new orders after these realized losses.
MAX_REALIZED_DAILY_LOSS = 20.0
MAX_REALIZED_CUMULATIVE_LOSS = 60.0
FEE_RESERVE = 1.10
WINDOW = (2.0, 6.0)  # NEW orders still start 2–6 hours before tip
# ALREADY-ACCEPTED orders may rest until the verified scheduled tip.
# This is separate from the entry window: the final two hours were not
# eligible for new posts, but cutting off existing maker liquidity then
# made the live execution policy differ from historical tests.
RESTING_WINDOW = (0.0, 6.0)
STATE = Path("/home/trader/prod-nba-auto")
REQUIRED = {
    "KALSHI_ENV": "prod",
    "TRADE_MODE": "live",
    "PROD_NBA_AUTO_ARM": "YES",
    "ALLOW_PRODUCTION_TRADING": "YES",
}


def guard(env, client):
    for name, expected in REQUIRED.items():
        if env.get(name) != expected:
            raise TradingError(f"Unarmed production auto: {name} must be {expected}")
    if env.get("DEMO_PILOT") == "1" or env.get("TRADE_MARKET") != "nba":
        raise TradingError("NBA auto cannot use Demo pilot or another market")
    if client.env != "prod" or client.dry_run or not client.can_sign:
        raise TradingError("Signed production execution client required")


def write_event(path, data):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_journal(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def money(n):
    value = float(n)
    if not math.isfinite(value) or value < 0:
        raise TradingError(f"Invalid risk value {n!r}")
    return round(value, 4)


def reserve(cost):
    return math.ceil(money(cost) * FEE_RESERVE * 100 - 1e-8) / 100


def elapsed_seconds():
    """Seconds since main() started this process; 0 when not run via main()."""
    return 0.0 if PROCESS_START is None else time.monotonic() - PROCESS_START


def last_queue_times(events):
    """Latest queue-observation time per order id, from one journal scan."""
    return {
        str(event.get("order_id")): event.get("utc")
        for event in events
        if event.get("event") == "queue"
    }


def queue_observation_due(last_times, order_id, now):
    """True unless this order's queue was observed within the last few minutes."""
    last = last_times.get(order_id)
    if last is None:
        return True
    try:
        age = (pd.Timestamp(now) - pd.Timestamp(last)).total_seconds() / 60
    except (TypeError, ValueError):
        return True
    return not 0 <= age < QUEUE_OBSERVATION_MINUTES


def records(events):
    attempts = [e for e in events if e.get("event") == "intent"]
    accepted = {}
    accepted_order_ids = set()
    for event in events:
        if event.get("event") != "accepted":
            continue
        client_id = event.get("client_order_id")
        order_id = event.get("order_id")
        if not client_id or not order_id:
            raise TradingError(
                "Malformed exchange acceptance in production journal: HALT"
            )
        if client_id in accepted or order_id in accepted_order_ids:
            raise TradingError(
                "Duplicate exchange acceptance in production journal: HALT"
            )
        accepted[client_id] = event
        accepted_order_ids.add(order_id)
    if len({e["client_order_id"] for e in attempts}) != len(attempts):
        raise TradingError("Duplicate client order ID in production journal")
    rejected = rejected_client_ids(events)
    for attempt in attempts:
        if (
            attempt["client_order_id"] not in accepted
            and attempt["client_order_id"] not in rejected
        ):
            raise TradingError(
                "Uncertain production order attempt: HALT, reconcile manually"
            )
    return attempts, accepted


def current_production_state(client, attempts, accepted, rejected=frozenset()):
    """Verify every live order/position belongs to the strategy journal."""
    resting = client.orders("resting")
    positions = client.positions()
    if not isinstance(resting, list) or not isinstance(positions, list):
        raise TradingError("Unparseable production orders/positions")
    # A live account should be dedicated to this pilot. If there are foreign
    # resting orders or positions, do not allocate additional risk.
    known_ids = {r["order_id"] for r in accepted.values()}
    tickers = {a["ticker"] for a in attempts}
    unknown_orders = [r for r in resting if r.get("order_id") not in known_ids]
    if unknown_orders:
        raise TradingError("Foreign resting production orders: HALT")
    held = []
    for p in positions:
        pos = p.get("position_fp")
        if pos is None:
            pos = p.get("position")
        if pos is None:
            raise TradingError("Cannot parse production position")
        try:
            qty = float(pos)
        except (TypeError, ValueError) as error:
            raise TradingError("Cannot parse production position") from error
        if not math.isfinite(qty):
            raise TradingError("Nonfinite production position")
        if qty:
            ticker = p.get("market_ticker", p.get("ticker"))
            if not ticker or ticker not in tickers:
                raise TradingError("Foreign open production position: HALT")
            maximum = sum(float(a["count"]) for a in attempts if a["ticker"] == ticker)
            if qty > 0 or abs(qty) > maximum + 1e-8:
                raise TradingError(
                    "Production position contradicts owned NO intents: HALT"
                )
            held.append(ticker)
    settlements = client.settlements() if attempts else []
    if not isinstance(settlements, list):
        raise TradingError("Cannot inspect production settlements")
    settled = set()
    for r in settlements:
        ticker = r.get("market_ticker") or r.get("ticker")
        if ticker in tickers:
            settled.add(ticker)
    # A buy can be accepted and disappear from resting before a later GET
    # (canceled, filled, exchange failure). Never free reservation unless
    # settlement is verified. Conservatively keeps it in active exposure.
    still_at_risk = [
        a
        for a in attempts
        if a["ticker"] not in settled and a["client_order_id"] not in rejected
    ]
    return {
        "resting": resting,
        "held": held,
        "settled": settled,
        "settlements": settlements,
        "active": still_at_risk,
    }


def reconcile_expired_unfilled(attempts, accepted, state, fills, now, events=()):
    """Release *active* capacity only on robust evidence of zero execution.

    Full historical attempt cost still counts toward the lifetime and daily
    gross-spend caps. Also release VERIFIED zero-fill cancellations on the
    following signed exchange snapshot; the acknowledgment alone is NOT
    sufficient and no filled or unreconciled orders are recycled.
    """
    still_active = []
    resting_ids = {str(o.get("order_id")) for o in state["resting"]}
    held_tickers = set(state["held"])
    filled_ids = {str(f.get("order_id")) for f in fills if f.get("order_id")}
    filled_tickers = {
        str(f.get("ticker") or f.get("market_ticker"))
        for f in fills
        if f.get("ticker") or f.get("market_ticker")
    }
    canceled_ids = {
        str(e.get("order_id"))
        for e in events
        if e.get("event") == "cancel_accepted" and e.get("order_id")
    }
    # State and fills must both be fresh signed exchange reads; this function
    # NEVER treats a cancel_ack itself as proof of zero execution.
    from datetime import timedelta

    released = 0
    rejected = state.get("rejected_client_ids", set())
    for attempt in attempts:
        if attempt["client_order_id"] in rejected:
            continue
        ticker = attempt["ticker"]
        if ticker in state["settled"]:
            continue
        match = accepted.get(attempt["client_order_id"])
        if not match:
            raise TradingError("Unaccepted attempt: HALT")
        oid = str(match["order_id"])
        tip = (
            pd.Timestamp(attempt["expiration_ts"], unit="s", tz="UTC")
            if attempt.get("expiration_ts") is not None
            else pd.Timestamp(attempt["tip_utc"])
        )
        # Legacy expiry still waits 10m; explicit owned cancellations may
        # recycle ACTIVE capacity after a second, authenticated snapshot.
        # Canceled/expired attempts continue counting toward all daily and
        # lifetime SUBMISSION limits.
        past_safe_expiry = pd.notna(tip) and now >= tip.to_pydatetime() + timedelta(
            minutes=10
        )
        cancel_verified = oid in canceled_ids
        can_release = (
            (past_safe_expiry or cancel_verified)
            and oid not in resting_ids
            and oid not in filled_ids
            and ticker not in filled_tickers
            and ticker not in held_tickers
        )
        if can_release:
            released += 1
        else:
            still_active.append(attempt)
    return still_active, released


def nba_realized_pnl(settlements, owned_tickers, now):
    """Read-only settlement P&L guard. Never infer profit from unfilled orders.

    Exchange outcomes must have complete unit-normalized accounting and
    timestamp; duplicate pages cannot inflate or erase a stop. Checks
    apply only to NBA cohort-owned markets; shared submission caps stay.
    """
    from zoneinfo import ZoneInfo

    if not isinstance(settlements, list):
        raise TradingError("Unverified NBA settlement ledger: HALT")
    local_today = now.astimezone(ZoneInfo("America/New_York")).date()
    seen = {}
    daily = cumulative = 0.0
    for item in settlements:
        if not isinstance(item, dict):
            raise TradingError("Malformed NBA settlement: HALT")
        ticker = item.get("market_ticker") or item.get("ticker")
        if ticker not in owned_tickers:
            continue
        accounted = settlement_accounting(item)
        amount = accounted.get("net_profit_dollars")
        try:
            when = pd.Timestamp(item["settled_time"])
        except (ValueError, TypeError, KeyError) as error:
            raise TradingError("Undated NBA settlement: HALT") from error
        if (
            not accounted["accounting_complete"]
            or amount is None
            or not math.isfinite(float(amount))
            or pd.isna(when)
            or when.tzinfo is None
            or when > pd.Timestamp(now) + pd.Timedelta(minutes=5)
        ):
            raise TradingError("Incomplete or future NBA settlement: HALT")
        key = (str(ticker), when.isoformat())
        if key in seen:
            if seen[key] != accounted:
                raise TradingError("Conflicting NBA settlement copies: HALT")
            continue
        seen[key] = accounted
        cumulative += float(amount)
        if when.tz_convert("America/New_York").date() == local_today:
            daily += float(amount)
    return {
        "daily_realized_pnl_dollars": round(daily, 4),
        "cumulative_realized_pnl_dollars": round(cumulative, 4),
        "settlement_records": len(seen),
        "loss_stop": (
            daily <= -MAX_REALIZED_DAILY_LOSS + 1e-9
            or cumulative <= -MAX_REALIZED_CUMULATIVE_LOSS + 1e-9
        ),
    }


def resting_cancel_reason(row, intent, market, fee_bound):
    """Fail closed on stale/changed probability, fee, maker price or availability.

    Evaluate the ORIGINAL resting NO price, not the latest hypothetical maker
    quote. An order only remains valid if its expected net return still clears
    the minimum. Input freshness/roster/injury vetos were applied by
    nba_candidates before this point.
    """
    if row is None or str(row.get("injury_status") or ""):
        return "unverified_roster_injury_or_model"
    try:
        hours = float(row["hours_to_tip"])
        if (
            not math.isfinite(hours)
            or not RESTING_WINDOW[0] < hours <= RESTING_WINDOW[1]
        ):
            return "outside_verified_pretip_window"

        cents = int(intent["price_cents"])
        count = int(intent["count"])
        low, high = PRICE_BAND_CENTS
        if not low <= cents <= high or not 0 < count <= MAX_CONTRACTS:
            return "invalid_original_order"
        no_price = cents / 100

        source = str(intent["probability_source"])
        if source not in {"sportsbook", "model"}:
            return "unverified_original_probability_source"
        raw_book_n = float(row.get("book_n", 0))
        book_n = raw_book_n if math.isfinite(raw_book_n) else 0
        p_book = float(row.get("p_book", float("nan")))
        required = str(row.get("requires_book", "")).lower()
        if required not in {"true", "false", "1", "0"}:
            return "unverified_book_requirement"
        has_books = book_n >= 2 and math.isfinite(p_book) and 0 <= p_book <= 1
        # Never degrade an originally sportsbook-confirmed signal to a
        # model-only signal; opening-week/role-change veto remains binding.
        if (source == "sportsbook" or required in {"true", "1"}) and not has_books:
            return "fresh_two_book_consensus_missing"
        p_yes = p_book if has_books else float(row["p_model"])
        if not math.isfinite(p_yes) or not 0 <= p_yes <= 1:
            return "unverified_current_probability"

        if not isinstance(market, dict) or market.get("status") not in {
            "active",
            "open",
        }:
            return "market_not_active"
        bid = float(market["yes_bid_dollars"])
        ask = float(market["yes_ask_dollars"])
        if not all(math.isfinite(v) for v in (bid, ask)) or not 0 < bid < ask < 1:
            return "invalid_fresh_exchange_book"
        # A resting NO buy is a YES ask. If now marketable, cancel any
        # still-resting remainder rather than relying on a stale passive quote.
        if round(1 - no_price, 2) <= round(bid, 2):
            return "resting_quote_no_longer_passive"
        if not isinstance(fee_bound, (float, int)) or not math.isfinite(fee_bound):
            return "unknown_current_fees"
        if (
            fee_bound < 0
            or count * no_price + fee_bound > reserve(count * no_price) + 1e-9
        ):
            return "fee_exceeds_original_reservation"
        net_edge = 1 - p_yes - no_price - fee_bound / count
        if not math.isfinite(net_edge) or net_edge < RESTING_MIN_NET_EDGE - 1e-9:
            return "current_net_edge_below_minimum"
    except (KeyError, ValueError, TypeError, OverflowError):
        return "unverifiable_resting_order_or_market_data"
    return None


# A failed input pipeline (projections, injuries, rosters or quotes) yields an
# empty, "blocked" frame. Resting orders are held through a short outage
# instead of being cancelled en masse (a cancelled ticker can never be
# re-ordered); new orders stay blocked. If good inputs have not been seen for
# longer than this, the resting orders are cancelled as before (fail closed).
INPUT_OUTAGE_HOLD_MINUTES = 15


# Network/transport failures only. Data-integrity failures (malformed,
# undated or future injury records, duplicate tickers, row-count or hash
# mismatches, no priced markets) still cancel resting orders immediately.
TRANSIENT_INPUT_ERRORS = frozenset(
    {
        "URLError",
        "HTTPError",
        "TimeoutError",
        "timeout",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "ConnectionAbortedError",
        "RemoteDisconnected",
        "IncompleteRead",
        "SSLError",
        "gaierror",
    }
)


def inputs_unavailable(frame):
    """True only when an input feed failed in transit (a connection hiccup)."""
    blocked = frame.attrs.get("diagnostics", {}).get("blocked")
    return frame.empty and blocked in TRANSIENT_INPUT_ERRORS


def note_good_inputs(directory, now):
    from live.nba_inputs import atomic_write

    atomic_write(
        directory / "last_good_inputs.json",
        (json.dumps({"utc": now.isoformat()}) + "\n").encode(),
    )


def minutes_since_good_inputs(directory, now):
    try:
        stamp = pd.Timestamp(
            json.loads((directory / "last_good_inputs.json").read_text())["utc"]
        )
        minutes = (pd.Timestamp(now) - stamp).total_seconds() / 60
    except (OSError, ValueError, KeyError, TypeError):
        return math.inf
    return minutes if math.isfinite(minutes) and minutes >= 0 else math.inf


def cancel_invalid_resting(client, journal, state, frame, now, events):
    """Cancel owned resting orders when fresh checks invalidate original quotes.

    GET or fee-service failures stop the pass; exchange-side order expiration
    remains as a hard safety limit. Never manufacture successful cancellations.
    """
    from kalshi.fees import live_maker_fee_bound

    fee_cache = {}  # series/event metadata, reused within this re-check
    accepted_by_id = {
        str(event["order_id"]): str(event["client_order_id"])
        for event in events
        if event.get("event") == "accepted"
        and event.get("order_id")
        and event.get("client_order_id")
    }
    intents_by_client = {
        str(event["client_order_id"]): event
        for event in events
        if event.get("event") == "intent" and event.get("client_order_id")
    }
    if frame.empty:
        current = {}
    else:
        if frame.ticker.duplicated().any():
            raise TradingError("Duplicate NBA tickers in resting recheck: HALT")
        current = {str(t): row for t, row in frame.set_index("ticker").iterrows()}
    canceled = 0
    for resting in state["resting"]:
        order_id = str(resting.get("order_id") or "")
        ticker = str(resting.get("ticker") or "")
        intent = intents_by_client.get(accepted_by_id.get(order_id))
        if (
            not order_id
            or not ticker
            or intent is None
            or intent.get("ticker") != ticker
        ):
            raise TradingError("Cannot reconcile owned resting order: HALT")

        row = current.get(ticker)
        if row is None or str(row.get("injury_status") or ""):
            reason = "unverified_roster_injury_or_model"
        else:
            try:
                market = fetch_market(ticker)
                cents, count = int(intent["price_cents"]), int(intent["count"])
                fee_bound, _ = live_maker_fee_bound(
                    ticker, cents / 100, count, fee_cache
                )
            except Exception as error:
                raise TradingError(
                    "Fresh resting quote/fee read failed; HALT new placements"
                ) from error
            reason = resting_cancel_reason(row, intent, market, fee_bound)
        if reason is None:
            continue
        write_event(
            journal,
            {
                "event": "cancel_intent",
                "utc": now.isoformat(),
                "order_id": order_id,
                "ticker": ticker,
                "reason": reason,
                # Which check vetoed the market (ESPN, official report, ...).
                "veto": str(row.get("injury_status") or "") if row is not None else "",
                "strategy_version": STRATEGY_VERSION,
            },
        )
        try:
            client.cancel(order_id, ticker=ticker)
        except Exception as error:
            raise TradingError(
                "Cannot confirm cancellation; HALT and inspect Kalshi orders"
            ) from error
        write_event(
            journal,
            {
                "event": "cancel_accepted",
                "utc": datetime.now(UTC).isoformat(),
                "order_id": order_id,
                "reason": reason,
            },
        )
        canceled += 1
    return canceled


def cancel_owned_on_kill(client, journal):
    """Emergency stop: only cancel orders provably from this pilot journal."""
    events = load_journal(journal)
    ids = {e["order_id"] for e in events if e.get("event") == "accepted"}
    client_ids = {e["client_order_id"] for e in events if e.get("event") == "intent"}
    canceled = 0
    for item in client.orders("resting"):
        if (
            item.get("order_id") not in ids
            and item.get("client_order_id") not in client_ids
        ):
            continue
        oid, ticker = item.get("order_id"), item.get("ticker")
        if not oid or not ticker:
            raise TradingError("Emergency cancellation cannot route: inspect Kalshi")
        client.cancel(oid, ticker=ticker)
        write_event(
            journal,
            {
                "event": "emergency_cancel",
                "utc": datetime.now(UTC).isoformat(),
                "order_id": oid,
                "ticker": ticker,
            },
        )
        canceled += 1
    print(f"PROD AUTO HALTED: canceled {canceled} owned resting orders")
    return canceled


def record_execution(journal, events, attempts, accepted, fills, settlements):
    """Store distinct actual fills and exchange settlement amounts for audit."""
    known_orders = {e["order_id"] for e in accepted.values()}
    tickers = {a["ticker"] for a in attempts}
    seen_fills = {e.get("fill_id") for e in events if e.get("event") == "fill"}
    seen_results = {
        e.get("ticker"): e for e in events if e.get("event") == "settlement"
    }
    for fill in fills:
        oid = fill.get("order_id")
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid or fid in seen_fills or oid not in known_orders:
            continue
        write_event(
            journal,
            {
                "event": "fill",
                "fill_id": str(fid),
                "utc": str(fill.get("created_time", "")),
                "ticker": str(fill.get("ticker") or fill.get("market_ticker") or ""),
                "order_id": str(oid),
                "count": str(fill.get("count_fp", "")),
                "yes_price": str(fill.get("yes_price_dollars", "")),
                "no_price": str(fill.get("no_price_dollars", "")),
                "fee": str(fill.get("fee_cost", "")),
                "is_taker": fill.get("is_taker"),
            },
        )
        seen_fills.add(fid)
    for result in settlements:
        ticker = result.get("market_ticker") or result.get("ticker")
        if ticker not in tickers:
            continue
        record = {
            "event": "settlement",
            "ticker": ticker,
            "utc": str(result.get("settled_time", "")),
            **settlement_accounting(result),
        }
        # Append a correction for older/incomplete records; never rewrite history.
        if record != seen_results.get(ticker):
            write_event(journal, record)
            seen_results[ticker] = record


def record_queue_observation(client, journal, order_id, now):
    """Read an owned order's queue without allowing a telemetry error to trade."""
    try:
        queue = client.queue_position(str(order_id))
        if queue is not None and (not math.isfinite(queue) or queue < 0):
            queue = None
        issue = None if queue is not None else "missing_or_invalid_queue_field"
    except Exception as error:
        import re

        match = re.search(r"-> HTTP ([0-9]{3})", str(error))
        queue = None
        issue = f"HTTP_{match.group(1)}" if match else type(error).__name__
    write_event(
        journal,
        {
            "event": "queue",
            "utc": now.isoformat(),
            "order_id": str(order_id),
            "ahead": queue,
            "issue": issue,
        },
    )


def record_markouts(journal, frame, now):
    """Observed NO-price movement after actual fills; never invent missed quotes."""
    events = load_journal(journal)
    seen = {
        (e.get("fill_id"), e.get("horizon_minutes"))
        for e in events
        if e.get("event") == "markout"
    }
    quotes = (
        frame.drop_duplicates("ticker").set_index("ticker")
        if not frame.empty
        else pd.DataFrame()
    )
    for fill in (e for e in events if e.get("event") == "fill"):
        try:
            age = (pd.Timestamp(now) - pd.Timestamp(fill["utc"])).total_seconds()
            entry = float(fill["no_price"])
            if not math.isfinite(entry) or not 0 < entry < 1:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        for horizon in (5, 15, 60):
            if (fill["fill_id"], horizon) in seen or age < horizon * 60:
                continue
            observation = {
                "event": "markout",
                "fill_id": fill["fill_id"],
                "ticker": fill["ticker"],
                "utc": now.isoformat(),
                "horizon_minutes": horizon,
                "observed_after_seconds": age,
                "mid_move_dollars": None,
                "bid_move_dollars": None,
                "fees_included": False,
            }
            if age > horizon * 60 + 600:
                observation["issue"] = "missed_observation_window"
            elif fill["ticker"] not in quotes.index:
                observation["issue"] = "quote_unavailable"
            else:
                quote = quotes.loc[fill["ticker"]]
                bid, ask = float(quote.yes_bid_dollars), float(quote.yes_ask_dollars)
                if not 0 < bid < ask < 1:
                    observation["issue"] = "invalid_quote"
                else:
                    observation.update(
                        mid_move_dollars=round(1 - (bid + ask) / 2 - entry, 6),
                        bid_move_dollars=round(1 - ask - entry, 6),
                        issue=None,
                    )
            write_event(journal, observation)


# Optional second cent of improvement in >=3c spreads (only if after-fee edge
# stays >=3c and the quote stays post-only). Off: it lost money in replay, so
# execution_quote always returns the baseline quote; its 3c/90c checks only
# apply if this is ever switched back on.
EXTRA_MAKER_TICK = 0.0  # historical baseline already improves one tick
MIN_EDGE_AFTER_IMPROVEMENT = 0.03
# New entries and resting orders use the SAME after-fee edge floor, so an
# order is never placed on terms that the next scan would cancel it for. v5
# accepts any non-negative edge (v4 required 3c); the 15c outlier cap stays.
ENTRY_MIN_NET_EDGE = 0.0
RESTING_MIN_NET_EDGE = ENTRY_MIN_NET_EDGE


def execution_quote(candidate):
    """Choose a better maker quote only if the existing book/model edge covers it.

    candidate.edge already includes estimated maker fees, and where available
    uses sportsbook probability rather than model-only probability. Preserve
    at least three percentage points of that estimated edge after improving.
    """
    base = float(candidate.price)
    original_edge = float(candidate.edge)
    bid, ask = float(candidate.yes_bid), float(candidate.yes_ask)
    if not all(math.isfinite(v) for v in (base, original_edge, bid, ask)):
        raise TradingError("Nonfinite execution quote")
    if not 0 < bid < ask < 1:
        raise TradingError("Invalid execution market spread")
    spread_cents = round((ask - bid) * 100)
    if abs(spread_cents - (ask - bid) * 100) > 0.0001:
        raise TradingError("Non-cent price spread in maker experiment")
    # Baseline is already inside 2c+ spreads by one tick.
    # A second tick must never reach/cross the opposing YES bid.
    proposed = round(base + EXTRA_MAKER_TICK, 2)
    remaining_edge = round(original_edge - EXTRA_MAKER_TICK, 5)
    take_second_tick = (
        EXTRA_MAKER_TICK > 0
        and spread_cents >= 3
        and remaining_edge >= MIN_EDGE_AFTER_IMPROVEMENT
        and proposed <= 0.90
        and round(1 - proposed, 2) > round(bid, 2)
    )
    return (
        proposed if take_second_tick else base,
        remaining_edge if take_second_tick else original_edge,
        int(take_second_tick),
    )


def verify_quote(candidate, proposed_no_price=None):
    """Re-read production quote and ensure selected maker price is still passive."""
    market = fetch_market(str(candidate.ticker))
    if not market or market.get("status") not in {"active", "open"}:
        raise TradingError("Selected market no longer active")
    try:
        bid = float(market["yes_bid_dollars"])
        ask = float(market["yes_ask_dollars"])
    except (KeyError, TypeError, ValueError) as err:
        raise TradingError("Production quote fields missing") from err
    if not all(math.isfinite(x) for x in (bid, ask)):
        raise TradingError("Nonfinite production quote")
    if not 0 < bid < ask < 1:
        raise TradingError("Production market is not truly two-sided")
    no_bid = 1 - ask
    expected = round(no_bid + (0.01 if ask - bid >= 0.019999 else 0), 2)
    if abs(expected - float(candidate.price)) > 0.001:
        raise TradingError("Price moved since model snapshot; wait for next pass")
    price = (
        float(candidate.price)
        if proposed_no_price is None
        else float(proposed_no_price)
    )
    if price < expected - 0.001 or price > expected + EXTRA_MAKER_TICK + 0.001:
        raise TradingError("Proposed NO price does not match verified snapshot")
    # A buy NO is a sell YES ask at 1 - price. Resting order must be priced
    # strictly above the YES bid to stay maker-only.
    if round(1 - price, 2) <= round(bid, 2):
        raise TradingError("Proposed maker quote would cross the YES bid")


def select_candidates(frame, events, state, now, diagnostics=None, window=WINDOW):
    """Return executable signals and record where candidate opportunities die.

    Stage counts are private aggregate telemetry; they do not authorize
    an order and never relax the frozen production entry policy.
    """
    counts = diagnostics if diagnostics is not None else {}
    counts["open_markets"] = len(frame)
    if frame.empty:
        return []
    attempts, _ = records(events)
    verified = frame[frame.injury_status.fillna("").eq("") & frame.tip_utc.notna()]
    counts["verified_availability_and_tip"] = len(verified)
    in_window = verified[verified.hours_to_tip.between(*window)]
    counts["in_entry_window"] = len(in_window)
    eligible = in_window[
        in_window.ticker.astype(str).str.startswith(
            ("KXNBAPTS-", "KXNBAREB-", "KXNBAAST-", "KXNBA3PT-")
        )
    ]
    counts["supported_prop_series"] = len(eligible)
    if eligible.empty:
        return []
    found = candidate_orders(eligible, "no_seller_bookline", window=window)
    counts["passed_book_model_and_spread"] = len(found)
    if found.empty:
        return []
    found = found[found.side.eq("no")].copy()
    counts["no_side_candidates"] = len(found)
    found["edge"] = pd.to_numeric(found.edge, errors="coerce")
    # Large apparent edges often imply a wrong line or stale book.
    found = found[found.edge.between(0, 0.15)]
    counts["passed_edge_sanity"] = len(found)
    already = {a["ticker"] for a in attempts}
    found = found[~found.ticker.isin(already)]
    counts["not_previously_attempted"] = len(found)
    if found.empty:
        return []
    return list(found.sort_values("edge", ascending=False).itertuples())


def order_from_row(row, now, no_price=None):
    price = float(row.price) if no_price is None else float(no_price)
    if not math.isfinite(price):
        raise TradingError("Nonfinite order price")
    cents = round(price * 100)
    if not math.isfinite(price) or abs(cents - price * 100) > 1e-6:
        raise TradingError("Order price not a whole cent")
    low, high = PRICE_BAND_CENTS
    if not low <= cents <= high:
        raise TradingError(f"Order price outside safe {low}c–{high}c range")
    count = MAX_CONTRACTS
    while count > 0 and reserve(round(count * price, 2)) > MAX_ORDER_COST:
        count -= 1
    if count <= 0:
        raise TradingError("Zero affordable contracts")
    tip = pd.Timestamp(row.tip_utc)
    if pd.isna(tip) or int(tip.timestamp()) < int(now.timestamp()) + 2 * 3600:
        raise TradingError("Too close to kickoff")
    cost = round(count * cents / 100, 2)
    order = Order(
        ticker=str(row.ticker),
        side="no",
        count=count,
        price_cents=cents,
        # Existing orders rest until *scheduled tip* unless a verified
        # injury, roster, probability, market or fee change cancels earlier.
        # Exchange-side expiry still works even if the bot is offline.
        expiration_ts=int(tip.timestamp()),
        post_only=True,
    )
    return order, cost


def pre_submit_kickoff_ok(tip_utc, now):
    """Fail closed on the wall clock, not the earlier two-minute scan start.

    The 30-second buffer enforces the NBA baseline 2-hour minimum at POST,
    even if the model/market scan has been running for several minutes.
    """
    from datetime import timedelta

    tip = pd.Timestamp(tip_utc)
    if pd.isna(tip):
        return False
    try:
        return tip.to_pydatetime() > now + timedelta(hours=2, seconds=30)
    except (TypeError, ValueError):
        return False


def budget_blockers(
    attempts, active, row, cost, now, shared=None, rejected=frozenset()
):
    """Explain every binding risk cap; never weaken the underlying admission.

    Daily/lifetime limits count all attempts, including zero-fill expiries.
    Game/team caps use accepted attempts, including later cancellations.
    """
    today = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    total = sum(reserve(a["cost"]) for a in attempts)
    open_now = sum(reserve(a["cost"]) for a in active)
    # An exchange-confirmed rejected submission never became a position.
    # Preserve it in lifetime/daily spend but not game/team slots.
    accepted_attempts = [
        a for a in attempts if a.get("client_order_id") not in rejected
    ]
    game_cost = sum(
        reserve(a["cost"])
        for a in accepted_attempts
        if a["game_id"] == str(row.game_id)
    )
    team_cost = sum(
        reserve(a["cost"])
        for a in accepted_attempts
        if a["team"] == str(row.team)
        and datetime.fromisoformat(a["utc"])
        .astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
        .date()
        == today
    )
    game_orders = sum(a["game_id"] == str(row.game_id) for a in accepted_attempts)
    day_cost = sum(
        reserve(a["cost"])
        for a in attempts
        if datetime.fromisoformat(a["utc"])
        .astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
        .date()
        == today
    )
    r = reserve(cost)
    from live.shared_account_risk import fits

    reasons = []
    if shared is not None and not fits(shared, cost, now):
        reasons.append("shared_account_cap")
    if total + r > MAX_GROSS_COST + 1e-9:
        reasons.append("nba_lifetime_submissions")
    if open_now + r > MAX_ACTIVE_COST + 1e-9:
        reasons.append("nba_active_exposure")
    if game_cost + r > MAX_GAME_COST + 1e-9:
        reasons.append("nba_per_game_submissions")
    if team_cost + r > MAX_TEAM_COST + 1e-9:
        reasons.append("nba_per_team_submissions")
    if day_cost + r > MAX_DAILY_COST + 1e-9:
        reasons.append("nba_daily_submissions")
    if game_orders >= MAX_GAME_ORDERS:
        reasons.append("nba_game_order_count")
    return reasons


def room_for(attempts, active, row, cost, now, shared=None, rejected=frozenset()):
    return not budget_blockers(
        attempts, active, row, cost, now, shared=shared, rejected=rejected
    )


def legacy_resting_count(attempts, accepted, resting):
    """Count verified prior-version resting orders without changing them.

    Each prior version's own exchange-side expiry remains the safety boundary
    for its already-accepted orders. Any unowned or unknown-version order
    still HALTs.
    """
    intents = {str(a["client_order_id"]): a for a in attempts}
    count = 0
    for order in resting:
        order_id = str(order.get("order_id") or "")
        ticker = str(order.get("ticker") or "")
        owner = [
            intents.get(str(cid))
            for cid, record in accepted.items()
            if str(record.get("order_id")) == order_id
        ]
        if not order_id or not ticker or len(owner) != 1 or owner[0] is None:
            raise TradingError("Unowned NBA resting order: HALT")
        intent = owner[0]
        if str(intent.get("ticker")) != ticker:
            raise TradingError("Resting NBA order/ticker mismatch: HALT")
        version = intent.get("strategy_version")
        if version in PRIOR_VERSIONS:
            count += 1
        elif version != STRATEGY_VERSION:
            raise TradingError("Unknown NBA resting order version: HALT")
    return count


def late_context_diagnostics(frame, candidates):
    """Measure truly corroborated late signals without authorizing a POST.

    An independent, licensed minutes projection and an explicitly confirmed
    starter status are distinct inputs. A historical playing-time baseline,
    predicted lineup, or incomplete vendor snapshot never counts as verified.
    These counts are diagnostic; late entries remain shadow-only.
    """
    by_ticker = (
        frame.set_index("ticker") if not frame.empty and "ticker" in frame else None
    )
    counts = {
        "shadow_candidates": len(candidates),
        "licensed_projected_minutes": 0,
        "confirmed_starting_five": 0,
        "both_verified": 0,
        "execution_enabled": False,
    }
    if by_ticker is None:
        return counts
    for candidate in candidates:
        ticker = str(candidate.ticker)
        if ticker not in by_ticker.index:
            continue
        row = by_ticker.loc[ticker]
        minutes = pd.to_numeric(
            pd.Series([row.get("projected_minutes")]), errors="coerce"
        ).iloc[0]
        verified_minutes = (
            row.get("projected_minutes_source") == "rotowire_licensed"
            and pd.notna(minutes)
            and 8 <= float(minutes) <= 48
        )
        confirmed = row.get("lineup_confirmation_status") == "confirmed" and isinstance(
            row.get("confirmed_starter"), (bool, np.bool_)
        )
        counts["licensed_projected_minutes"] += int(verified_minutes)
        counts["confirmed_starting_five"] += int(confirmed)
        counts["both_verified"] += int(verified_minutes and confirmed)
    return counts


def entry_evidence(row):
    """Point-in-time *observation* provenance for future exchange-accepted orders.

    Preserve missing evidence as null, never treat historical minutes as a
    licensed game-specific projection or an expected lineup as confirmed.
    This data is PRIVATE (journal only) and cannot authorize extra orders.
    """

    def number(value):
        try:
            result = float(value)
            return round(result, 6) if math.isfinite(result) else None
        except (ValueError, TypeError, OverflowError):
            return None

    def stamp(name):
        value = getattr(row, name, None)
        if value is None or pd.isna(value):
            return None
        dt = pd.to_datetime(value, utc=True, errors="coerce")
        return dt.isoformat() if pd.notna(dt) else None

    source = str(getattr(row, "projected_minutes_source", "unverified"))
    projected = number(getattr(row, "projected_minutes", None))
    verified_projection = (
        source == "rotowire_licensed" and projected is not None and 8 <= projected <= 48
    )
    lineup = str(getattr(row, "lineup_confirmation_status", "unverified"))
    starter = getattr(row, "confirmed_starter", None)
    starter = (
        bool(starter)
        if (lineup == "confirmed" and isinstance(starter, (bool, np.bool_)))
        else None
    )
    return {
        "projected_minutes_at_entry": projected if verified_projection else None,
        "projected_minutes_source_at_entry": source
        if verified_projection
        else "unverified",
        "historical_minutes_baseline_at_entry": number(
            getattr(row, "historical_minutes_baseline", None)
        ),
        "internal_minutes_forecast_at_entry": number(
            getattr(row, "minutes_forecast_internal", None)
        ),
        "lineup_confirmation_status_at_entry": "confirmed"
        if lineup == "confirmed" and starter is not None
        else "unverified",
        "confirmed_starter_at_entry": starter,
        "vendor_context_fetch_utc_at_entry": stamp("pregame_context_fetch_utc"),
        "book_updated_utc_at_entry": stamp("book_updated_utc"),
        "book_game_tip_utc_at_entry": stamp("book_commence_utc"),
        "model_probability_yes_at_entry": number(getattr(row, "p_model", None)),
        "sportsbook_probability_yes_at_entry": number(getattr(row, "p_book", None)),
        "kalshi_yes_bid_at_entry": number(getattr(row, "yes_bid", None)),
        "kalshi_yes_ask_at_entry": number(getattr(row, "yes_ask", None)),
    }


def pass_once(client, env, frame, now, journal, *, dry=False):
    from collections import Counter
    from live.nba_inputs import atomic_write
    from kalshi.fees import live_maker_fee_bound

    skipped = Counter()
    funnel = {}
    placed_this_pass = 0
    fee_cache = {}  # series/event fee metadata, reused within this pass
    seen_tickers = set()

    def finish(decision, placed=False):
        report = {
            "utc": datetime.now(UTC).isoformat(),
            "strategy_version": STRATEGY_VERSION,
            "decision": decision,
            "placed": placed,
            "orders_placed_this_pass": placed_this_pass,
            "pass_seconds": round(elapsed_seconds(), 1),
            "legacy_prior_version_resting_orders": legacy_resting,
            "candidate_count": len(candidates),
            "selection_funnel": dict(funnel),
            "late_window_shadow": {
                **late_context_diagnostics(frame, late_shadow_candidates),
                "candidate_count": len(late_shadow_candidates),
                "selection_funnel": dict(late_funnel),
                "execution_enabled": False,
                "note": "Research only. No order placement or late risk allocation.",
            },
            "resting_order_count": len(state.get("resting", [])),
            "verified_zero_fill_expiries_this_scan": released,
            "realized_pnl_stop": realized_pnl,
            "quote_research": research_quotes,
            "skipped": dict(skipped),
            "inputs": frame.attrs.get("diagnostics", {}),
            "attempts": len(attempts),
            "gross_reserved": sum(reserve(a["cost"]) for a in attempts),
        }
        # A read-only dry scan must NEVER replace the last live scan report.
        if not dry:
            atomic_write(
                journal.parent / "last_scan.json",
                (json.dumps(report, indent=2) + "\n").encode(),
            )
        print("NBA DECISION:", decision, dict(skipped), flush=True)
        return placed

    if not dry:
        guard(env, client)
    events = load_journal(journal)
    attempts, accepted = records(events)
    rejected = rejected_client_ids(events)
    shared = None
    legacy_resting = 0
    released = 0
    realized_pnl = {"status": "not_evaluated_in_dry_mode"}
    if not dry:
        from live.shared_account_risk import dual_mode, state_for

        if dual_mode(env):
            state, shared = state_for(client, "nba", now)
        else:
            state = current_production_state(client, attempts, accepted, rejected)
        state["rejected_client_ids"] = rejected
        legacy_resting = legacy_resting_count(attempts, accepted, state["resting"])
        free = money(client.balance()["balance"])
    else:
        state = {"active": []}
    candidates = select_candidates(frame, events, state, now, diagnostics=funnel)
    # Observe the historically promising 30m-2h window without changing
    # exchange risk. A confirmed lineup source is NOT available in this
    # pipeline, so these candidates must never enter the live POST loop.
    late_funnel = {}
    late_shadow_candidates = select_candidates(
        frame, events, state, now, diagnostics=late_funnel, window=(0.5, 2.0)
    )
    from live.quote_shadow import shadow_quotes

    research_quotes = [
        {"ticker": str(row.ticker), **shadow_quotes(row)} for row in candidates[:5]
    ]
    if not dry:
        min_ts = (
            int(datetime.fromisoformat(attempts[0]["utc"]).timestamp()) - 60
            if attempts
            else int(now.timestamp()) - 60
        )
        # Capture fill data or halt on read failure (do not silently use zero).
        fills = client.fills(min_ts=min_ts)
        if not isinstance(fills, list):
            raise TradingError("Cannot read production fills")
        owned_ids = {str(a["order_id"]) for a in accepted.values()}
        owned_tickers = {a["ticker"] for a in attempts}
        if any(
            (f.get("ticker") or f.get("market_ticker")) in owned_tickers
            and str(f.get("order_id")) not in owned_ids
            for f in fills
        ):
            raise TradingError("Foreign fill in an owned NBA market: HALT")
        active, released = reconcile_expired_unfilled(
            attempts, accepted, state, fills, now, events=events
        )
        state["active"] = active
        if released:
            print(
                f"PROD AUTO: {released} verified unfilled expired orders freed from active capacity"
            )
        record_execution(
            journal,
            load_journal(journal),
            attempts,
            accepted,
            fills,
            state["settlements"],
        )
        last_queue = last_queue_times(events)
        for resting in state["resting"]:
            if queue_observation_due(last_queue, str(resting["order_id"]), now):
                record_queue_observation(client, journal, resting["order_id"], now)
        record_markouts(journal, frame, now)
        if legacy_resting:
            # Never alter a previously submitted prior-version order or mix
            # its risk policy with the current one. Still reconcile signed
            # fills and publish a successful scan. When exchange-confirmed
            # resting drops to zero, the next scan starts the current version.
            print(
                f"NBA TRANSITION: waiting for {legacy_resting} prior-version "
                "resting NBA order(s) to close; no new orders"
            )
            return finish("waiting_for_prior_version_orders")
        if inputs_unavailable(frame):
            outage = minutes_since_good_inputs(journal.parent, now)
            if outage <= INPUT_OUTAGE_HOLD_MINUTES:
                print(
                    f"NBA INPUTS UNAVAILABLE for {outage:.1f} min: holding "
                    f"{len(state['resting'])} resting order(s); no new orders"
                )
                return finish("inputs_unavailable_holding_resting")
            print(
                "NBA INPUTS UNAVAILABLE beyond the hold window: "
                "cancelling resting orders (fail closed)"
            )
        elif not frame.empty:
            note_good_inputs(journal.parent, now)
        canceled = cancel_invalid_resting(
            client, journal, state, frame, now, load_journal(journal)
        )
        if canceled:
            print(f"PROD AUTO: canceled {canceled} unsafe resting orders")
            # Require another reconciliation pass after cancellation.
            return finish("unsafe_resting_canceled")
        realized_pnl = nba_realized_pnl(
            state["settlements"], {a["ticker"] for a in attempts}, now
        )
        if realized_pnl["loss_stop"]:
            print("NBA REALIZED LOSS STOP: no additional orders")
            return finish("realized_loss_stop")
        from live.shared_account_risk import account_loss_stop

        if account_loss_stop(shared):
            print("ACCOUNT REALIZED LOSS STOP (NBA + NFL): no additional orders")
            return finish("account_loss_stop")
        print(
            f"PROD AUTO: attempts={len(attempts)}, resting={len(state['resting'])}, "
            f"held={len(state['held'])}, settled_tickers={len(state['settled'])}, "
            f"fills={len(fills)}, gross_reserved=${sum(reserve(a['cost']) for a in attempts):.2f}/${MAX_GROSS_COST:.0f}"
        )
    if not candidates:
        print("No eligible 2-6h NBA opportunities")
        return finish("no_eligible_candidates")
    for row in candidates:
        if placed_this_pass >= MAX_NEW_ORDERS_PER_PASS:
            break
        if elapsed_seconds() > NEW_ORDER_DEADLINE_SECONDS:
            skipped["pass_time_budget"] += 1
            break
        if str(row.ticker) in seen_tickers:
            skipped["duplicate_ticker_in_pass"] += 1
            continue
        seen_tickers.add(str(row.ticker))
        try:
            quoted, execution_edge, extra_ticks = execution_quote(row)
            order, cost = order_from_row(row, now, no_price=quoted)
        except TradingError:
            skipped["invalid_order_or_price"] += 1
            continue
        blockers = []
        while order.count > 0:
            blockers = budget_blockers(
                attempts,
                state["active"],
                row,
                cost,
                now,
                shared=shared,
                rejected=rejected,
            )
            if not blockers:
                break
            order.count -= 1
            cost = round(order.count * order.price_cents / 100, 2)
        if order.count <= 0:
            for reason in blockers or ["unknown_risk_cap"]:
                skipped["risk_" + reason] += 1
            continue
        if not dry and free < reserve(cost):
            skipped["cash_balance"] += 1
            continue
        try:
            fee_bound, fee_metadata = live_maker_fee_bound(
                order.ticker, quoted, order.count, fee_cache
            )
            p_book = float(getattr(row, "p_book", float("nan")))
            p_yes = p_book if math.isfinite(p_book) else float(row.p_model)
            net_edge = 1 - p_yes - quoted - fee_bound / order.count
            if not ENTRY_MIN_NET_EDGE - 1e-9 <= net_edge <= 0.15:
                raise TradingError("nonpositive_or_outlier_net_edge")
            if cost + fee_bound > reserve(cost) + 1e-9:
                raise TradingError("fee_exceeds_reservation")
        except Exception as error:
            skipped[
                str(error) if isinstance(error, TradingError) else "fee_read_failure"
            ] += 1
            continue
        try:
            verify_quote(row, quoted)
        except TradingError:
            skipped["fresh_quote_check"] += 1
            continue
        if dry:
            print(
                "DRY CANDIDATE",
                json.dumps(
                    {
                        "ticker": order.ticker,
                        "side": order.side,
                        "count": order.count,
                        "cost": cost,
                        "price_cents": order.price_cents,
                        "extra_maker_ticks": extra_ticks,
                        "edge_after_quote": round(execution_edge, 4),
                    },
                    sort_keys=True,
                ),
            )
            return finish("read_only_candidate")

        # The candidate scan can take minutes. Check the actual wall clock
        # immediately before the irreversible order intent and network POST,
        # rather than the start of the scan, or late entries can slip through.
        if not pre_submit_kickoff_ok(row.tip_utc, datetime.now(UTC)):
            print(
                f"Skipped {order.ticker}: too close to verified kickoff at submission"
            )
            skipped["entry_window_elapsed"] += 1
            continue

        # Validate the target matching engine and its own collateral before
        # the durable intent. A shard without funding must never create a
        # phantom submission or block the other cohort.
        try:
            order.exchange_index = require_funded_shard(
                client, order.ticker, reserve(cost)
            )
        except TradingError as error:
            if str(error).startswith("SHARD_UNFUNDED_"):
                skipped["exchange_shard_unfunded"] += 1
                return finish("exchange_shard_unfunded", placed=bool(placed_this_pass))
            raise

        # Last check before the irreversible intent: never start an order the
        # systemd timeout could interrupt between intent and acceptance.
        if elapsed_seconds() > NEW_ORDER_DEADLINE_SECONDS:
            skipped["pass_time_budget"] += 1
            break

        # Durable intent first; any failure after this (including a timeout)
        # disables all future automatic orders until manually investigated.
        intent = {
            "event": "intent",
            "utc": now.isoformat(),
            "client_order_id": order.client_order_id,
            "ticker": order.ticker,
            "cost": cost,
            "count": order.count,
            "price_cents": order.price_cents,
            "game_id": str(row.game_id),
            "team": str(row.team),
            "tip_utc": pd.Timestamp(row.tip_utc).isoformat(),
            "edge": round(execution_edge, 4),
            "baseline_edge": round(float(row.edge), 4),
            "extra_maker_ticks": extra_ticks,
            "strategy_version": STRATEGY_VERSION,
            "model_version": MODEL_VERSION,
            "probability_source": "sportsbook" if math.isfinite(p_book) else "model",
            "p_yes": p_yes,
            "book_n": int(getattr(row, "book_n", 0)),
            "fee_bound_dollars": fee_bound,
            "net_edge_after_fee_bound": round(net_edge, 6),
            "model_generated_utc": str(getattr(row, "model_generated_utc", "")),
            "expiration_ts": order.expiration_ts,
            "expiry_policy": "verified_scheduled_tip",
            "quote_checked_utc": datetime.now(UTC).isoformat(),
            **entry_evidence(row),
            **fee_metadata,
        }
        write_event(journal, intent)
        try:
            result = client.place(order)
        except Exception as error:
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
                "Ambiguous production submission. Auto halted until manual audit."
            ) from error
        acceptance = {
            "event": "accepted",
            "utc": datetime.now(UTC).isoformat(),
            "client_order_id": order.client_order_id,
            "order_id": result["order_id"],
        }
        write_event(journal, acceptance)
        # Charge this order to every cap (NBA and account-wide) and to cash
        # before anything else, so the next candidate in this pass sees it.
        charge_new_order(intent, acceptance, attempts, accepted, state, shared)
        free -= reserve(cost)
        placed_this_pass += 1
        print(
            "PROD AUTO ACCEPTED",
            order.ticker,
            "cost",
            cost,
            "order_id",
            result["order_id"],
        )
        try:
            queue = client.queue_position(str(result["order_id"]))
            queue_issue = None if queue is not None else "missing_queue_field"
        except Exception as error:
            # Do not log exception bodies: authenticated API responses can
            # contain sensitive information. Only the category and HTTP code.
            import re

            match = re.search(r"-> HTTP ([0-9]{3})", str(error))
            queue = None
            queue_issue = f"HTTP_{match.group(1)}" if match else type(error).__name__
        write_event(
            journal,
            {
                "event": "queue",
                "utc": datetime.now(UTC).isoformat(),
                "order_id": result["order_id"],
                "ahead": queue,
                "issue": queue_issue,
            },
        )
    if placed_this_pass:
        return finish("accepted", placed=True)
    print("No opportunities fit remaining production risk budget or fresh quotes")
    return finish("all_candidates_blocked")


def charge_new_order(intent, acceptance, attempts, accepted, state, shared):
    """Count a just-accepted order as an attempt, accepted and active.

    Mirrors what the next pass would rebuild from the journal and exchange, so
    every per-game, per-team, daily, lifetime, active and account-wide cap
    sees it immediately. Only ever adds exposure; never frees any.
    """
    attempts.append(intent)
    accepted[intent["client_order_id"]] = acceptance
    state["active"].append(intent)
    if shared is not None:
        owner = shared["ownership"]
        owner["attempts"].append({**intent, "_cohort": "nba"})
        owner["tickers"][intent["ticker"]] = "nba"
        owner["orders"][str(acceptance["order_id"])] = "nba"
        shared["active_client_ids"].add(intent["client_order_id"])


def official_injury_vetoes(frame, model_utc, now, cache_dir=None):
    """Add the official injury report's vetoes to ``frame`` (in place).

    Labels go only on rows not already vetoed, and the boolean column
    ``official_two_books`` marks rows whose team needs a fresh two-book
    consensus tonight. Nothing here clears a veto. If anything goes wrong
    (fetching, reading, matching), nothing is changed: ESPN's checks still
    apply and the returned summary (for last_scan.json) gives the reason. An
    error here must never block the scan, because a blocked scan cancels
    resting orders.
    """
    frame["official_two_books"] = False
    try:
        return _official_injury_vetoes(frame, model_utc, now, cache_dir)
    except Exception as error:
        frame["official_two_books"] = False
        reason = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(f"OFFICIAL INJURY REPORT UNAVAILABLE: {reason} -- ESPN checks only")
        return {"status": "unavailable", "reason": reason}


def _fetch_official(now, model_utc, cache_dir):
    """(latest, baseline, notes) within OFFICIAL_REPORT_SECONDS, hard limit.

    The downloads run in a daemon thread, so a stalled connection or DNS
    lookup cannot stretch the scan. When the newest report cannot be fetched,
    the newest one already on disk is used instead (the age check still
    applies), so vetoes do not flicker off for one bad scan.
    """
    import threading

    from markets.nba import official_injuries as official

    deadline = time.monotonic() + OFFICIAL_REPORT_SECONDS
    box = {}

    def work():
        try:
            box["latest"] = official.report_at(
                now, deadline=deadline, cache_dir=cache_dir
            )
        except Exception as error:
            box["error"] = error
            return
        try:
            box["baseline"] = official.report_at(
                model_utc, deadline=deadline, cache_dir=cache_dir
            )
        except Exception as error:
            box["baseline_error"] = type(error).__name__

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(OFFICIAL_REPORT_SECONDS)
    got = {} if worker.is_alive() else dict(box)
    notes = {}
    if worker.is_alive():
        notes["fetch_error"] = "report_fetch_deadline"
    elif "error" in got:
        error = got["error"]
        notes["fetch_error"] = (
            str(error) if isinstance(error, ValueError) else type(error).__name__
        )
    if "baseline_error" in got:
        notes["baseline_error"] = got["baseline_error"]
    latest, baseline = got.get("latest"), got.get("baseline")
    if latest is None and cache_dir is not None:
        try:
            latest = official.from_cache(now, cache_dir)
            notes["latest_from_cache"] = True
        except official.ReportError:
            latest = None  # report the fetch error, not the empty cache
    if latest is None:
        raise official.ReportError(notes.get("fetch_error", "no_report_found"))
    if baseline is None and cache_dir is not None:
        try:
            baseline = official.from_cache(model_utc, cache_dir)
        except Exception as error:
            notes["baseline_error"] = type(error).__name__
    return latest, baseline, notes


def _official_injury_vetoes(frame, model_utc, now, cache_dir):
    from markets.nba import official_injuries as official
    from markets.nba.kalshi import normalize_name

    if cache_dir is not None:
        official.prune(cache_dir, now)
    (issued, latest), baseline, notes = _fetch_official(now, model_utc, cache_dir)
    age = (pd.Timestamp(now) - pd.Timestamp(issued)).total_seconds() / 60
    if not -5 <= age <= OFFICIAL_REPORT_MAX_AGE_MINUTES:
        raise official.ReportError("report_too_old")
    base_issued, base_rows = baseline if baseline is not None else (None, None)
    dates = frame.tip_utc.dt.tz_convert(official.ET).dt.strftime("%m/%d/%Y")
    games = set(zip(frame.team_espn, dates))
    result = official.assess(
        official.for_games(latest, games),
        None if base_rows is None else official.for_games(base_rows, games),
    )
    names = frame.get("player", pd.Series("", index=frame.index)).fillna("")
    player = pd.Series(
        [
            result["players"].get((t, d, normalize_name(n)), "")
            for t, d, n in zip(frame.team_espn, dates, names)
        ],
        index=frame.index,
    )
    team = pd.Series(
        [result["teams"].get((t, d), "") for t, d in zip(frame.team_espn, dates)],
        index=frame.index,
    )
    label = team.where(team.ne(""), player)
    open_rows = frame.injury_status.fillna("").eq("")
    frame.loc[open_rows & label.ne(""), "injury_status"] = label
    frame["official_two_books"] = [
        (t, d) in result["two_books"] for t, d in zip(frame.team_espn, dates)
    ]
    summary = {
        "status": "ok",
        "issued_et": issued.isoformat(),
        "age_minutes": round(age, 1),
        "rows": len(latest),
        "baseline_issued_et": base_issued.isoformat() if base_issued else None,
        **notes,
        "vetoed_rows": int(label.ne("").sum()),
        "newly_vetoed_rows": int((open_rows & label.ne("")).sum()),
        "team_vetoes": {f"{t} {d}": v for (t, d), v in sorted(result["teams"].items())},
        "two_book_teams": sorted(f"{t} {d}" for t, d in result["two_books"]),
        "changed_players": result["changed_players"],
    }
    print(
        f"OFFICIAL INJURY REPORT: {issued:%I:%M %p} ET, {len(latest)} rows, "
        f"vetoed {summary['vetoed_rows']} markets, team changes "
        f"{sorted(summary['team_vetoes']) or 'none'}"
    )
    return summary


def nba_candidates(now, latest=Path("outputs/projections/latest.csv")):
    """Fail closed unless the dated NBA model, live quotes, and injury feed work.

    The frozen NBA no_seller_bookline rule is unchanged. Quotes are refreshed
    from Kalshi Production; the latest model probabilities are never inferred
    from the market itself. Book lines are attached only if individually fresh.
    """
    from live.nba_trade import refresh_quotes
    from kalshi.books import attach_latest
    from markets.nba.live import injuries

    import io
    from live.nba_inputs import read

    diagnostics = {"model_version": MODEL_VERSION}
    try:
        data, metadata = read(latest.parent, now)
        ts = pd.Timestamp(metadata["generated_utc"])
        age = (pd.Timestamp(now) - ts).total_seconds() / 3600
        diagnostics.update(
            model_generated_utc=metadata["generated_utc"], model_age_hours=age
        )
        frame = pd.read_csv(io.BytesIO(data), low_memory=False)
        if len(frame) != metadata["rows"]:
            raise ValueError("projection_row_count")
        if frame.empty:
            frame.attrs["diagnostics"] = {**diagnostics, "blocked": "no_priced_markets"}
            return frame
        needed = {
            "ticker",
            "tip_utc",
            "game_id",
            "player_id",
            "team",
            "p_model",
            "injury_status",
            "hours_to_tip",
            "team_espn",
            "home_espn",
            "away_espn",
            "requires_book",
            "last_player_game_utc",
            "last_player_team",
        }
        if not needed.issubset(frame.columns):
            raise ValueError("missing NBA projection columns")
        frame["tip_utc"] = pd.to_datetime(frame.tip_utc, utc=True, errors="coerce")
        frame["p_model"] = pd.to_numeric(frame.p_model, errors="coerce")
        frame["hours_to_tip"] = (
            frame.tip_utc - pd.Timestamp(now)
        ).dt.total_seconds() / 3600
        if frame.ticker.duplicated().any():
            raise ValueError("duplicate_projection_ticker")
        frame["injury_status"] = frame.injury_status.fillna("")
        frame["model_generated_utc"] = metadata["generated_utc"]
        from markets.nba.live import rosters, scoreboard

        season = now.year + 1 if now.month >= 8 else now.year
        days = sorted(
            set(
                frame.tip_utc.dropna()
                .dt.tz_convert("America/New_York")
                .dt.strftime("%Y%m%d")
            )
        )
        if len(days) > 3:
            raise ValueError("unexpected_projection_schedule_span")
        schedule = pd.concat(
            [scoreboard(day, season) for day in days], ignore_index=True
        )
        if schedule.game_id.duplicated().any():
            raise ValueError("duplicate_live_game")
        by_game = schedule.set_index("game_id")
        current_rosters = rosters(set(frame.team_espn.dropna()))
        for idx, row in frame.iterrows():
            try:
                game = by_game.loc[int(row.game_id)]
                good = (
                    not game.completed
                    and game.home == row.home_espn
                    and game.away == row.away_espn
                    and abs((game.tip_utc - row.tip_utc).total_seconds()) <= 60
                    and int(row.player_id) in current_rosters[row.team_espn]
                )
            except (KeyError, TypeError, ValueError):
                good = False
            if not good:
                frame.loc[idx, "injury_status"] = "UNVERIFIED_CURRENT_ROSTER_OR_GAME"
        frame.loc[
            ~frame.p_model.between(0, 1) | frame.tip_utc.isna(),
            "injury_status",
        ] = "UNVERIFIED_MODEL_OR_TIP"
        # Check the current injury feed, not only the cached injury column.
        report = injuries()
        from live.nba_availability import explicit_minutes_limit

        if not isinstance(report, pd.DataFrame) or not {
            "player_id",
            "team",
            "updated",
            "out",
        }.issubset(report.columns):
            raise ValueError("current ESPN NBA injuries unavailable")
        if not report.empty:
            players = pd.to_numeric(report.player_id, errors="coerce")
            out = report.out.fillna(False).astype(bool)
            updated = pd.to_datetime(report.updated, utc=True, errors="coerce")
            if players.isna().any() or updated.isna().any():
                raise ValueError("unidentifiable_or_undated_injury")
            if (updated > pd.Timestamp(now) + pd.Timedelta(minutes=5)).any():
                raise ValueError("future_injury_timestamp")
            fresh = updated >= ts
            flagged = set(players[fresh | out].dropna().astype(int))
            frame_ids = pd.to_numeric(frame.player_id, errors="coerce")
            frame.loc[frame_ids.isin(flagged), "injury_status"] = "NEW_INJURY_NEWS"
            # A fresh "probable" update does not mean the entire team has
            # a changed minute distribution. Preserve direct player veto for
            # all fresh news; team-wide veto is for credible role disruption.
            high_risk = out
            if "status" in report:
                status = report.status.fillna("").astype(str).str.lower()
                high_risk = high_risk | status.isin({"out", "doubtful", "questionable"})
            # Historical minutes do not predict newly imposed coach caps.
            limited = (
                report.comment.map(explicit_minutes_limit).fillna(False)
                if "comment" in report
                else pd.Series(False, index=report.index)
            )
            # "Day-To-Day" is ESPN's uncertain playing-status label, NOT
            # equivalent to Out or confirmed available. Do not price a
            # directly uncertain player's prop using historical minutes.
            uncertain = (
                status.isin({"day-to-day", "day to day", "questionable"})
                if "status" in report
                else pd.Series(False, index=report.index)
            )
            uncertain_players = set(players[uncertain].dropna().astype(int))
            uncertain_teams = set(report.loc[uncertain, "team"].dropna())
            newly_out_teams = set(
                report.loc[fresh & (high_risk | limited), "team"].dropna()
            )
            frame.loc[frame.team_espn.isin(newly_out_teams), "injury_status"] = (
                "TEAM_INJURY_CHANGE"
            )
            limited_ids = set(players[limited].dropna().astype(int))
            frame.loc[frame_ids.isin(limited_ids), "injury_status"] = (
                "REPORTED_MINUTES_RESTRICTION"
            )
            frame.loc[frame_ids.isin(uncertain_players), "injury_status"] = (
                "UNCERTAIN_PLAYER_AVAILABILITY"
            )
        else:
            uncertain_teams = set()
        # Second news source: the league's own report, every 15 minutes.
        diagnostics["official_injury_report"] = official_injury_vetoes(
            frame, ts, now, cache_dir=latest.parent / "official_injury_reports"
        )
        # Fetch ONLY an explicitly configured licensed pregame provider.
        # Do not mislabel historical minutes as independent projections.
        from live.nba_pregame_context import (
            enrich,
            historical_minutes_projection,
            load,
        )

        licensed_days = {
            pd.Timestamp(tip).tz_convert("America/New_York").strftime("%Y-%m-%d")
            for tip in frame.tip_utc.dropna()
            if 0 < (pd.Timestamp(tip) - pd.Timestamp(now)).total_seconds() <= 8 * 3600
        }
        context = load(licensed_days, now) if licensed_days else {"configured": False}
        if {
            "historical_minutes_baseline",
            "last_game_minutes",
            "recent_start_rate",
        }.issubset(frame.columns):
            frame = historical_minutes_projection(frame)
        frame = enrich(frame, context, now)
        # When independently projected minutes diverge from the training
        # forecast, do not keep trading the old p_model or pretend to
        # have recalibrated its distribution. Block until repriced.
        if "historical_minutes_baseline" in frame:
            historical = pd.to_numeric(
                frame.historical_minutes_baseline, errors="coerce"
            )
            independent = pd.to_numeric(frame.projected_minutes, errors="coerce")
            available = independent.notna()
            shift = (independent - historical).abs()
            material = (
                available & (shift > 6) & (shift > 0.20 * historical.clip(lower=1))
            )
            frame.loc[material, "injury_status"] = (
                "INDEPENDENT_MINUTES_SHIFT_REQUIRES_MODEL_REPRICE"
            )
            frame.loc[available & independent.lt(8), "injury_status"] = (
                "PROJECTED_LOW_OR_NO_PLAYING_TIME"
            )
            # Different starting assignment from established recent role:
            # existing game-specific mean is invalid, regardless of books.
            start_rate = pd.to_numeric(
                frame.get(
                    "recent_start_rate", pd.Series(float("nan"), index=frame.index)
                ),
                errors="coerce",
            )
            established = (
                frame.lineup_confirmation_status.eq("confirmed")
                & frame.confirmed_starter.notna()
            )
            unexpected_bench = (
                established & frame.confirmed_starter.eq(False) & start_rate.ge(0.8)
            )
            unexpected_start = (
                established & frame.confirmed_starter.eq(True) & start_rate.le(0.2)
            )
            frame.loc[unexpected_bench | unexpected_start, "injury_status"] = (
                "CONFIRMED_STARTING_ROLE_CHANGED"
            )
        # A server configured to REQUIRE independent feed never silently
        # trades from only historical data if credentials are unavailable.
        if os.environ.get("NBA_REQUIRE_VERIFIED_CONTEXT") == "YES":
            required_context = (
                frame.projected_minutes.isna()
                | frame.projected_minutes_source.ne("rotowire_licensed")
            )
            frame.loc[required_context, "injury_status"] = (
                "INDEPENDENT_PREGAME_MINUTES_REQUIRED"
            )
            # This requirement is explicit opt-in. Do not trust an expected
            # or projected lineup as confirmed in the final pre-tip half hour.
            missing_starters = frame.hours_to_tip.between(
                0, 0.5
            ) & frame.lineup_confirmation_status.ne("confirmed")
            frame.loc[missing_starters, "injury_status"] = (
                "FINAL_PREGAME_CONFIRMED_STARTERS_REQUIRED"
            )
        diagnostics.update(
            vendor_context_configured=bool(context.get("configured")),
            vendor_context_reason=context.get("reason", "available"),
            projected_minutes_verified=int(frame.projected_minutes.notna().sum()),
            confirmed_starter_rows=int(
                frame.lineup_confirmation_status.eq("confirmed").sum()
            ),
        )
        # Keep the baseline explicitly labeled. It is a trailing historical
        # minutes estimate, not a current coach-confirmed playing-time target.
        if "historical_minutes_baseline" in frame:
            minute_base = pd.to_numeric(
                frame.historical_minutes_baseline, errors="coerce"
            )
            frame.loc[~minute_base.between(0, 48), "injury_status"] = (
                "UNVERIFIED_HISTORICAL_MINUTES"
            )
        frame = refresh_quotes(frame, now)
        book_path = latest.parent / "nba_books.csv"
        if book_path.exists() and book_path.stat().st_size == 0:
            from kalshi.books import attach

            frame = attach(frame, None)
        else:
            frame = (
                attach_latest(frame, path=book_path)
                if book_path.exists()
                else attach_latest(frame)
            )
        if "book_updated_utc" in frame and not report.empty:
            team_news = (
                report.assign(stamp=pd.to_datetime(report.updated, utc=True))
                .groupby("team")
                .stamp.max()
            )
            update = pd.to_datetime(frame.book_updated_utc, utc=True, errors="coerce")
            stale_news = update < frame.team_espn.map(team_news)
            frame.loc[stale_news, "p_book"] = float("nan")
            frame.loc[stale_news, "book_n"] = 0
        if "book_commence_utc" in frame:
            game_gap = (
                (
                    pd.to_datetime(frame.book_commence_utc, utc=True, errors="coerce")
                    - frame.tip_utc
                )
                .dt.total_seconds()
                .abs()
            )
            frame.loc[game_gap > 900, "p_book"] = float("nan")
            frame.loc[game_gap > 900, "book_n"] = 0
        # A sportsbook quote may have been cached for four hours. Those
        # probabilities are too old to validate a live resting order near
        # tip, especially after lineup/injury changes. Hard age bounds:
        # 2h early; 75m inside 2.5h of tip. No synthetic fresh timestamps.
        if "book_updated_utc" in frame:
            book_stamp = pd.to_datetime(
                frame.book_updated_utc, utc=True, errors="coerce"
            )
            age_minutes = (pd.Timestamp(now) - book_stamp).dt.total_seconds() / 60
            max_minutes = frame.hours_to_tip.le(2.5).map({True: 75, False: 120})
            stale = book_stamp.isna() | age_minutes.lt(0) | age_minutes.gt(max_minutes)
        else:
            stale = frame.book_n.ge(2)
        diagnostics["sportsbook_age_rejected"] = int(stale.sum())
        frame.loc[stale, "p_book"] = float("nan")
        frame.loc[stale, "book_n"] = 0
        # Never use a solitary sportsbook as a consensus probability.
        # Previously the entry logic could accept book_n=1, while the v3
        # resting recheck required two books and canceled the same order
        # on the next pass. With only one book, fall back to the historical
        # model ONLY when this market is independently role-verified.
        weak_books = pd.to_numeric(frame.book_n, errors="coerce").fillna(0) < 2
        frame.loc[weak_books, "p_book"] = float("nan")
        # Opening-night, long-absence and transferred-player roles are not
        # established by last season's box scores. Require two fresh books.
        required = frame.requires_book.astype(str).str.lower().isin({"true", "1"})
        invalid_flag = ~frame.requires_book.astype(str).str.lower().isin(
            {"true", "false", "1", "0"}
        )
        history_gap = (
            frame.tip_utc
            - pd.to_datetime(frame.last_player_game_utc, utc=True, errors="coerce")
        ).dt.days
        required |= (
            history_gap.isna()
            | (history_gap > 45)
            | frame.team_espn.ne(frame.last_player_team)
        )
        frame.loc[
            invalid_flag | (required & (frame.p_book.isna() | (frame.book_n < 2))),
            "injury_status",
        ] = "SEASON_OR_ROLE_CHANGE_NEEDS_TWO_BOOKS"
        # Teammates of a day-to-day/questionable rotation player are not
        # modeled by a single fixed minutes scenario. Require an independent
        # two-book consensus, but never override a stronger existing veto.
        official_two_books = (
            frame["official_two_books"].fillna(False).astype(bool)
            if "official_two_books" in frame
            else False
        )
        uncertain_no_books = (
            (frame.team_espn.isin(uncertain_teams) | official_two_books)
            & (frame.p_book.isna() | (frame.book_n < 2))
            & frame.injury_status.eq("")
        )
        frame.loc[uncertain_no_books, "injury_status"] = (
            "UNCERTAIN_TEAM_REQUIRES_TWO_BOOKS"
        )
        diagnostics.update(
            rows=len(frame),
            in_entry_window=int(frame.hours_to_tip.between(*WINDOW).sum()),
            verified=int(frame.injury_status.eq("").sum()),
            book_covered=int(frame.p_book.notna().sum()),
            historical_minutes_available=int(
                pd.to_numeric(
                    frame.get("historical_minutes_baseline", pd.Series(dtype=float)),
                    errors="coerce",
                )
                .notna()
                .sum()
            ),
            exclusions=frame.loc[frame.injury_status.ne(""), "injury_status"]
            .value_counts()
            .to_dict(),
        )
        frame.attrs["diagnostics"] = diagnostics
        print(
            f"NBA PREFLIGHT: model_age={age:.2f}h, open_quoted={len(frame)}, "
            f"verified={int(frame.injury_status.fillna('').eq('').sum())}, "
            f"book_covered={int(frame.p_book.notna().sum())}"
        )
        return frame
    except Exception as err:
        # Don't leak HTTP response bodies, headers, or credentials.
        print(f"NBA PREFLIGHT BLOCKED: {type(err).__name__} -- no new orders")
        blocked = pd.DataFrame()
        blocked.attrs["diagnostics"] = {
            **diagnostics,
            "blocked": str(err) if isinstance(err, ValueError) else type(err).__name__,
        }
        return blocked


def assert_nfl_production_stopped():
    """Do not run two independently capped production pilots on one account."""
    import subprocess

    for unit in (
        "market-maker-prod-nfl-auto.timer",
        "market-maker-prod-nfl-auto.service",
    ):
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "--quiet", unit],
                timeout=5,
                check=False,
                capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TradingError(
                "Cannot verify isolated NBA production account"
            ) from error
        if result.returncode == 0:
            raise TradingError("NFL production still active: NBA trading HALTED")
        # systemd returns 3 for inactive/failed and 4 for no matching unit.
        # Any other result is ambiguous: block production trading.
        if result.returncode not in {3, 4}:
            raise TradingError(
                "Uncertain NFL production unit state: NBA trading HALTED"
            )


def main():
    global PROCESS_START
    PROCESS_START = time.monotonic()
    from contextlib import nullcontext
    from live.production_lock import account_lock
    from live.nba_inputs import sync, atomic_write

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Production GET checks only; never submits or cancels",
    )
    parser.add_argument("--sync-inputs", action="store_true")
    args = parser.parse_args()
    if sum((args.dry_run, args.live, args.status, args.preflight)) != 1:
        parser.error("Choose exactly one mode")
    directory = (
        STATE
        if args.live or args.status or args.preflight
        else Path("/tmp/smm-nba-auto-readonly")
    )
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    with (
        account_lock() if args.live else nullcontext(),
        (directory / "lock").open("a+") as lock,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = directory / "journal.jsonl"
        if args.status:
            events = load_journal(journal)
            print("Pilot attempts:", len([e for e in events if e["event"] == "intent"]))
            print("Accepted:", len([e for e in events if e["event"] == "accepted"]))
            print(
                "Uncertain:",
                len([e for e in events if e["event"] == "unknown_outcome"]),
            )
            return
        if os.environ.get("KALSHI_ENV") != "prod":
            raise TradingError(
                "Production auto requires production venue even for dry run"
            )
        client = (ReadOnlyClient if args.preflight else TradingClient)(
            dry_run=args.dry_run or args.preflight, env="prod"
        )
        if args.live:
            guard(os.environ, client)
            if (directory / "KILL").exists():
                cancel_owned_on_kill(client, journal)
                return
            from live.shared_account_risk import dual_mode

            if not dual_mode(os.environ):
                assert_nfl_production_stopped()
        now = datetime.now(UTC)
        latest = Path("outputs/projections/latest.csv")
        if args.sync_inputs:
            latest = directory / "inputs" / "latest.csv"
            try:
                sync(latest.parent, now)
            except Exception as error:
                print(
                    f"NBA INPUT SYNC: {type(error).__name__}; checking cached input age/hash",
                    flush=True,
                )
        frame = nba_candidates(now, latest=latest)
        if args.preflight:
            report = preflight(client, frame, now, journal)
            atomic_write(
                directory / "preflight.json",
                (json.dumps(report, indent=2) + "\n").encode(),
            )
            print(json.dumps(report, indent=2))
            raise SystemExit(0 if report["ready"] else 2)
        pass_once(client, os.environ, frame, now, journal, dry=args.dry_run)
        print("NBA WORKER: completed", flush=True)


class ReadOnlyClient(TradingClient):
    def _request(self, method, path, params=None, body=None):
        if method != "GET":
            raise TradingError("Read-only preflight rejects exchange writes")
        return super()._request(method, path, params=params, body=body)


def preflight(client, frame, now, journal):
    """Inspect the real account without altering exchange orders or journals."""
    failures = []
    if client.env != "prod" or not client.can_sign:
        failures.append("signed_production_reads_required")
    from live.shared_account_risk import dual_mode, state_for

    try:
        dual = dual_mode(os.environ)
        if not dual:
            assert_nfl_production_stopped()
    except TradingError as error:
        dual = False
        failures.append(str(error))
    if (journal.parent / "KILL").exists():
        failures.append("NBA_KILL_exists")
    if frame.empty or not frame.injury_status.eq("").any():
        failures.append("no_verified_projection_rows")
    try:
        events = load_journal(journal)
        attempts, accepted = records(events)
        rejected = rejected_client_ids(events)
        if dual:
            state, _shared = state_for(client, "nba", now)
        else:
            state = current_production_state(client, attempts, accepted, rejected)
        old_resting = legacy_resting_count(attempts, accepted, state["resting"])
        cash = money(client.balance()["balance"])
        if cash < MAX_ORDER_COST:
            failures.append("cash_below_order_cap")
        # Aggregated account cash is not usable collateral on another shard.
        # Check one representative eligible market without submitting anything.
        verified = frame[frame.injury_status.fillna("").eq("")]
        if not verified.empty:
            try:
                require_funded_shard(
                    client, str(verified.iloc[0].ticker), reserve(MAX_ORDER_COST)
                )
            except TradingError as error:
                failures.append(
                    str(error)
                    if str(error).startswith("SHARD_UNFUNDED_")
                    else "shard_funding_or_routing_unverifiable"
                )
        pnl_check = nba_realized_pnl(
            state["settlements"], {a["ticker"] for a in attempts}, now
        )
        if pnl_check["loss_stop"]:
            failures.append("nba_realized_loss_stop")
        budget = sum(reserve(a["cost"]) for a in attempts)
        if budget >= MAX_GROSS_COST:
            failures.append("lifetime_budget_exhausted")
        account = {
            "cash_dollars": cash,
            "gross_reserved": budget,
            "resting": len(state["resting"]),
            "legacy_prior_version_resting_orders": old_resting,
            "entry_state": (
                "waiting_for_prior_version_orders"
                if old_resting
                else "eligible_for_current_version"
            ),
            "held_markets": len(state["held"]),
            "realized_pnl_stop": pnl_check,
        }
    except Exception as error:
        failures.append(
            str(error) if isinstance(error, TradingError) else type(error).__name__
        )
        account = {"verified": False}
    return {
        "utc": now.isoformat(),
        "ready": not failures,
        "strategy_version": STRATEGY_VERSION,
        "failures": failures,
        "account": account,
        "inputs": frame.attrs.get("diagnostics", {}),
        "note": "Read-only readiness check; owner activation is separate. No fill or profit claim.",
    }


if __name__ == "__main__":
    main()
