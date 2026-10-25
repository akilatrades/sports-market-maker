"""Pure accounting and depth calculations for a read-only prospective study."""

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation

ZERO = Decimal(0)
ONE = Decimal(1)
THRESHOLD = Decimal("0.10")
HORIZONS = (0, 600, 1800, 3600)
MAX_LATE = 60


class EvidenceError(ValueError):
    pass


def amount(value, positive=False):
    if value is None or isinstance(value, bool):
        raise EvidenceError("missing_amount")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise EvidenceError("invalid_amount") from None
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        raise EvidenceError("invalid_amount")
    return result


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        raise EvidenceError("invalid_time") from None
    if result.tzinfo is None:
        raise EvidenceError("timezone_required")
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def orders_from_journal(events):
    intents = {e["client_order_id"]: e for e in events if e.get("event") == "intent"}
    accepted = {}
    for event in events:
        if event.get("event") != "accepted":
            continue
        oid, cid = event.get("order_id"), event.get("client_order_id")
        if not oid or cid not in intents:
            raise EvidenceError("ambiguous_order_ownership")
        if oid in accepted and accepted[oid] != intents[cid]:
            raise EvidenceError("ambiguous_order_ownership")
        accepted[oid] = intents[cid]
    return accepted


def normalize_fill(raw, intent):
    side = intent["side"]
    if side not in ("yes", "no"):
        raise EvidenceError("invalid_side")
    if raw.get("outcome_side") != side or raw.get("book_side") != (
        "bid" if side == "yes" else "ask"
    ):
        raise EvidenceError("canonical_direction_mismatch")
    quantity = amount(raw.get("count_fp", raw.get("count")), True)
    price = amount(raw.get(side + "_price_dollars"))
    opposite = amount(raw.get(("no" if side == "yes" else "yes") + "_price_dollars"))
    if price > ONE or price + opposite != ONE:
        raise EvidenceError("invalid_complementary_prices")
    if price > Decimal(str(intent["price_cents"])) / 100:
        raise EvidenceError("fill_exceeds_limit")
    fid = str(raw.get("fill_id") or raw.get("trade_id") or "")
    at = instant(raw["created_time"])
    if not fid or (raw.get("ticker") or raw.get("market_ticker")) != intent["ticker"]:
        raise EvidenceError("invalid_fill_identity")
    return {
        "fid": fid,
        "oid": raw["order_id"],
        "ticker": intent["ticker"],
        "event_ticker": intent["event_ticker"],
        "side": side,
        "quantity": str(quantity),
        "price": str(price),
        "fee": str(amount(raw.get("fee_cost"))),
        "at": at.isoformat(),
        "version": intent["strategy_version"],
    }


def normalized_orders(rows):
    """All account orders, including other cohorts, removed from public bids."""
    result = []
    seen = set()
    for row in rows:
        oid = row.get("order_id")
        if not oid or oid in seen:
            raise EvidenceError("duplicate_or_missing_order")
        seen.add(oid)
        if row.get("status") != "resting":
            raise EvidenceError("nonresting_order_in_snapshot")
        book = row.get("book_side")
        if book not in ("bid", "ask"):
            raise EvidenceError("missing_order_book_side")
        yes = amount(row.get("yes_price_dollars"))
        no = amount(row.get("no_price_dollars"))
        if yes > ONE or yes + no != ONE:
            raise EvidenceError("invalid_order_prices")
        side = "yes" if book == "bid" else "no"
        result.append(
            {
                "oid": oid,
                "ticker": row["ticker"],
                "side": side,
                "price": str(yes if side == "yes" else no),
                "quantity": str(
                    amount(row.get("remaining_count_fp", row.get("remaining_count")))
                ),
            }
        )
    return sorted(result, key=lambda row: row["oid"])


def external_book(payload, ticker, own):
    block = payload.get("orderbook_fp")
    if not isinstance(block, dict):
        raise EvidenceError("missing_fixed_point_book")
    result = {}
    for side in ("yes", "no"):
        raw = block.get(side + "_dollars")
        if not isinstance(raw, list):
            raise EvidenceError("missing_book_side")
        levels = defaultdict(Decimal)
        for entry in raw:
            if not isinstance(entry, list) or len(entry) != 2:
                raise EvidenceError("invalid_book_level")
            price, quantity = amount(entry[0], True), amount(entry[1])
            if price >= ONE:
                raise EvidenceError("invalid_book_price")
            levels[price] += quantity
        for order in own:
            if order["ticker"] == ticker and order["side"] == side:
                price, quantity = amount(order["price"]), amount(order["quantity"])
                if levels[price] < quantity:
                    raise EvidenceError("own_order_exceeds_public_depth")
                levels[price] -= quantity
        result[side] = [
            [str(price), str(quantity)]
            for price, quantity in sorted(levels.items(), reverse=True)
            if quantity > 0
        ]
    return result


