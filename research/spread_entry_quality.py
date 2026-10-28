"""Entry diagnostics for a new cohort, separate from the frozen exit study."""

import copy
from collections import defaultdict
from decimal import Decimal

from research.spread_forward_core import amount, consume, digest, instant

PROTOCOL = "spread-entry-quality-v1"


def entry_features(order, samples):
    """An after-pass book can never masquerade as pre-entry information."""
    before = instant(order["utc"])
    valid = [
        s
        for s in samples
        if s.get("valid")
        and s["ticker"] == order["ticker"]
        and instant(s["completed_at"]) <= before
        and 0 <= (before - instant(s["at"])).total_seconds() <= 120
    ]
    if not valid:
        return {"status": "missing_pre_pass_book", "depth_filter": None}
    sample = max(valid, key=lambda s: instant(s["completed_at"]))
    quantity = amount(order["count"], True)
    cost = amount(order["price_cents"]) / 100
    result = consume(
        copy.deepcopy(sample["external_book"][order["side"]]),
        quantity,
        amount(sample["fee_multiplier"]),
    )
    complete = amount(result["remaining"]) == 0
    # Conservative taker fee proxy on entry as well; this is a diagnostic bound.
    entry_fee = consume(
        [[str(cost), str(quantity)]], quantity, amount(sample["fee_multiplier"])
    )["fee_estimate"]
    gap = (
        (
            (
                quantity * cost
                + amount(entry_fee)
                - amount(result["proceeds"])
                + amount(result["fee_estimate"])
            )
            / quantity
        )
        if complete
        else None
    )
    return {
        "status": "observed",
        "snapshot_completed_at": sample["completed_at"],
        "snapshot_age_seconds": (before - instant(sample["at"])).total_seconds(),
        "full_quantity_exit_depth": complete,
        "immediate_exit_gap_per_contract": str(gap) if gap is not None else None,
        "depth_filter": bool(complete and gap <= Decimal("0.05")),
        "price": str(cost),
        "quantity": str(quantity),
    }


def game_key(event):
    """Group different series sharing the exchange event suffix (e.g. NBA)."""
    parts = str(event).split("-", 1)
    return parts[1] if len(parts) == 2 else str(event)


def exposure(positions, orders):
    """Conservative cash exposure, no correlation or opposite-side netting."""
    games = defaultdict(lambda: {"held_cost": Decimal(0), "resting_cost": Decimal(0)})
    unknown = 0
    for p in positions:
        try:
            raw = p.get("market_exposure_dollars")
            cost = (
                amount(raw) if raw is not None else amount(p["market_exposure"]) / 100
            )
            if cost:
                event = p.get("event_ticker") or "-".join(p["ticker"].split("-")[:2])
                games[game_key(event)]["held_cost"] += cost
        except (ValueError, KeyError, TypeError):
            unknown += 1
    for o in orders:
        event = "-".join(o["ticker"].split("-")[:2])
        games[game_key(event)]["resting_cost"] += amount(o["price"]) * amount(
            o["quantity"]
        )
    return {
        "by_game": {
            k: {
                **{name: str(v) for name, v in values.items()},
                "total_cost": str(sum(values.values())),
            }
            for k, values in sorted(games.items())
        },
        "unknown_position_rows": unknown,
        "grouping": "Exchange event suffix across series; unmatched identities remain separate. Cash cost, not outcome VaR.",
    }


def fill_report(fills, entries, checkpoints, outcomes):
    at_fill = {
        lot["fid"]: c
        for c in checkpoints
        if c.get("valid")
        for lot in c["lots"]
        if lot["horizon_seconds"] == 0
    }
    rows, groups = (
        [],
        defaultdict(
            lambda: {
                "fills": 0,
                "quantity": Decimal(0),
                "settled_quantity": Decimal(0),
                "hypothetical_hold_pnl": Decimal(0),
                "games": set(),
            }
        ),
    )
    for f in fills:
        entry = entries.get(f["oid"])
        if not entry:
            continue
        feature = entry["features"]
        upper_age = (instant(f["at"]) - instant(entry["utc"])).total_seconds()
        c = at_fill.get(f["fid"])
        loss = None
        if c:
            q = amount(f["quantity"])
            value = consume(
                copy.deepcopy(c["external_book"][f["side"]]),
                q,
                amount(c["fee_multiplier"]),
            )
            if amount(value["remaining"]) == 0:
                loss = str(
                    (
                        q * amount(f["price"])
                        + amount(f["fee"])
                        - amount(value["proceeds"])
                        + amount(value["fee_estimate"])
                    )
                    / q
                )
        passes = feature.get("depth_filter")
        labels = ["all_observed_fills"]
        if passes is not None:
            labels.append("depth_pass" if passes else "depth_fail")
        else:
            labels.append("missing_pre_pass_evidence")
        if passes and 0 <= upper_age <= 900:
            labels.append("depth_and_age_pass")
        for label in labels:
            g = groups[label]
            g["fills"] += 1
            g["quantity"] += amount(f["quantity"])
            g["games"].add(game_key(f["event_ticker"]))
            if outcomes.get(f["ticker"]) in ("yes", "no"):
                g["settled_quantity"] += amount(f["quantity"])
                g["hypothetical_hold_pnl"] += amount(f["quantity"]) * (
                    int(outcomes[f["ticker"]] == f["side"]) - amount(f["price"])
                ) - amount(f["fee"])
        rows.append(
            {
                "fill_ref": digest(f["fid"]),
                "order_ref": digest(f["oid"]),
                "ticker": f["ticker"],
                "game": game_key(f["event_ticker"]),
                "at": f["at"],
                "side": f["side"],
                "quantity": f["quantity"],
                "entry": feature,
                "pass_age_upper_seconds": upper_age,
                "at_fill_book_valid": c is not None,
                "at_fill_exit_gap_per_contract": loss,
            }
        )
    return {
        "fills": rows[-2000:],
        "fill_rows_truncated": max(0, len(rows) - 2000),
        "groups": {
            k: {
                name: len(v)
                if isinstance(v, set)
                else str(v)
                if isinstance(v, Decimal)
                else v
                for name, v in group.items()
            }
            for k, group in groups.items()
        },
        "interpretation": "Fixed observed-fill diagnostics, not a strategy backtest. Filtering changes queues, inventory and future orders. Missing books are unknown. Per-fill exit depth is not a simultaneous portfolio liquidation. Pass age is an upper bound, not exact quote age.",
    }
