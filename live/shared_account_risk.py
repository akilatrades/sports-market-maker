"""Cross-sport ownership and budget checks. No exchange writes.

Import from the two production workers only while their existing account_lock
is held. Absent, ambiguous or unowned account data must stop new entries.
"""
from datetime import datetime
from pathlib import Path
import json
import math
from zoneinfo import ZoneInfo

from kalshi.trading import TradingError

ROOT = Path("/home/trader")
LIMITS = {"lifetime": 100.0, "daily": 40.0, "active": 25.0}
LOCAL_DAY = ZoneInfo("America/New_York")


def journal_events(sport):
    if sport not in ("nfl", "nba"):
        raise TradingError("Invalid production cohort")
    path = ROOT / f"prod-{sport}-auto" / "journal.jsonl"
    if not path.exists():
        raise TradingError("Missing other-cohort production journal")
    raw = path.read_text()
    if raw and not raw.endswith("\n"):
        raise TradingError("Incomplete production journal")
    try:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (ValueError, TypeError) as error:
        raise TradingError("Invalid production journal") from error


def ownership(events_by_sport):
    orders, tickers, attempts = {}, {}, []
    client_ids = set()
    for sport in ("nfl", "nba"):
        events = events_by_sport[sport]
        intents = [e for e in events if e.get("event") == "intent"]
        accepted = [e for e in events if e.get("event") == "accepted"]
        if any(e.get("event") == "unknown_outcome" for e in events):
            raise TradingError("Ambiguous production order: HALT")
        by_id = {}
        for e in intents:
            cid, ticker = e.get("client_order_id"), e.get("ticker")
            if not cid or not ticker or cid in client_ids:
                raise TradingError("Duplicate or incomplete production intent")
            try:
                ts = datetime.fromisoformat(e["utc"])
                amount = float(e["cost"])
            except (ValueError, TypeError, KeyError) as error:
                raise TradingError("Invalid production intent") from error
            if ts.tzinfo is None or not math.isfinite(amount) or amount <= 0:
                raise TradingError("Invalid production intent fields")
            if ticker in tickers and tickers[ticker] != sport:
                raise TradingError("Overlapping markets between production bots")
            client_ids.add(cid)
            tickers[ticker] = sport
            by_id[cid] = e
            attempts.append(e)
        seen = set()
        for e in accepted:
            cid, oid = e.get("client_order_id"), e.get("order_id")
            if not oid or cid not in by_id or cid in seen or str(oid) in orders:
                raise TradingError("Invalid production acceptance")
            seen.add(cid)
            orders[str(oid)] = sport
        if seen != set(by_id):
            raise TradingError("Unreconciled production submission: HALT")
    return {"orders": orders, "tickers": tickers, "attempts": attempts}


def classify(resting, positions, owner):
    """Return only cohort-owned open orders/NO positions; fail on manual risk."""
    if not isinstance(resting, list) or not isinstance(positions, list):
        raise TradingError("Invalid production account snapshot")
    result = {s: {"resting": [], "held": []} for s in ("nfl", "nba")}
    for row in resting:
        sport = owner["orders"].get(str(row.get("order_id")))
        if sport not in result:
            raise TradingError("Unowned resting order: HALT")
        result[sport]["resting"].append(row)
    for row in positions:
        try:
            raw = row.get("position_fp", row.get("position"))
            qty = float(raw)
        except (TypeError, ValueError) as error:
            raise TradingError("Unreadable account position") from error
        if not math.isfinite(qty):
            raise TradingError("Nonfinite account position")
        if abs(qty) < 1e-9:
            continue
        ticker = row.get("market_ticker") or row.get("ticker")
        sport = owner["tickers"].get(ticker)
        if sport not in result or qty > 0:
            raise TradingError("Unowned or wrong-side account position: HALT")
        result[sport]["held"].append(ticker)
    return result


def room(owner, active_client_ids, cost, now):
    """Global admission requires previously verified active-order identities."""
    if now.tzinfo is None:
        raise TradingError("Current timestamp has no timezone")
    attempts = owner["attempts"]
    ids = {a["client_order_id"] for a in attempts}
    if not isinstance(active_client_ids, set) or not active_client_ids <= ids:
        raise TradingError("Unreconciled shared active capacity")
    from live.nfl_policy import reserve

    try:
        proposed = reserve(cost)
        lifetime = sum(reserve(a["cost"]) for a in attempts)
        active = sum(
            reserve(a["cost"]) for a in attempts
            if a["client_order_id"] in active_client_ids
        )
        local_date = now.astimezone(LOCAL_DAY).date()
        daily = sum(
            reserve(a["cost"]) for a in attempts
            if datetime.fromisoformat(a["utc"]).astimezone(LOCAL_DAY).date()
            == local_date
        )
    except (ValueError, TypeError, KeyError) as error:
        raise TradingError("Invalid shared risk input") from error
    return {
        "shared_lifetime": lifetime + proposed <= LIMITS["lifetime"] + 1e-9,
        "shared_daily": daily + proposed <= LIMITS["daily"] + 1e-9,
        "shared_active": active + proposed <= LIMITS["active"] + 1e-9,
    }