def consume(levels, quantity, multiplier=ONE, slippage=ZERO):
    """Consume shared depth once, with conservative per-level cent fee rounding."""
    remaining = amount(quantity)
    proceeds = fees = ZERO
    parts = []
    for level in levels:
        price, size = amount(level[0]), amount(level[1])
        take = min(size, remaining)
        if not take:
            continue
        executed = max(ZERO, price - slippage)
        fee = Decimal("0.07") * multiplier * take * executed * (1 - executed)
        fee = fee.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        proceeds += take * executed
        fees += fee
        remaining -= take
        level[1] = str(size - take)
        parts.append([str(executed), str(take), str(fee)])
        if not remaining:
            break
    return {
        "quantity": str(amount(quantity) - remaining),
        "remaining": str(remaining),
        "proceeds": str(proceeds),
        "fee_estimate": str(fees),
        "levels": parts,
    }


def replay(fills, samples=(), outcomes=None, slippage=ZERO):
    """Fixed-entry comparison. No inferred fills, doubled lots or reused depth."""
    outcomes = outcomes or {}
    timeline = []
    seen = {}
    for fill in fills:
        fid = fill["fid"]
        if fid in seen:
            if fill != seen[fid]:
                raise EvidenceError("conflicting_fill")
            continue
        seen[fid] = fill
        timeline.append((instant(fill["at"]), 0, fid, "entry", fill))
    for sample in samples:
        timeline.append((instant(sample["at"]), 1, sample["id"], "checkpoint", sample))
    lots = defaultdict(list)
    pnl = defaultdict(Decimal)
    sales = []
    attempted = set()
    invalid = set()
    for at, _, _, kind, row in sorted(timeline):
        ticker = row["ticker"]
        outcome_at = outcomes.get(ticker, {}).get("at")
        if outcome_at and at > instant(outcome_at):
            if kind == "checkpoint" and not row.get("valid"):
                invalid.add(ticker)
                continue
            raise EvidenceError("activity_after_settlement")
        if kind == "entry":
            left = amount(row["quantity"], True)
            price = amount(row["price"])
            pnl[ticker] -= amount(row["fee"])
            queue = lots[ticker]
            while left and queue and queue[0]["side"] != row["side"]:
                old = queue[0]
                paired = min(left, old["left"])
                pnl[ticker] += paired * (ONE - price - old["price"])
                old["left"] -= paired
                left -= paired
                if not old["left"]:
                    queue.pop(0)
            if left:
                queue.append(
                    {
                        "fid": row["fid"],
                        "side": row["side"],
                        "left": left,
                        "price": price,
                    }
                )
            continue
        if not row.get("valid") or row.get("fee_type") not in (
            "quadratic",
            "quadratic_with_maker_fees",
        ):
            invalid.add(ticker)
            continue
        multiplier = amount(row.get("fee_multiplier"))
        depth = json.loads(json.dumps(row["external_book"]))
        for reference in sorted(row["lots"], key=lambda x: (x["fill_at"], x["fid"])):
            fid = reference["fid"]
            if fid not in seen:
                raise EvidenceError("checkpoint_unknown_fill")
            original = seen[fid]
            age = (at - instant(original["at"])).total_seconds()
            horizon = reference["horizon_seconds"]
            if horizon not in HORIZONS or not 0 <= age - horizon <= MAX_LATE:
                invalid.add(ticker)
                continue
            if horizon == 0 or fid in attempted:
                continue
            lot = next((x for x in lots[ticker] if x["fid"] == fid), None)
            if lot is None:
                continue
            levels = depth[lot["side"]]
            if not levels or amount(levels[0][0]) < lot["price"] + THRESHOLD:
                continue
            left = min(lot["left"], amount(reference["remaining_actual"]))
            if not left:
                continue
            sale = consume(levels, left, multiplier, slippage)
            sold = amount(sale["quantity"])
            pnl[ticker] += amount(sale["proceeds"]) - sold * lot["price"]
            pnl[ticker] -= amount(sale["fee_estimate"])
            lot["left"] -= sold
            attempted.add(fid)
            sales.append({"fid": fid, "ticker": ticker, "at": row["at"], **sale})
        lots[ticker] = [lot for lot in lots[ticker] if lot["left"]]
    unresolved = {}
    for ticker, queue in lots.items():
        outcome = outcomes.get(ticker)
        if outcome is None:
            if queue:
                unresolved[ticker] = [
                    dict(x, left=str(x["left"]), price=str(x["price"])) for x in queue
                ]
            continue
        yes = amount(outcome["yes_payout"])
        if yes > 1:
            raise EvidenceError("invalid_settlement")
        for lot in queue:
            payout = yes if lot["side"] == "yes" else ONE - yes
            pnl[ticker] += lot["left"] * (payout - lot["price"])
    resolved = {key: str(value) for key, value in pnl.items() if key not in unresolved}
    return {
        "resolved_pnl": resolved,
        "resolved_total": str(sum((Decimal(x) for x in resolved.values()), ZERO)),
        "open_lots": unresolved,
        "sales": sales,
        "invalid_comparison_markets": sorted(invalid),
        "fixed_future_entries_assumed": True,
        "exit_fees_are_estimates": True,
    }
