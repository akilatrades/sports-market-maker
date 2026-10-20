"""Shadow quote ladder for research only; never authorizes trading.

Compare passive buy-NO prices while preserving estimated fee-adjusted edge.
There is no fill-probability model yet: we do not call the most aggressive
price "optimal" or instruct production workers to post it.
"""

import math

MIN_REMAINING_EDGE = 0.03


def shadow_quotes(candidate, *, max_ticks=2):
    """Return up to 3 eligible non-crossing whole-cent quotes.

    The candidate's edge is already after the research fee buffer. Each extra
    cent paid removes one cent of quoted advantage. The trader must still
    perform its real signed fee, risk, kickoff and fresh-book checks.
    """
    try:
        base = float(candidate.price)
        edge = float(candidate.edge)
        yes_bid = float(candidate.yes_bid)
        yes_ask = float(candidate.yes_ask)
    except (AttributeError, TypeError, ValueError):
        return {"status": "unknown_input", "alternatives": []}
    values = (base, edge, yes_bid, yes_ask)
    if not all(math.isfinite(v) for v in values):
        return {"status": "unknown_input", "alternatives": []}
    if not 0 < yes_bid < yes_ask < 1:
        return {"status": "invalid_spread", "alternatives": []}
    cents = round(100 * base)
    if abs(100 * base - cents) > 1e-5:
        return {"status": "not_whole_cent", "alternatives": []}
    # If the baseline cannot rest as a maker, evaluating price increases is
    # nonsensical. A buy NO at p corresponds to a sell YES ask at 1-p.
    if not 10 <= cents <= 90 or 1 - base <= yes_bid + 1e-9:
        return {"status": "baseline_not_passive", "alternatives": []}
    options = []
    for ticks in range(max_ticks + 1):
        price_cents = cents + ticks
        price = price_cents / 100
        residual = edge - ticks / 100
        if (
            price_cents > 90
            or residual < MIN_REMAINING_EDGE - 1e-9
            or 1 - price <= yes_bid + 1e-9
        ):
            continue
        options.append(
            {
                "improvement_ticks": ticks,
                "no_bid_cents": price_cents,
                "estimated_edge_after_price_cents": round(100 * residual, 2),
                "maker_only_on_snapshot": True,
            }
        )
    return {
        "status": "shadow_only",
        "baseline_no_bid_cents": cents,
        "alternatives": options,
        "note": "Quoted edge, not expected P&L. Fill odds/fees must be validated separately.",
    }
