"""Append-only classification of manually reconciled failed production attempts.

Never infer rejection from an exchange query alone. The sole recognized
resolution is recorded by the guarded owner-side signed reconciliation tool.
Original intents still count against lifetime/daily budget and remain
ineligible for resubmission on the same ticker.

Resolutions recognized for NBA and NFL submissions with an unknown outcome:

* ``reconciled_rejected`` with one of the two 20 October incident evidences
  (an HTTP 404 seen on the original POST, plus signed reads), or with
  ``ABSENT_EVIDENCE``: the owner's ``live.prod_nba_auto --reconcile``
  (2026-11-08) found no order with the client id in any status on its
  market, no fill there from an order outside the journal and no position
  there, after the order's own expiry (tip-off) and at least 10 minutes
  after the intent.
* ``accepted`` marked ``reconciled: FOUND_MARK``, written after the
  ``unknown_outcome``: the same command found the order on the exchange
  (``reconciled_found_ids``).
"""

from kalshi.trading import TradingError

INCIDENT_EVIDENCE = (
    "signed_get_no_order_fill_position_and_owner_ui",
    "signed_get_no_order_fill_position_and_explicit_shard_404",
)
ABSENT_EVIDENCE = "owner_signed_get_absent_after_expiry"
ABSENT_MIN_AGE_SECONDS = 600
FOUND_MARK = "owner_signed_lookup"


def _valid(event):
    evidence = event.get("evidence")
    if evidence in INCIDENT_EVIDENCE:
        return event.get("submission_http_status") == 404
    if evidence == ABSENT_EVIDENCE:
        age = event.get("intent_age_seconds")
        return (
            type(age) is int
            and age >= ABSENT_MIN_AGE_SECONDS
            and event.get("after_expiry") is True
        )
    return False


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
            or not _valid(event)
            or not event.get("utc")
        ):
            raise TradingError("Invalid or duplicate rejected-order resolution: HALT")
        resolved.add(cid)
    return resolved


def reconciled_found_ids(events):
    """Submissions with an unknown outcome that the owner's signed lookup
    later found on the exchange: an ``accepted`` event marked ``FOUND_MARK``
    after the ``unknown_outcome``. Any other acceptance of an unknown
    submission (earlier, or unmarked) resolves nothing."""
    unknown, found = set(), set()
    for event in events:
        kind, cid = event.get("event"), event.get("client_order_id")
        if not cid:
            continue
        if kind == "unknown_outcome":
            unknown.add(cid)
        elif kind == "accepted" and event.get("reconciled") == FOUND_MARK:
            if cid in unknown:
                found.add(cid)
    return found
