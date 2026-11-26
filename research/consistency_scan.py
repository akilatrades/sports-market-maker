"""Test 2: cross-contract consistency on Kalshi, live and read-only
(RESEARCH_LOG.md, 2026-11-26, plan written before any result).

Each hour for 7 days: every open event with its markets (public data only).
Three riskless patterns, after taker fees (0.07 x P x (1 - P) per contract):

- sum: in a mutually exclusive event, buy NO on every outcome with a YES bid;
  pays at least (n - 1) dollars, riskless when the bids sum above 1 + fees.
  "buy every YES" (asks sum below 1) is listed apart: riskless only if the
  outcomes are exhaustive.
- threshold: one number, two thresholds: a higher threshold's YES bid above
  a lower one's YES ask plus fees.
- calendar: one question, two deadlines: the earlier deadline's YES bid above
  the later one's YES ask plus fees.

Top-of-book prices carry no size, so each finding is an upper bound.

    python -m research.consistency_scan --due
    python -m research.consistency_scan

Writes outputs/consistency/findings.csv (one row per finding per run) and
summary.json.
"""

import csv
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

OUT = Path("outputs/consistency")
DAYS = 7
MIN_MINUTES_BETWEEN = 50
MAX_PAGES = 250
BAR = {"edge": 0.02, "events": 20}
FIELDS = ["utc", "kind", "event_ticker", "tickers", "edge", "n", "detail"]
GREATER = {"greater", "greater_or_equal", "above"}
DEADLINE = re.compile(r"\b(before|by)\b", re.IGNORECASE)
DATES = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(st|nd|rd|th)?(,?\s+\d{4})?"
    r"|\b\d{1,2}/\d{1,2}(/\d{2,4})?|\b(20\d\d)\b|\b(q[1-4])\b",
    re.IGNORECASE,
)


def fee(p):
    return 0.07 * p * (1 - p)


def price(market, side):
    try:
        value = float(market.get(f"yes_{side}_dollars"))
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 1 else None


def live(markets):
    return [m for m in markets if str(m.get("status", "active")) in {"active", "open"}]


def sum_findings(event):
    out = []
    markets = live(event.get("markets") or [])
    if not event.get("mutually_exclusive") or len(markets) < 2:
        return out
    bids = [(m["ticker"], price(m, "bid")) for m in markets]
    bids = [(t, b) for t, b in bids if b and b > 0]
    if len(bids) >= 2:
        edge = sum(b for _, b in bids) - 1 - sum(fee(1 - b) for _, b in bids)
        if edge > 0:
            out.append(("sum_bids_above_1", [t for t, _ in bids], edge, len(bids), ""))
    asks = [(m["ticker"], price(m, "ask")) for m in markets]
    if all(a is not None and 0 < a < 1 for _, a in asks):
        edge = 1 - sum(a for _, a in asks) - sum(fee(a) for _, a in asks)
        if edge > 0:
            out.append(
                (
                    "sum_asks_below_1_if_exhaustive",
                    [t for t, _ in asks],
                    edge,
                    len(asks),
                    "",
                )
            )
    return out


def pair_findings(pairs, kind):
    """``pairs`` = [(lower, higher)] where higher's YES can only happen if
    lower's does (higher threshold / earlier deadline). Riskless when
    higher's bid exceeds lower's ask plus fees."""
    best = None
    for low, high in pairs:
        ask, bid = price(low, "ask"), price(high, "bid")
        if ask is None or bid is None or not (0 < ask < 1) or not (0 < bid < 1):
            continue
        edge = bid - ask - fee(ask) - fee(1 - bid)
        if edge > 0 and (best is None or edge > best[2]):
            best = (
                kind,
                [low["ticker"], high["ticker"]],
                edge,
                2,
                f"bid {bid:.2f} > ask {ask:.2f}",
            )
    return [best] if best else []


def threshold_findings(event):
    ms = []
    for m in live(event.get("markets") or []):
        try:
            strike = float(m.get("floor_strike"))
        except (TypeError, ValueError):
            continue
        if str(m.get("strike_type", "")).lower() in GREATER:
            ms.append((strike, m))
    ms.sort(key=lambda x: x[0])
    pairs = [(ms[i][1], ms[j][1]) for i in range(len(ms)) for j in range(i + 1, len(ms))
             if ms[j][0] > ms[i][0]]  # fmt: skip
    return pair_findings(pairs, "threshold")


