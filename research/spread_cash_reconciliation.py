"""Reconcile signed spread cash and positions while funded trading is paused.

This independent report never changes the worker journal or frozen study.
Scalar settlements use the exchange's cash credit, never an invented YES/NO.
"""

from collections import defaultdict
from decimal import Decimal

from research.spread_forward_core import (
    EvidenceError, amount, digest, instant, normalize_fill, orders_from_journal, replay,
)


def reconciliation(events, raw_fills, settlements, positions, at):
    owned = orders_from_journal(events)
    ticker_intents = {o["ticker"]: o for o in owned.values()}
    approvals = {}
    for event in events:
        if event.get("event") != "external_close":
            continue
        raw = event.get("fill")
        if (not isinstance(raw, dict)
            or event.get("evidence") != "owner_verified_signed_manual_close_v1"
            or event.get("reason") != "owner_manual_cashout"
            or digest(raw) != event.get("fill_sha256")
            or not instant(raw["created_time"]) <= instant(event["utc"]) <= at):
            raise EvidenceError("invalid_external_close_approval")
        fid = raw.get("fill_id") or raw.get("trade_id")
        if not fid or fid in approvals or raw.get("order_id") in owned:
            raise EvidenceError("ambiguous_external_close")
        approvals[fid] = raw
    unique, errors = {}, defaultdict(set)
    for raw in raw_fills:
        ticker = raw.get("ticker") or raw.get("market_ticker")
        if ticker not in ticker_intents:
            continue
        fid = raw.get("fill_id") or raw.get("trade_id")
        if not fid:
            errors[ticker].add("missing_fill_identity")
            continue
        if fid in unique and unique[fid] != raw:
            errors[ticker].add("conflicting_signed_fill")
        unique[fid] = raw
    expected = {
        str(e["fill_id"]): e["ticker"] for e in events
        if e.get("event") == "fill" and e.get("fill_id") and e.get("order_id") in owned
    }
    expected.update({fid: r.get("ticker") or r.get("market_ticker") for fid, r in approvals.items()})
    for fid, ticker in expected.items():
        if fid not in unique:
            errors[ticker].add("journal_fill_missing_from_signed_history")
    fills = []
    for fid, raw in sorted(unique.items(), key=lambda x: (x[1]["created_time"], x[0])):
        ticker = raw.get("ticker") or raw.get("market_ticker")
        try:
            if raw.get("order_id") in owned:
                fill = normalize_fill(raw, owned[raw["order_id"]])
            elif fid in approvals:
                intent = dict(ticker_intents[ticker], side=raw["outcome_side"], price_cents=100)
                fill = normalize_fill(raw, intent)
                if normalize_fill(approvals[fid], intent) != fill:
                    raise EvidenceError("approved_close_disagrees_with_signed_fill")
                lots = replay(fills)["open_lots"].get(ticker, [])
                room = sum((amount(l["left"]) for l in lots if l["side"] != fill["side"]), Decimal(0))
                if amount(fill["quantity"]) > room:
                    raise EvidenceError("external_close_would_open_risk")
            else:
                raise EvidenceError("other_account_activity_in_spread_market")
            if instant(fill["at"]) > at:
                raise EvidenceError("future_fill")
            fills.append(fill)
        except (KeyError, ValueError, TypeError) as error:
            errors[ticker].add(str(error) if type(error) is EvidenceError else "malformed_fill")
    by_ticker = defaultdict(list)
    for f in fills:
        by_ticker[f["ticker"]].append(f)
    settled = {}
    for row in settlements:
        ticker = row.get("ticker") or row.get("market_ticker")
        if ticker not in ticker_intents:
            continue
        if ticker in settled and settled[ticker] != row:
            errors[ticker].add("conflicting_settlement")
        settled[ticker] = row
    held = {}
    for row in positions:
        ticker = row.get("ticker")
        if ticker not in ticker_intents:
            continue
        if ticker in held:
            errors[ticker].add("duplicate_position")
        held[ticker] = Decimal(str(row.get("position_fp", row.get("position", 0))))
        if not held[ticker].is_finite():
            errors[ticker].add("invalid_position")
    rows = []
    for ticker in sorted(set(by_ticker) | set(errors)):
        fs = by_ticker[ticker]
        actual = replay(fs)
        lots = actual["open_lots"].get(ticker, [])
        # Realized pairs are not included in replay's resolved map while a lot remains.
        cash = -sum((amount(f["quantity"]) * amount(f["price"]) + amount(f["fee"]) for f in fs), Decimal(0))
        total_quantity = sum((amount(f["quantity"]) for f in fs), Decimal(0))
        unpaired = sum((amount(l["left"]) for l in lots), Decimal(0))
        cash += (total_quantity - unpaired) / 2  # each opposite-side pair pays $1
        cost = sum((amount(l["left"]) * amount(l["price"]) for l in lots), Decimal(0))
        net = sum((amount(l["left"]) * (1 if l["side"] == "yes" else -1) for l in lots), Decimal(0))
        status, revenue, result = "open", None, None
        if ticker in settled:
            s = settled[ticker]
            try:
                when = instant(s["settled_time"])
                if not all(instant(f["at"]) <= when <= at for f in fs):
                    raise EvidenceError("settlement_timing_mismatch")
                result = s.get("market_result")
                revenue = amount(s["revenue_dollars"]) if s.get("revenue_dollars") is not None else amount(s["revenue"]) / 100
                if held.get(ticker, Decimal(0)) != 0:
                    raise EvidenceError("settled_position_not_flat")
                if result in ("yes", "no"):
                    payout = sum((amount(l["left"]) for l in lots if l["side"] == result), Decimal(0))
                    if abs(revenue - payout) > Decimal("0.005"):
                        raise EvidenceError("binary_cash_credit_mismatch")
                    status = "settled_binary_cash_verified"
                elif result == "scalar":
                    for side in ("yes", "no"):
                        expected_count = sum((amount(l["left"]) for l in lots if l["side"] == side), Decimal(0))
                        if amount(s[side + "_count_fp"]) != expected_count:
                            raise EvidenceError("scalar_position_quantity_mismatch")
                    if revenue > unpaired:
                        raise EvidenceError("scalar_cash_credit_out_of_bounds")
                    status = "settled_scalar_cash_verified"
                else:
                    raise EvidenceError("unknown_settlement_result")
                cash += revenue
                cost = Decimal(0)
            except (KeyError, ValueError, TypeError) as error:
                errors[ticker].add(str(error) if type(error) is EvidenceError else "malformed_settlement")
        elif held.get(ticker, Decimal(0)) != net:
            errors[ticker].add("unsettled_position_mismatch")
        if not lots and ticker not in settled:
            status = "closed_by_pairs"
        rows.append({
            "ticker": ticker, "fill_count": len(fs), "status": "needs_review" if errors[ticker] else status,
            "issues": sorted(errors[ticker]), "settlement_result": result,
            "settlement_cash_credit": str(revenue) if revenue is not None else None,
            "realized_pnl": str(cash + cost) if not errors[ticker] else None,
            "unsettled_cost": str(cost) if not errors[ticker] else None,
            "held_net_contracts": str(held.get(ticker, Decimal(0))),
        })
    valid = all(r["status"] != "needs_review" for r in rows)
    return {
        "scope": "all_spread_versions_and_previously_approved_manual_closes",
        "status": "reconciled" if valid else "needs_review", "markets": rows,
        "realized_pnl": str(sum((Decimal(r["realized_pnl"]) for r in rows), Decimal(0))) if valid else None,
        "unsettled_cost": str(sum((Decimal(r["unsettled_cost"]) for r in rows), Decimal(0))) if valid else None,
        "scalar_cash_reconciled": sum(r["status"] == "settled_scalar_cash_verified" for r in rows),
        "open_markets": sum(r["status"] == "open" for r in rows),
        "original_study_unchanged": True,
        "note": "Actual signed cash credits, FIFO pair netting and actual fill fees. Open cost is not a loss or a liquidation valuation. Scalar cash reconciliation does not assign a binary outcome or repair frozen shadow economics.",
    }
