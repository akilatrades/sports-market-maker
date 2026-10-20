"""Exchange-observed execution quality, separated from model/backtest claims.

These descriptive live metrics do not estimate future profitability. Unknown
fees, maker flags, timestamps or account reconciliation are never zeros.
"""

from datetime import datetime


def observed_execution(audit, events):
    if audit.get("status") != "verified_snapshot":
        return {"status": "unavailable"}
    rows = audit.get("orders")
    if not isinstance(rows, list) or not isinstance(events, list):
        return {"status": "unavailable"}
    intents = {
        e.get("ticker"): e
        for e in events
        if e.get("event") == "intent" and e.get("ticker")
    }
    filled = [
        row
        for row in rows
        if isinstance(row.get("filled_contracts"), (int, float))
        and row["filled_contracts"] > 0
    ]
    known_contracts = [
        row["filled_contracts"]
        for row in rows
        if isinstance(row.get("filled_contracts"), (int, float))
    ]
    all_contracts_known = len(known_contracts) == len(rows)
    contracts = round(sum(known_contracts), 4) if all_contracts_known else None
    maker_known = (
        all(row.get("maker_filled_contracts") is not None for row in filled)
        and all_contracts_known
    )
    maker = (
        round(sum(row["maker_filled_contracts"] for row in filled), 4)
        if maker_known
        else None
    )
    fee_known = all(row.get("fill_fees_dollars") is not None for row in filled)
    fees = (
        round(sum(row["fill_fees_dollars"] for row in filled), 6) if fee_known else None
    )

    observed_windows = []
    for row in filled:
        try:
            submitted = datetime.fromisoformat(row["submitted_utc"])
            first = datetime.fromisoformat(row["first_fill_utc"])
            elapsed = (first - submitted).total_seconds() / 60
            if elapsed >= 0:
                observed_windows.append(elapsed)
        except (TypeError, ValueError):
            continue

    # The intent field is the edge forecast at quote time, NOT a realized
    # win or an estimate of the chance to be filled.
    edges = []
    for row in filled:
        signal = intents.get(row.get("ticker"), {})
        edge = signal.get("net_edge_after_fee_bound")
        if edge is None or not isinstance(edge, (float, int)):
            break
        edges.append((row["filled_contracts"], float(edge)))
    edge_per_contract = (
        round(
            sum(count * edge for count, edge in edges)
            / sum(count for count, _ in edges),
            6,
        )
        if edges and len(edges) == len(filled)
        else None
    )
    closed = sum(
        row["state"]
        in {"fully_filled", "partially_filled_closed", "confirmed_unfilled"}
        for row in rows
    )
    closed_filled = sum(
        row["state"] in {"fully_filled", "partially_filled_closed"} for row in rows
    )
    return {
        "status": "observed_not_backtested",
        "accepted_orders": len(rows),
        "closed_orders_with_known_outcome": closed,
        "closed_orders_with_fills": closed_filled,
        "closed_order_fill_rate": round(closed_filled / closed, 4) if closed else None,
        "filled_orders": len(filled),
        "filled_contracts": contracts,
        "total_reported_fees_dollars": fees,
        "maker_contracts": maker,
        "maker_share": round(maker / contracts, 4)
        if maker is not None and contracts
        else None,
        "mean_minutes_to_first_fill": (
            round(sum(observed_windows) / len(observed_windows), 2)
            if len(observed_windows) == len(filled) and filled
            else None
        ),
        "model_estimated_net_edge_on_filled": edge_per_contract,
        "unreconciled_or_unknown_orders": audit.get("unknown_or_unreconciled"),
        "note": "Observed fill/fee/queue metrics only; model edge is a quote-time forecast, not realized profitability.",
    }
