"""Transparent independent scan labels; never a substitute for worker decisions."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from research.spread_forward_core import instant


def candidate(market, series, config, cache, at):
    """Classify every listed market using frozen policy and observed start cache.

    This is a separate observation time. Capacity/queue/race decisions of the
    live worker are not inferred; its real journal and scan report are retained.
    """
    p = config
    row = {
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "series": series,
        "at": at.isoformat(),
        "source": "independent_survey",
        "eligible": False,
        "reason": "unknown",
        "worker_no_quote_reason": "unobserved",
    }
    ticker, event = row["ticker"], row["event_ticker"]
    if not ticker or not event:
        return dict(row, reason="missing_identity")
    if ticker.startswith(tuple(p["EXCLUDED_PREFIXES"])):
        return dict(row, reason="other_strategy_prefix")
    if series in p["MAKER_FEE_SERIES"]:
        return dict(row, reason="excluded_maker_fee_series")
    if series in p["NO_START_SERIES"]:
        return dict(row, reason="no_start_series")
    if market.get("status") not in ("active", "open"):
        return dict(row, reason="market_not_open")
    try:
        expires = instant(market["expected_expiration_time"])
    except (KeyError, ValueError):
        return dict(row, reason="unknown_expiry")
    hours = (expires - at).total_seconds() / 3600
    if not p["WINDOW_HOURS"][0] <= hours <= p["WINDOW_HOURS"][1]:
        return dict(row, reason="outside_expiry_window")
    try:
        bid = Decimal(str(market["yes_bid_dollars"])) * 100
        ask = Decimal(str(market["yes_ask_dollars"])) * 100
        if not (
            bid.is_finite()
            and ask.is_finite()
            and bid == int(bid)
            and ask == int(ask)
            and 0 < bid < ask < 100
        ):
            return dict(row, reason="invalid_or_missing_two_sided_quote")
    except (KeyError, ValueError, ArithmeticError):
        return dict(row, reason="invalid_or_missing_two_sided_quote")
    if ask - bid < p["MIN_SPREAD_CENTS"]:
        return dict(row, reason="spread_too_narrow")
    yes, no = int(bid) + 1, 101 - int(ask)
    lo, hi = p["PRICE_RANGE_CENTS"]
    if not (lo <= yes <= hi and lo <= no <= hi):
        return dict(row, reason="price_outside_range")
    starts = []
    match = re.match(
        r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})(?=[A-Z])", event
    )
    if match:
        yy, month, day, hour, minute = match.groups()
        months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
        try:
            local = datetime(
                2000 + int(yy),
                months.index(month) + 1,
                int(day),
                int(hour),
                int(minute),
                tzinfo=ZoneInfo("America/New_York"),
            )
            starts.append(min(local.replace(fold=f).astimezone(UTC) for f in (0, 1)))
        except ValueError:
            pass
    timed = bool(starts)
    milestones = []
    hit = cache.get(event, {})
    try:
        checked = instant(hit["checked"])
        if -300 <= (at - checked).total_seconds() <= p["START_CACHE_MINUTES"] * 60:
            milestones = [
                (instant(pair[0]), pair[1]) for pair in hit.get("milestones", [])
            ]
    except (KeyError, ValueError, TypeError, IndexError):
        milestones = []
    if not timed:
        trusted = set(p["TRUSTED_MILESTONE_TYPES"]) - set(
            p["NEVER_TRUSTED_MILESTONE_TYPES"]
        )
        since = at - timedelta(days=p["MILESTONE_TRUST_DAYS"])
        for kind, detail in cache.get("types", {}).items():
            if any(
                instant(value) >= since for value in detail.get("late", {}).values()
            ):
                trusted.discard(kind)
        starts.extend(start for start, kind in milestones if kind in trusted)
        suspended = cache.get("offset_late", {}).get(series)
        gap = p["SERIES_START_OFFSET_HOURS"].get(series)
        if gap is not None and (
            not suspended
            or instant(suspended) < at - timedelta(days=p["OFFSET_SUSPEND_DAYS"])
        ):
            starts.append(
                expires - timedelta(hours=gap, minutes=p["START_OFFSET_MARGIN_MINUTES"])
            )
    if not starts:
        return dict(row, reason="event_start_unknown")
    starts.extend(start for start, _ in milestones)
    remembered = cache.get("earliest", {}).get(event)
    if remembered and instant(remembered) >= at - timedelta(days=2):
        starts.append(instant(remembered))
    start = min(starts)
    lead = (start - at).total_seconds() / 60
    row.update(
        event_start_utc=start.isoformat(),
        yes_price_cents=yes,
        no_price_cents=no,
        spread_cents=int(ask - bid),
    )
    if lead < p["MIN_LEAD_MINUTES"]:
        return dict(row, reason="too_close_to_event_start")
    return dict(row, eligible=True, reason="observed_entry_eligible")
