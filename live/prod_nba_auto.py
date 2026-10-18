"""Bounded unattended NBA production experiment. SEPARATE from NFL and Demo.

This worker is isolated from the Demo service and has a lifetime *gross-cost*
budget below $50 including a fee buffer. One new post-only order max per pass,
no automatic re-arming, and durable journal before each network write. Fail
closed on inconsistent balances, orders, positions, fills or model data.
"""

import argparse
import fcntl
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from kalshi.api import fetch_market
from kalshi.paper_props import candidate_orders
from kalshi.trading import Order, TradingClient, TradingError
from live.nfl_policy import settlement_accounting
from live.nba_inputs import MODEL_VERSION

STRATEGY_VERSION = "nba-no-v2-opening-audit"

MAX_GROSS_COST = 50.0
MAX_ORDER_COST = 3.0
MAX_ACTIVE_COST = 15.0
MAX_GAME_COST = 3.0
MAX_TEAM_COST = 3.0
MAX_DAILY_COST = 30.0
MAX_GAME_ORDERS = 2
MAX_CONTRACTS = 5
FEE_RESERVE = 1.10
WINDOW = (2.0, 6.0)  # baseline NBA rule: 2–6 h before verified tip
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


def records(events):
    attempts = [e for e in events if e.get("event") == "intent"]
    accepted = {e["client_order_id"]: e for e in events if e.get("event") == "accepted"}
    if len({e["client_order_id"] for e in attempts}) != len(attempts):
        raise TradingError("Duplicate client order ID in production journal")
    for attempt in attempts:
        if attempt["client_order_id"] not in accepted:
            raise TradingError(
                "Uncertain production order attempt: HALT, reconcile manually"
            )
    return attempts, accepted


def current_production_state(client, attempts, accepted):
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
    still_at_risk = [a for a in attempts if a["ticker"] not in settled]
    return {
        "resting": resting,
        "held": held,
        "settled": settled,
        "settlements": settlements,
        "active": still_at_risk,
    }


