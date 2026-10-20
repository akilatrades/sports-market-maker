"""Append-only classification of manually reconciled failed production attempts.

Never infer rejection from an exchange query alone. The sole recognized
resolution is recorded by the guarded owner-side signed reconciliation tool.
Original intents still count against lifetime/daily budget and remain
ineligible for resubmission on the same ticker.
"""

from kalshi.trading import TradingError


def rejected_client_ids(events):
    intents = {
        e.get("client_order_id")
        for e in events
        if e.get("event") == "intent" and e.get("client_order_id")
    }
    unknown = {
        e.get("client_order_id")
        for e in events
        if e.get("event") == "unknown_outcome" and e.get("client_order_id")
    }
    accepted = {
        e.get("client_order_id")
        for e in events
        if e.get("event") == "accepted" and e.get("client_order_id")
    }
    resolved = set()
    for event in events:
        if event.get("event") != "reconciled_rejected":
            continue
        cid = event.get("client_order_id")
        if (
            not cid
            or cid not in intents
            or cid not in unknown
            or cid in accepted
            or cid in resolved
            or event.get("evidence")
            not in (
                "signed_get_no_order_fill_position_and_owner_ui",
                "signed_get_no_order_fill_position_and_explicit_shard_404",
            )
            or event.get("submission_http_status") != 404
            or not event.get("utc")
        ):
            raise TradingError("Invalid or duplicate rejected-order resolution: HALT")
        resolved.add(cid)
    return resolved
