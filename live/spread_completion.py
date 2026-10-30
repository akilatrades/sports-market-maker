"""Versioned completion policy. Pure calculations; no exchange writes.

This is a small pilot specification, not a fitted or validated source of alpha.
The original spread policy and forward-study protocol are intentionally separate.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from research.spread_forward_core import (
    EvidenceError,
    amount,
    instant,
    normalize_fill,
    orders_from_journal,
    replay,
)

VERSION = "spread-v4-completion-pilot-1"
TARGET = Decimal("0.02")
LOSS_ALLOWANCE = Decimal("0.10")
SIZE = Decimal("1")
ACTIVE_CAP = Decimal("10")
DAILY_LOSS = Decimal("1")
TOTAL_LOSS = Decimal("3")
MAX_AGE = timedelta(minutes=60)
QUOTE_LIFE = timedelta(seconds=90)
CUTOFF = timedelta(minutes=20)
MIN_ENTRY_LEAD = timedelta(minutes=85)
MIN_DEPTH = Decimal("10")
MAX_EXIT_GAP = Decimal("0.05")
MAX_BOOK_SECONDS = 5
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Quote:
    ticker: str
    side: str
    price: int
    quantity: Decimal
    purpose: str
    immediate: bool = False


def fee_bound(fees, taker=False):
    """Dollars/contract, including worst 0.01-contract fill fragmentation.

    July 7 2026 schedule rounds fee + cost to $0.0001. Each 0.01-contract
    fragment therefore needs at most $0.01/contract extra rounding reserve.
    p(1-p) <= 1/4 also covers price improvement on an IOC limit order.
    No rebates, fee waivers or future volume discounts are credited.
    """
    kind = fees.get("fee_type")
    if kind not in ("quadratic", "quadratic_with_maker_fees"):
        raise EvidenceError("unsupported_fee_schedule")
    multiplier = amount(fees.get("fee_multiplier"))
    rate = Decimal("0.07") if taker else Decimal("0.0175")
    if not taker and kind == "quadratic":
        rate = Decimal(0)
    return rate * multiplier / 4 + CENT


def inventory(events, fills, positions, settled, now):
    """Replay actual v4 fills; refuse missing fees, drift or legacy inventory."""
    orders = orders_from_journal(events)
    own = {k: v for k, v in orders.items() if v.get("strategy_version") == VERSION}
    normalized = {}
    filled_by_order = {}
    for raw in fills:
        if str(raw.get("order_id")) not in own:
            continue
        fill = normalize_fill(raw, own[str(raw["order_id"])])
        if instant(fill["at"]) > now:
            raise EvidenceError("future_fill")
        if amount(fill["quantity"]) % CENT:
            raise EvidenceError("unsupported_quantity_precision")
        if fill["fid"] in normalized and normalized[fill["fid"]] != fill:
            raise EvidenceError("conflicting_fill")
        if fill["fid"] not in normalized:
            filled_by_order[fill["oid"]] = filled_by_order.get(fill["oid"], Decimal(0)) + amount(fill["quantity"])
        if filled_by_order[fill["oid"]] > amount(own[fill["oid"]]["count"]):
            raise EvidenceError("fill_exceeds_order_quantity")
        reserve = own[fill["oid"]].get("fee_bound_per_contract")
        if reserve is None or amount(fill["fee"]) > amount(fill["quantity"]) * amount(reserve):
            raise EvidenceError("observed_fee_exceeds_reserve")
        normalized[fill["fid"]] = fill
    for row in events:
        if row.get("event") == "fill" and str(row.get("order_id")) in own:
            if str(row.get("fill_id")) not in normalized:
                raise EvidenceError("signed_fill_history_incomplete")
    lots = replay(list(normalized.values()))["open_lots"]
    result = {}
    for ticker in set(lots) | set(positions):
        queue = [] if ticker in settled else lots.get(ticker, [])
        net = sum(
            (amount(x["left"]) * (1 if x["side"] == "yes" else -1) for x in queue),
            Decimal(0),
        )
        if net != Decimal(str(positions.get(ticker, 0))):
            raise EvidenceError("inventory_does_not_reconcile")
        if not queue:
            continue
        for lot in queue:
            fill = normalized[lot["fid"]]
            lot["basis"] = amount(lot["price"]) + amount(fill["fee"]) / amount(
                fill["quantity"], True
            )
            lot["at"] = instant(fill["at"])
            lot["intent"] = own[fill["oid"]]
        result[ticker] = queue
    return result


def best(book, side):
    levels = book.get(side)
    if not isinstance(levels, list) or not levels:
        raise EvidenceError("missing_two_sided_depth")
    parsed = [(amount(p, True), amount(q, True)) for p, q in levels]
    if any(p >= 1 for p, _ in parsed):
        raise EvidenceError("invalid_book_price")
    return max(parsed)


def cents_floor(value):
    return int((value * 100).to_integral_value(rounding=ROUND_FLOOR))


def entry_quotes(market, book, fees, start, now):
    """One market/event at a time. Require depth and a small liquidation gap."""
    if start - now < MIN_ENTRY_LEAD:
        return []
    yes, yes_depth = best(book, "yes")
    no, no_depth = best(book, "no")
    if 1 - yes - no < Decimal("0.08") or min(yes_depth, no_depth) < MIN_DEPTH:
        return []
    # Whole-cent prices, rounded toward less aggressive bids.
    yp, np = cents_floor(yes) + 1, cents_floor(no) + 1
    if not (2 <= yp <= 98 and 2 <= np <= 98):
        return []
    maker, taker = fee_bound(fees), fee_bound(fees, True)
    if 1 - Decimal(yp + np) / 100 - 2 * maker < TARGET:
        return []
    if max(Decimal(yp) / 100 - yes, Decimal(np) / 100 - no) + maker + taker > MAX_EXIT_GAP:
        return []
    return [
        Quote(market["ticker"], "yes", yp, SIZE, "entry"),
        Quote(market["ticker"], "no", np, SIZE, "entry"),
    ]


def completion_quote(ticker, lots, book, fees, start, now):
    """Cap every closing leg at the held quantity; never average down.

    Crossing is IOC + exchange reduce-only. Passive quotes never cross and
    require the runtime's cancel/reconcile barrier. A price floor can leave
    an unmatched position: this is explicitly not a guaranteed stop loss.
    """
    sides = {x["side"] for x in lots}
    if len(sides) != 1:
        raise EvidenceError("mixed_inventory")
    held = next(iter(sides))
    side = "no" if held == "yes" else "yes"
    quantity = sum((amount(x["left"]) for x in lots), Decimal(0))
    basis = max(x["basis"] for x in lots)
    oldest = min(x["at"] for x in lots)
    expired = now >= min(oldest + MAX_AGE, start - CUTOFF)
    if now >= start:
        return None, "event_started_unmatched"
    bid, _ = best(book, side)
    opposite_bid, _ = best(book, held)
    ask = 1 - opposite_bid
    if bid >= ask:
        raise EvidenceError("crossed_book")
    target = -LOSS_ALLOWANCE if expired else TARGET
    limit = min(99, cents_floor(1 - basis - target - fee_bound(fees, True)))
    if limit >= 1 and ask <= Decimal(limit) / 100:
        return Quote(
            ticker, side, limit, quantity,
            "timeout_exit" if expired else "take_profit", True,
        ), "inventory_timeout" if expired else "completing"
    if expired:
        return None, "exit_price_floor_blocked"
    passive_limit = cents_floor(1 - basis - TARGET - fee_bound(fees))
    # At least a full cent below the offer, even for sub-cent books.
    price = min(99, passive_limit, cents_floor(bid) + 1, cents_floor(ask - CENT))
    if price < 1:
        return None, "no_profitable_quote"
    return Quote(ticker, side, price, quantity, "complete"), "completing"
