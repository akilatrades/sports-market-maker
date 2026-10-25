"""Private research report. Incomplete evidence cannot produce an exit verdict."""

from collections import Counter, defaultdict
from decimal import Decimal

from research.spread_forward_core import HORIZONS, amount, instant, replay


def report(store):
    manifest = store.meta("manifest") or {}
    fills = store.values("fill")
    orders = store.values("cohort_order")
    samples = store.values("checkpoint")
    snapshots = store.values("account_snapshot")
    outcomes, settlement_errors = {}, set()
    open_before_settlement = replay(fills)["open_lots"]
    revenues = {}
    for snapshot in snapshots:
        for row in snapshot["settlements"]:
            ticker = row.get("ticker") or row.get("market_ticker")
            result = row.get("market_result")
            if result not in ("yes", "no"):
                if ticker:
                    settlement_errors.add(ticker)
                continue
            try:
                revenue = (
                    amount(row["revenue_dollars"])
                    if row.get("revenue_dollars") is not None
                    else amount(row.get("revenue")) / 100
                )
                expected = sum(
                    (
                        amount(lot["left"])
                        for lot in open_before_settlement.get(ticker, [])
                        if lot["side"] == result
                    ),
                    Decimal(0),
                )
                if abs(revenue - expected) > Decimal("0.005"):
                    settlement_errors.add(ticker)
                if ticker in revenues and revenue != revenues[ticker]:
                    settlement_errors.add(ticker)
                revenues[ticker] = revenue
            except ValueError:
                settlement_errors.add(ticker)
            outcome = {"yes_payout": "1" if result == "yes" else "0"}
            at = row.get("settled_time")
            if at:
                outcome["at"] = instant(at).isoformat()
            if ticker in outcomes and outcomes[ticker] != outcome:
                settlement_errors.add(ticker)
            outcomes[ticker] = outcome
    tickers = {f["ticker"] for f in fills}
    own_ids = {o["order_id"] for o in orders}
    contaminated = {
        r.get("ticker") or r.get("market_ticker")
        for r in store.values("raw_fill_version")
        if (r.get("ticker") or r.get("market_ticker")) in tickers
        and r.get("order_id") not in own_ids
    }
    invalid = set(contaminated) | (settlement_errors & tickers)
    covered = set()
    for sample in samples:
        if not sample.get("valid"):
            invalid.add(sample["ticker"])
        else:
            covered.update((r["fid"], r["horizon_seconds"]) for r in sample["lots"])
    expected = {(f["fid"], h) for f in fills for h in HORIZONS}
    # During collection future checkpoints count as pending, not zero returns.
    missing = expected - covered
    incomplete = {
        f["ticker"] for f in fills if any((f["fid"], h) in missing for h in HORIZONS)
    }
    actual = replay(fills, outcomes=outcomes)
    scenarios = {}
    for cents in (0, 1, 2):
        scenarios[str(cents)] = replay(
            fills, samples, outcomes, slippage=Decimal(cents) / 100
        )
    eligible = set(actual["resolved_pnl"]) - invalid - incomplete
    for scenario in scenarios.values():
        eligible &= set(scenario["resolved_pnl"])
        eligible -= set(scenario["invalid_comparison_markets"])
    event_of = {f["ticker"]: f["event_ticker"] for f in fills}
    events = defaultdict(Decimal)
    for ticker in set(actual["resolved_pnl"]) - invalid:
        events[event_of[ticker]] += Decimal(actual["resolved_pnl"][ticker])
    ranked = sorted(events.values(), reverse=True)
    concentration = {
        "resolved_events": len(events),
        "net_pnl": str(sum(ranked, Decimal(0))),
        "without_best_event": str(sum(ranked[1:], Decimal(0))),
        "without_best_three_events": str(sum(ranked[3:], Decimal(0))),
    }
    baseline_total = sum(
        (Decimal(actual["resolved_pnl"][t]) for t in eligible), Decimal(0)
    )
    comparisons = {
        cents: str(
            sum((Decimal(s["resolved_pnl"][t]) for t in eligible), Decimal(0))
            - baseline_total
        )
        for cents, s in scenarios.items()
    }
    filled_orders = {f["oid"] for f in fills}
    opportunity_keys, rejection_counts = set(), Counter()
    baseline_events = set(manifest.get("baseline_events", []))
    for c in store.iter_values("candidate"):
        rejection_counts[c["reason"]] += 1
        if (
            c.get("eligible")
            and manifest.get("start")
            and manifest["start"] <= c["at"] < manifest.get("end", "")
            and c.get("event_ticker") not in baseline_events
        ):
            opportunity_keys.update(
                (c["event_ticker"], c["ticker"], side) for side in ("yes", "no")
            )
    return {
        "protocol": manifest.get("protocol"),
        "start": manifest.get("start"),
        "end": manifest.get("end"),
        "accepted_orders": len(orders),
        "filled_orders": len(filled_orders),
        "not_yet_filled_orders": len(own_ids - filled_orders),
        "filled_contracts": str(
            sum((amount(f["quantity"]) for f in fills), Decimal(0))
        ),
        "actual_entry_fees": str(sum((amount(f["fee"]) for f in fills), Decimal(0))),
        "observed_unique_opportunities": len(opportunity_keys),
        "candidate_rejection_counts": dict(rejection_counts),
        "primary_dollars_per_opportunity": None,
        "primary_metric_status": "requires_end_of_window_complete_population_and_accounting_review",
        "concentration": concentration,
        "baseline": actual,
        "shadow_scenarios_by_slippage_cents": scenarios,
        "matched_comparison_markets": sorted(eligible),
        "matched_exit_minus_hold_pnl": comparisons,
        "invalid_markets": sorted(invalid),
        "incomplete_markets": sorted(incomplete),
        "checkpoint_coverage": {"valid": len(covered), "expected": len(expected)},
        "verdict": "collecting_evidence_no_automatic_strategy_change",
        "limitations": [
            "Requotes are dependent; report event-level results, not trade-count significance.",
            "Listed depth is not guaranteed executable; exits are estimates, never executed.",
            "Same future entry fills are assumed in both paths; feedback is not simulated.",
            "Unknown/scalar/disputed outcomes and contaminated markets require manual reconciliation.",
            "Independent surveys are not exact reproductions of bot opportunity selection.",
        ],
    }