def reconcile_expired_unfilled(attempts, accepted, state, fills, now):
    """Release *active* capacity only on robust evidence of zero execution.

    Full historical attempt cost still counts toward the lifetime and daily
    gross-spend caps. Never release recent, partially filled, resting, or
    unaccounted orders. Check the exchange again on every subsequent pass.
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
    from datetime import timedelta

    released = 0
    for attempt in attempts:
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
        # Require 10 extra minutes after nominal expiration to tolerate late
        # exchange events. No history, no balance release.
        can_release = (
            pd.notna(tip)
            and now >= tip.to_pydatetime() + timedelta(minutes=10)
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


def cancel_invalid_resting(client, journal, state, frame, now):
    """Withdraw owned orders after new roster/injury/market safety failures."""
    if frame.empty:
        invalid = set(o.get("order_id") for o in state["resting"])
    else:
        status = frame.set_index("ticker")["injury_status"].fillna("UNVERIFIED")
        valid = set(status[status.eq("")].index)
        invalid = set()
        for resting in state["resting"]:
            ticker = resting.get("ticker")
            if ticker not in valid:
                invalid.add(resting["order_id"])
                continue
            row = frame.set_index("ticker").loc[ticker]
            if not WINDOW[0] < float(row.hours_to_tip) <= WINDOW[1]:
                invalid.add(resting["order_id"])
    canceled = 0
    for resting in state["resting"]:
        order_id = resting.get("order_id")
        if order_id not in invalid:
            continue
        ticker = resting.get("ticker")
        if not ticker:
            raise TradingError("Cannot cancel order without its ticker: HALT")
        write_event(
            journal,
            {
                "event": "cancel_intent",
                "utc": now.isoformat(),
                "order_id": order_id,
                "ticker": ticker,
                "reason": "availability no longer verified",
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


# Guardrail for the small pilot. No change to maker/taker status or risk caps.
# Only improve a quote by a second tick in a spread wide enough to stay passive.
EXTRA_MAKER_TICK = 0.0  # freeze NBA baseline pricing; no NFL 2-tick experiment
MIN_EDGE_AFTER_IMPROVEMENT = 0.03


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


def select_candidates(frame, events, state, now):
    attempts, _ = records(events)
    if frame.empty:
        return []
    eligible = frame[
        frame.injury_status.fillna("").eq("")
        & frame.hours_to_tip.between(*WINDOW)
        & frame.tip_utc.notna()
        & frame.ticker.astype(str).str.startswith(
            ("KXNBAPTS-", "KXNBAREB-", "KXNBAAST-", "KXNBA3PT-")
        )
    ]
    if eligible.empty:
        return []
    found = candidate_orders(eligible, "no_seller_bookline", window=WINDOW)
    if found.empty:
        return []
    found = found[found.side.eq("no")].copy()
    found["edge"] = pd.to_numeric(found.edge, errors="coerce")
    # Extremely large modeled edges are suspicious: wrong player, mismatched
    # line, or stale sportsbook feed. Such markets need human review.
    found = found[found.edge.between(0, 0.15)]
    already = {a["ticker"] for a in attempts}
    found = found[~found.ticker.isin(already)]
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
    if not 10 <= cents <= 90:
        raise TradingError("Order price outside safe 10c–90c range")
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
        expiration_ts=min(int(now.timestamp()) + 3600, int(tip.timestamp()) - 7200),
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


def room_for(attempts, active, row, cost, now):
    today = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    total = sum(reserve(a["cost"]) for a in attempts)
    open_now = sum(reserve(a["cost"]) for a in active)
    game_cost = sum(
        reserve(a["cost"]) for a in attempts if a["game_id"] == str(row.game_id)
    )
    team_cost = sum(reserve(a["cost"]) for a in attempts if a["team"] == str(row.team))
    game_orders = sum(a["game_id"] == str(row.game_id) for a in attempts)
    day_cost = sum(
        reserve(a["cost"])
        for a in attempts
        if datetime.fromisoformat(a["utc"])
        .astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
        .date()
        == today
    )
    r = reserve(cost)
    return (
        total + r <= MAX_GROSS_COST + 1e-9
        and open_now + r <= MAX_ACTIVE_COST + 1e-9
        and game_cost + r <= MAX_GAME_COST + 1e-9
        and team_cost + r <= MAX_TEAM_COST + 1e-9
        and day_cost + r <= MAX_DAILY_COST + 1e-9
        and game_orders < MAX_GAME_ORDERS
    )


def pass_once(client, env, frame, now, journal, *, dry=False):
    from collections import Counter
    from live.nba_inputs import atomic_write
    from kalshi.fees import live_maker_fee_bound

    skipped = Counter()

    def finish(decision, placed=False):
        report = {
            "utc": datetime.now(UTC).isoformat(),
            "strategy_version": STRATEGY_VERSION,
            "decision": decision,
            "placed": placed,
            "candidate_count": len(candidates),
            "skipped": dict(skipped),
            "inputs": frame.attrs.get("diagnostics", {}),
            "attempts": len(attempts),
            "gross_reserved": sum(reserve(a["cost"]) for a in attempts),
        }
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
    if not dry:
        state = current_production_state(client, attempts, accepted)
        free = money(client.balance()["balance"])
    else:
        state = {"active": []}
    candidates = select_candidates(frame, events, state, now)
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
            attempts, accepted, state, fills, now
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
        for resting in state["resting"]:
            record_queue_observation(client, journal, resting["order_id"], now)
        record_markouts(journal, frame, now)
        canceled = cancel_invalid_resting(client, journal, state, frame, now)
        if canceled:
            print(f"PROD AUTO: canceled {canceled} unsafe resting orders")
            # Require another reconciliation pass after cancellation.
            return finish("unsafe_resting_canceled")
        print(
            f"PROD AUTO: attempts={len(attempts)}, resting={len(state['resting'])}, "
            f"held={len(state['held'])}, settled_tickers={len(state['settled'])}, "
            f"fills={len(fills)}, gross_reserved=${sum(reserve(a['cost']) for a in attempts):.2f}/${MAX_GROSS_COST:.0f}"
        )
    if not candidates:
        print("No eligible 2-6h NBA opportunities")
        return finish("no_eligible_candidates")
    for row in candidates:
        try:
            quoted, execution_edge, extra_ticks = execution_quote(row)
            order, cost = order_from_row(row, now, no_price=quoted)
        except TradingError:
            skipped["invalid_order_or_price"] += 1
            continue
        while order.count > 0 and not room_for(
            attempts, state["active"], row, cost, now
        ):
            order.count -= 1
            cost = round(order.count * order.price_cents / 100, 2)
        if order.count <= 0:
            skipped["risk_budget"] += 1
            continue
        if not dry and free < reserve(cost):
            skipped["cash_balance"] += 1
            continue
        try:
            fee_bound, fee_metadata = live_maker_fee_bound(
                order.ticker, quoted, order.count
            )
            p_book = float(getattr(row, "p_book", float("nan")))
            p_yes = p_book if math.isfinite(p_book) else float(row.p_model)
            net_edge = 1 - p_yes - quoted - fee_bound / order.count
            if not 0 < net_edge <= 0.15:
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

        # Durable intent first; any failure after this (including a timeout)
        # disables all future automatic orders until manually investigated.
        write_event(
            journal,
            {
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
                "probability_source": "sportsbook"
                if math.isfinite(p_book)
                else "model",
                "p_yes": p_yes,
                "book_n": int(getattr(row, "book_n", 0)),
                "fee_bound_dollars": fee_bound,
                "net_edge_after_fee_bound": round(net_edge, 6),
                "model_generated_utc": str(getattr(row, "model_generated_utc", "")),
                "expiration_ts": order.expiration_ts,
                **fee_metadata,
            },
        )
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
        write_event(
            journal,
            {
                "event": "accepted",
                "utc": datetime.now(UTC).isoformat(),
                "client_order_id": order.client_order_id,
                "order_id": result["order_id"],
            },
        )
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
        return finish("accepted", placed=True)
    print("No opportunities fit remaining production risk budget or fresh quotes")
    return finish("all_candidates_blocked")


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
            newly_out_teams = set(report.loc[fresh, "team"].dropna())
            frame.loc[frame.team_espn.isin(newly_out_teams), "injury_status"] = (
                "TEAM_INJURY_CHANGE"
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
        diagnostics.update(
            rows=len(frame),
            in_entry_window=int(frame.hours_to_tip.between(*WINDOW).sum()),
            verified=int(frame.injury_status.eq("").sum()),
            book_covered=int(frame.p_book.notna().sum()),
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
    try:
        assert_nfl_production_stopped()
    except TradingError as error:
        failures.append(str(error))
    if (journal.parent / "KILL").exists():
        failures.append("NBA_KILL_exists")
    if frame.empty or not frame.injury_status.eq("").any():
        failures.append("no_verified_projection_rows")
    try:
        attempts, accepted = records(load_journal(journal))
        state = current_production_state(client, attempts, accepted)
        cash = money(client.balance()["balance"])
        if cash < MAX_ORDER_COST:
            failures.append("cash_below_order_cap")
        budget = sum(reserve(a["cost"]) for a in attempts)
        if budget >= MAX_GROSS_COST:
            failures.append("lifetime_budget_exhausted")
        account = {
            "cash_dollars": cash,
            "gross_reserved": budget,
            "resting": len(state["resting"]),
            "held_markets": len(state["held"]),
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
