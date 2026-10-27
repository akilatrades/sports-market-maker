"""Offline diagnostics for a frozen spread study; no credentials or exchange calls.

Post-fill depth is a diagnostic, never an entry-time feature. The $1 event
budget is a fixed-fill risk sensitivity, not a replay of order placement.
"""

import argparse
import copy
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from research.spread_forward_core import HORIZONS, MAX_LATE, consume, instant

D = Decimal
EVENT_BUDGET = D("1.00")


def review(data, as_of):
    fills = data["fills"]
    report = data["report"]
    if report["invalid_markets"] or report["baseline"]["invalid_comparison_markets"]:
        raise ValueError("invalid_study_accounting")
    if as_of.tzinfo is None:
        raise ValueError("timezone_required")
    if len({f["fid"] for f in fills}) != len(fills):
        raise ValueError("duplicate_fill_identity")
    by_id = {f["fid"]: f for f in fills}
    evidence = {}
    for checkpoint in data["checkpoints"]:
        if not checkpoint.get("valid") or instant(checkpoint["at"]) > as_of:
            continue
        levels = copy.deepcopy(checkpoint["external_book"])
        for lot in sorted(checkpoint["lots"], key=lambda x: (x["fill_at"], x["fid"])):
            fill = by_id.get(lot["fid"])
            if fill is None:
                raise ValueError("unknown_checkpoint_fill")
            horizon = lot["horizon_seconds"]
            lag = (instant(checkpoint["at"]) - instant(fill["at"])).total_seconds()
            if horizon not in HORIZONS or not 0 <= lag - horizon <= MAX_LATE:
                continue
            key = (fill["fid"], horizon)
            if key in evidence:
                raise ValueError("duplicate_checkpoint")
            quantity = D(lot["remaining_actual"])
            original = D(fill["quantity"])
            if not 0 <= quantity <= original or original <= 0:
                raise ValueError("invalid_remaining_quantity")
            side = fill["side"]
            bids = levels[side]
            best = D(bids[0][0]) if bids else None
            sale = consume(bids, quantity, D(str(checkpoint["fee_multiplier"])))
            sold = D(sale["quantity"])
            # Unfilled units retain unknown economics; never value them at zero.
            full = D(sale["remaining"]) == 0
            net = (
                D(sale["proceeds"])
                - D(sale["fee_estimate"])
                - sold * D(fill["price"])
                - D(fill["fee"]) * sold / original
            )
            evidence[key] = {
                "fill_ref": fill["fid"],
                "event": fill["event_ticker"],
                "ticker": fill["ticker"],
                "horizon_seconds": horizon,
                "remaining_actual": str(quantity),
                "best_external_bid": str(best) if best is not None else None,
                "entry_price": fill["price"],
                "full_depth": full,
                "modeled_exit_pnl": str(net) if full and quantity else None,
                "sold_quantity": str(sold),
                "unfilled_quantity": sale["remaining"],
            }
    due = [
        (f["fid"], h)
        for f in fills
        for h in HORIZONS
        if (as_of - instant(f["at"])).total_seconds() > h + MAX_LATE
    ]
    valid = sum(key in evidence for key in due)
    rows = [evidence[key] for key in due if key in evidence]
    horizon_report = {}
    for h in HORIZONS:
        observed = [r for r in rows if r["horizon_seconds"] == h]
        complete = [r for r in observed if r["modeled_exit_pnl"] is not None]
        horizon_report[str(h)] = {
            "due": sum(key[1] == h for key in due),
            "valid": len(observed),
            "full_position_exits": len(complete),
            "positive_after_estimated_fees": sum(
                D(r["modeled_exit_pnl"]) > 0 for r in complete
            ),
            "modeled_pnl_full_positions_only": str(
                sum((D(r["modeled_exit_pnl"]) for r in complete), D(0))
            ),
        }
    # A scaled inventory can change FIFO netting. Refuse this simple sensitivity
    # when a market has multiple fills; do not pretend to model those paths.
    tickers = [f["ticker"] for f in fills]
    risk = {"status": "unsupported_multiple_fills_in_market"}
    if len(tickers) == len(set(tickers)):
        used = defaultdict(Decimal)
        baseline = report["baseline"]
        resolved = set(baseline["resolved_pnl"])
        pending_cost = D(0)
        capped = defaultdict(Decimal)
        actual = defaultdict(Decimal)
        allocations = []
        for fill in sorted(fills, key=lambda f: (instant(f["at"]), f["fid"])):
            event = fill["event_ticker"]
            cost = D(fill["quantity"]) * D(fill["price"]) + D(fill["fee"])
            if cost <= 0:
                raise ValueError("nonpositive_fill_cost")
            retained = min(cost, max(D(0), EVENT_BUDGET - used[event]))
            used[event] += retained
            fraction = retained / cost
            ticker = fill["ticker"]
            if ticker in resolved:
                pnl = D(baseline["resolved_pnl"][ticker])
                actual[event] += pnl
                capped[event] += pnl * fraction
            else:
                pending_cost += retained
            allocations.append(
                {
                    "event": event,
                    "fill_ref": fill["fid"],
                    "retained_cost": str(retained),
                }
            )
        risk = {
            "status": "fixed_fill_sensitivity_only",
            "event_budget": str(EVENT_BUDGET),
            "resolved_events": len(actual),
            "pending_entry_cost": str(pending_cost),
            "actual_resolved_pnl": str(sum(actual.values(), D(0))),
            "scaled_resolved_pnl": str(sum(capped.values(), D(0))),
            "allocations": allocations,
            "limitations": [
                "Uses proportional fractional fills and fees, not executable order sizes.",
                "Uses actual fills; omitted orders and inventory feedback are unknown.",
                "Budget includes entry fees and never recycles proceeds within an event.",
                "Pending positions are excluded from both realized totals.",
            ],
        }
    matched = report["matched_comparison_markets"]
    hold = sum((D(report["baseline"]["resolved_pnl"][t]) for t in matched), D(0))
    exits = {
        slip: str(sum((D(s["resolved_pnl"][t]) for t in matched), D(0)))
        for slip, s in report["shadow_scenarios_by_slippage_cents"].items()
    }
    return {
        "review_version": "spread-quality-review-v1",
        "source_generated_at": data["generated_at"],
        "as_of": as_of.isoformat(),
        "study_manifest": data["manifest"],
        "coverage": {
            "due": len(due),
            "valid": valid,
            "ratio": valid / len(due) if due else None,
        },
        "exit_diagnostics": horizon_report,
        "checkpoint_details": rows,
        "event_budget_sensitivity": risk,
        "matched_exit_comparison": {"hold": str(hold), "exits": exits},
        "entry_filter_test": {
            "status": "not_testable_from_this_export",
            "missing": "Time-aligned external depth before every submitted quote, including nonfills.",
            "reason": "Using post-fill depth to accept entries would use future information.",
        },
        "verdict": "exploratory_no_live_change_no_profitability_claim",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # Private input produces private output; never write into a git checkout.
    output_parent = args.out.parent.resolve()
    if any(
        (parent / ".git").exists() for parent in (output_parent, *output_parent.parents)
    ):
        raise SystemExit("refuse_private_output_inside_git_checkout")
    result = review(json.loads(args.input.read_text()), datetime.now(UTC))
    os.umask(0o077)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.is_symlink():
        raise SystemExit("refuse_symlink_output")
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.out.chmod(0o600)
    print("Private offline review written; no trading or study changes.")


if __name__ == "__main__":
    main()