def calendar_findings(event):
    groups = {}
    for m in live(event.get("markets") or []):
        title = f"{m.get('title', '')} {m.get('yes_sub_title', '')}"
        if not DEADLINE.search(title) or not DATES.search(title):
            continue
        stem = re.sub(r"\s+", " ", DATES.sub("", title)).strip().lower()
        try:
            close = datetime.fromisoformat(
                str(m.get("close_time")).replace("Z", "+00:00")
            )
        except ValueError:
            continue
        groups.setdefault(stem, []).append((close, m))
    out = []
    for items in groups.values():
        items.sort(key=lambda x: x[0])
        # Earlier deadline "happens" implies later deadline "happens".
        pairs = [(items[j][1], items[i][1]) for i in range(len(items)) for j in range(i + 1, len(items))
                 if items[j][0] > items[i][0]]  # fmt: skip
        out += pair_findings(pairs, "calendar")
    return out


def open_events(get_json, max_pages=MAX_PAGES):
    events, cursor = [], ""
    for _ in range(max_pages):
        params = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        page = get_json("/events", params) or {}
        events += page.get("events") or []
        cursor = page.get("cursor") or ""
        if not cursor:
            return events, True
    return events, False


def scan(events, utc):
    rows = []
    for e in events:
        for kind, tickers, edge, n, detail in (
            sum_findings(e) + threshold_findings(e) + calendar_findings(e)
        ):
            rows.append({"utc": utc, "kind": kind, "event_ticker": e.get("event_ticker", ""),
                         "tickers": " ".join(tickers), "edge": round(edge, 4), "n": n,
                         "detail": detail})  # fmt: skip
    return rows


def lasting(path, bar=BAR["edge"]):
    """Distinct events with an edge of at least ``bar`` in two consecutive
    runs (about an hour apart), by kind."""
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return {}
    runs = sorted({r["utc"] for r in rows})
    seen = {}
    for r in rows:
        if float(r["edge"]) >= bar:
            seen.setdefault((r["kind"], r["event_ticker"]), set()).add(
                runs.index(r["utc"])
            )
    out = {}
    for (kind, event), idx in seen.items():
        if any(i + 1 in idx for i in idx):
            out.setdefault(kind, set()).add(event)
    return {k: sorted(v) for k, v in out.items()}


def due(now, out=OUT):
    try:
        state = json.loads((out / "summary.json").read_text("utf-8"))
    except (OSError, ValueError):
        return "due"
    started = datetime.fromisoformat(state["started_utc"])
    if (now - started).days >= DAYS:
        return "done"
    last = datetime.fromisoformat(state["updated_utc"])
    return (
        "due" if (now - last).total_seconds() >= MIN_MINUTES_BETWEEN * 60 else "not due"
    )


def main(argv=None, out=OUT, get_json=None, now=None):
    argv = sys.argv[1:] if argv is None else argv
    out = Path(out)
    now = now or datetime.now(UTC)
    if "--due" in argv:
        print(due(now, out))
        return 0
    if get_json is None:
        from kalshi.api import get_json
    try:
        previous = json.loads((out / "summary.json").read_text("utf-8"))
    except (OSError, ValueError):
        previous = {}
    events, complete = open_events(get_json)
    utc = now.isoformat(timespec="minutes")
    rows = scan(events, utc)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "findings.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)
    held = lasting(path)
    riskless = {k: v for k, v in held.items() if k != "sum_asks_below_1_if_exhaustive"}
    distinct = len({e for v in riskless.values() for e in v})
    runs = previous.get("runs", 0) + 1
    summary = {
        "kind": "READ-ONLY scan of public Kalshi prices; top of book, no size; not a trade",
        "started_utc": previous.get("started_utc", now.isoformat(timespec="seconds")),
        "updated_utc": now.isoformat(timespec="seconds"),
        "runs": runs,
        "events_scanned_this_run": len(events),
        "listing_complete": complete,
        "mutually_exclusive_events": sum(bool(e.get("mutually_exclusive")) for e in events),
        "findings_this_run": {k: sum(r["kind"] == k for r in rows) for k in sorted({r["kind"] for r in rows})},
        "best_this_run": sorted(rows, key=lambda r: -r["edge"])[:10],
        "events_2c_in_consecutive_runs": {k: len(v) for k, v in held.items()},
        "examples_2c_in_consecutive_runs": {k: v[:10] for k, v in held.items()},
        "bar": BAR,
        "riskless_events_meeting_bar": distinct,
        "verdict": "worth building an executor" if distinct >= BAR["events"] else "not yet",
    }  # fmt: skip
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "best_this_run"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
