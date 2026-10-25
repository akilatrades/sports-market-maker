"""Explicitly approved, reduction-only spread closes. No exchange/journal writes."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from kalshi.trading import TradingError

EVIDENCE = "owner_verified_signed_manual_close_v1"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def amount(value, positive=False):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise TradingError("Invalid external close amount: HALT") from None
    if not n.is_finite() or n < 0 or (positive and n <= 0):
        raise TradingError("Invalid external close amount: HALT")
    return n


def normalize(fill):
    try:
        fid = str(fill.get("fill_id") or fill.get("trade_id") or "")
        oid = str(fill.get("order_id") or "")
        ticker = fill.get("ticker") or fill.get("market_ticker")
        side = fill.get("outcome_side")
        if side not in ("yes", "no") or fill.get("book_side") != (
            "bid" if side == "yes" else "ask"
        ):
            raise ValueError("Canonical direction required")
        if not fid or not oid or not ticker:
            raise ValueError("Exchange identity required")
        when = datetime.fromisoformat(fill["created_time"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError("Timezone required")
        yes = amount(fill["yes_price_dollars"])
        no = amount(fill["no_price_dollars"])
        if yes > 1 or no > 1 or yes + no != 1:
            raise ValueError("Complementary prices required")
        quantity = amount(fill.get("count_fp", fill.get("count")), True)
        fee = amount(fill["fee_cost"])
        return {
            "fid": fid,
            "oid": oid,
            "ticker": ticker,
            "side": side,
            "when": when.isoformat(),
            "count": str(quantity.normalize()),
            "price": str((yes if side == "yes" else no).normalize()),
            "fee": str(fee.normalize()),
        }
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise TradingError("Unverifiable external close: HALT") from error


def approved(events, fills, now):
    intents = {
        e.get("client_order_id"): e for e in events if e.get("event") == "intent"
    }
    orders = {
        str(e.get("order_id")): intents[e.get("client_order_id")]
        for e in events
        if e.get("event") == "accepted" and e.get("client_order_id") in intents
    }
    tickers = {e["ticker"] for e in orders.values()}
    result = {}
    for event in events:
        if event.get("event") != "external_close":
            continue
        raw = event.get("fill")
        if (
            not isinstance(raw, dict)
            or event.get("evidence") != EVIDENCE
            or event.get("reason") != "owner_manual_cashout"
        ):
            raise TradingError("Unapproved external close: HALT")
        if event.get("fill_sha256") != fingerprint(raw):
            raise TradingError("External close evidence changed: HALT")
        snapshot_hash = event.get("snapshot_sha256")
        if (
            not isinstance(snapshot_hash, str)
            or len(snapshot_hash) != 64
            or any(c not in "0123456789abcdef" for c in snapshot_hash)
        ):
            raise TradingError("Invalid external snapshot identity: HALT")
        row = normalize(raw)
        if row["ticker"] not in tickers or row["oid"] in orders or row["fid"] in result:
            raise TradingError("Ambiguous external close ownership: HALT")
        try:
            at = datetime.fromisoformat(event["utc"].replace("Z", "+00:00"))
            filled = datetime.fromisoformat(row["when"])
            if at.tzinfo is None or not filled <= at <= now:
                raise ValueError("Invalid approval time")
        except (KeyError, TypeError, ValueError) as error:
            raise TradingError("Invalid external close time: HALT") from error
        result[row["fid"]] = row
    for fill in fills:
        fid = str(fill.get("fill_id") or fill.get("trade_id") or "")
        if fid in result and normalize(fill) != result[fid]:
            raise TradingError("External close disagrees with signed fill: HALT")
    return result


def recognized(fill, approvals):
    fid = str(fill.get("fill_id") or fill.get("trade_id") or "")
    return fid in approvals and normalize(fill) == approvals[fid]
