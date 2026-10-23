"""Export the bots' orders, fills and settlements to a PRIVATE GitHub repo.

Runs on the trading server from its own timer. It reads only the bot
journals (NBA, NFL and the spread maker, which already record every order,
fill, queue reading, price move after a fill, cancel and settlement there)
and the spread maker's shadow ledger; it makes no Kalshi request and needs
no Kalshi credentials. It writes nothing on the server. Journals
are read line by line, keeping only the fields exported, so memory stays
small even after a long season.

Output: daily CSV files per market and a summary, one row per order, fill and
settled market, using explicit column lists. Exchange order, client order and
fill identifiers are replaced by short one-way hashes (enough to join the
files); keys, balances and account details are never exported.

Pushing is opt-in (``--push``) and goes only to the repository named in
PRIVATE_EXPORT_REPO with the token in PRIVATE_EXPORT_TOKEN (a fine-grained
token limited to that repository's contents). It refuses unless GitHub
reports exactly that repository as private (not internal, not archived, no
GitHub Pages), never pushes to the public project repository, and never
follows redirects. All files go up as one commit, only when something
changed.

Run: python -m tools.export_private_fills            (counts only, no push)
     python -m tools.export_private_fills --out DIR  (write the files locally)
     python -m tools.export_private_fills --push     (server timer)
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PUBLIC_REPO = "akilatrades/sports-market-maker"
JOURNALS = {
    "nba": Path("/home/trader/prod-nba-auto/journal.jsonl"),
    "nfl": Path("/home/trader/prod-nfl-auto/journal.jsonl"),
    "spread": Path("/home/trader/prod-spread-auto/journal.jsonl"),
}
# The spread maker's simulated ledger: summarized separately, never added to
# live results.
SPREAD_SHADOW = Path("/home/trader/prod-spread-auto/shadow.jsonl")
# Copied from each order's intent record, when present. Nothing else is.
# NBA and NFL name some fields differently; both are kept.
INTENT_FIELDS = [
    "ticker",
    "player",
    "price_cents",
    "count",
    "cost",
    "game_id",
    "team",
    "tip_utc",
    "strategy_version",
    "model_version",
    "probability_source",
    "p_yes",  # NBA: probability used
    "p_yes_used",  # NFL: probability used
    "p_model_yes",  # NFL: model probability
    "book_n",
    "edge",
    "baseline_edge",
    "extra_maker_ticks",
    "net_edge_after_fee_bound",  # NBA
    "edge_after_fee_buffer",  # NFL
    "fee_bound_dollars",  # NBA
    "fee_buffer_dollars",  # NFL
    "model_probability_yes_at_entry",
    "sportsbook_probability_yes_at_entry",
    "kalshi_yes_bid_at_entry",
    "kalshi_yes_ask_at_entry",
    "book_updated_utc_at_entry",
    "model_generated_utc",  # NBA
    "model_made_utc",  # NFL
    "projected_minutes_at_entry",
    "projected_minutes_source_at_entry",
    "historical_minutes_baseline_at_entry",
    "lineup_confirmation_status_at_entry",
    "fee_type",
    "fee_multiplier",
]
ORDER_COLUMNS = [
    "market",
    "order_ref",
    "intent_utc",
    "side",
    *INTENT_FIELDS,
    "minutes_before_tip",
    "status",
    "accepted_utc",
    "first_queue_ahead",
    "last_queue_ahead",
    "cancel_requested_utc",
    "cancel_confirmed_utc",
    "cancel_reason",
    "cancel_veto",
    "emergency_cancel_utc",
    "filled_contracts",
    "first_fill_utc",
    "avg_fill_no_price",
    "fill_fees_dollars",
    "settled_utc",
    "market_settlement_net_profit_dollars",
]
MARKOUTS = [f"markout_{kind}_{h}m" for h in (5, 15, 60) for kind in ("mid", "bid")]
FILL_COLUMNS = [
    "market",
    "fill_ref",
    "order_ref",
    "fill_utc",
    "ticker",
    "side",
    "count",
    "no_price",
    "yes_price",
    "fee",
    "is_taker",
    "minutes_before_tip",
    "strategy_version",
    "probability_source",
    "price_cents",
    "edge",
    "net_edge_after_fee_bound",
    "edge_after_fee_buffer",
    "sportsbook_probability_yes_at_entry",
    "model_probability_yes_at_entry",
    "p_model_yes",
    *MARKOUTS,
]
SETTLEMENT_FIELDS = [
    "revenue_dollars",
    "yes_cost_dollars",
    "no_cost_dollars",
    "fee_dollars",
    "net_profit_dollars",
    "accounting_complete",
]
SETTLEMENT_COLUMNS = ["market", "ticker", "settled_utc", "strategy_version"]
SETTLEMENT_COLUMNS += SETTLEMENT_FIELDS
# Journal fields kept while reading, by event kind; everything else is
# dropped at once (memory) and can never reach the output.
KEEP = {
    "intent": {"utc", "client_order_id", *INTENT_FIELDS},
    "accepted": {"utc", "client_order_id", "order_id"},
    "unknown_outcome": {"client_order_id"},
    "reconciled_rejected": {"client_order_id", "utc"},
    "queue": {"order_id", "ahead"},
    "cancel_intent": {"utc", "order_id", "reason", "veto"},
    "cancel_accepted": {"utc", "order_id"},
    "emergency_cancel": {"utc", "order_id"},
    "fill": {
        "fill_id",
        "utc",
        "ticker",
        "order_id",
        "count",
        "yes_price",
        "no_price",
        "fee",
        "is_taker",
    },
    "markout": {"fill_id", "horizon_minutes", "mid_move_dollars", "bid_move_dollars"},
    "settlement": {"ticker", "utc", *SETTLEMENT_FIELDS},
}
# Never delete more than this share of a market's files in one run (a bad
# read must not wipe the archive; git history keeps everything anyway).
MAX_DELETE_SHARE = 0.25
# Split very large uploads into commits of about this size.
BATCH_BYTES = 4_000_000


class ExportError(RuntimeError):
    pass


def events(path, keep=None):
    """Slim journal events, one line at a time.

    Yields (kind, fields) for the kinds in ``keep`` (default KEEP). A line
    still being written at the end of the file is skipped, as are blank,
    non-JSON or non-object lines (counted in ``skipped``).
    """
    keep = keep or KEEP
    skipped = {"lines": 0}

    def generate():
        with path.open("r", encoding="utf-8", errors="replace", newline="\n") as f:
            for line in f:
                if not line.endswith("\n"):
                    break  # the writer is mid-line; the next export reads it
                try:
                    record = json.loads(line)
                except ValueError:
                    if line.strip():
                        skipped["lines"] += 1
                    continue
                if not isinstance(record, dict):
                    skipped["lines"] += 1
                    continue
                kind = record.get("event")
                if isinstance(kind, str) and kind in keep:
                    yield kind, {k: record[k] for k in keep[kind] if k in record}

    return generate(), skipped


def ref(value):
    """A short one-way hash: joins files without exposing exchange IDs."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:12] if value else ""


def _time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else None


def _day(value):
    stamp = _time(value)
    return stamp.astimezone(ET).strftime("%Y-%m-%d") if stamp else "undated"


def _minutes(earlier, later):
    a, b = _time(earlier), _time(later)
    return round((b - a).total_seconds() / 60, 1) if a and b else ""


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tables(market, stream):
    """(orders, fills, settlements, latest event time) for one bot's journal."""
    intents, status, accepted, client_of = {}, {}, {}, {}
    q_first, q_last, cancel, cancel_ok, emergency = {}, {}, {}, {}, {}
    fills, markouts, settlements = {}, {}, {}
    latest = None
    for kind, e in stream:
        stamp = _time(e.get("utc"))
        if stamp and (latest is None or stamp > latest):
            latest = stamp
        cid, oid = e.get("client_order_id"), e.get("order_id")
        oid = str(oid) if oid else None
        if kind == "intent" and cid:
            intents[cid] = e
            status.setdefault(cid, "intent_only")
        elif kind == "accepted" and cid:
            accepted[cid] = e.get("utc", "")
            status[cid] = "accepted"
            if oid:
                client_of[oid] = cid
        elif kind == "unknown_outcome" and cid:
            status[cid] = "unknown_outcome"
        elif kind == "reconciled_rejected" and cid:
            status[cid] = "reconciled_rejected"
        elif not oid:
            if kind == "markout" and e.get("fill_id"):
                markouts[(e["fill_id"], e.get("horizon_minutes"))] = e
            elif kind == "settlement" and e.get("ticker"):
                settlements[e["ticker"]] = e  # the latest record is the correction
        elif kind == "queue" and e.get("ahead") is not None:
            q_first.setdefault(oid, e["ahead"])
            q_last[oid] = e["ahead"]
        elif kind == "cancel_intent":
            cancel[oid] = e
        elif kind == "cancel_accepted":
            cancel_ok[oid] = e.get("utc", "")
        elif kind == "emergency_cancel":
            emergency[oid] = e.get("utc", "")
        elif kind == "fill":
            fills.setdefault(oid, []).append(e)
    order_of = {cid: oid for oid, cid in client_of.items()}
    intent_by_ticker = {i.get("ticker"): i for i in intents.values()}
    orders, fill_rows = [], []
    for cid, intent in intents.items():
        oid = order_of.get(cid)
        own = fills.get(oid, []) if oid else []
        counts = [_number(f.get("count")) for f in own]
        prices = [_number(f.get("no_price")) for f in own]
        priced = [(c, p) for c, p in zip(counts, prices) if c and p is not None]
        priced_count = sum(c for c, _ in priced)
        fees = [_number(f.get("fee")) for f in own]
        stop = cancel.get(oid, {})
        settled = settlements.get(intent.get("ticker"), {})
        orders.append(
            {
                "market": market,
                "order_ref": ref(cid),
                "intent_utc": intent.get("utc", ""),
                "side": "no",  # both bots post passive NO orders only
                **{k: intent.get(k, "") for k in INTENT_FIELDS},
                "minutes_before_tip": _minutes(
                    intent.get("utc"), intent.get("tip_utc")
                ),
                "status": status.get(cid, ""),
                "accepted_utc": accepted.get(cid, ""),
                "first_queue_ahead": q_first.get(oid, ""),
                "last_queue_ahead": q_last.get(oid, ""),
                "cancel_requested_utc": stop.get("utc", ""),
                "cancel_confirmed_utc": cancel_ok.get(oid, ""),
                "cancel_reason": stop.get("reason", ""),
                "cancel_veto": stop.get("veto", ""),
                "emergency_cancel_utc": emergency.get(oid, ""),
                "filled_contracts": sum(c for c in counts if c),
                "first_fill_utc": min((f.get("utc", "") for f in own), default=""),
                "avg_fill_no_price": round(
                    sum(c * p for c, p in priced) / priced_count, 4
                )
                if priced_count
                else "",
                "fill_fees_dollars": round(sum(f for f in fees if f is not None), 6)
                if own
                else "",
                "settled_utc": settled.get("utc", ""),
                "market_settlement_net_profit_dollars": settled.get(
                    "net_profit_dollars", ""
                ),
            }
        )
        for f in own:
            row = {
                "market": market,
                "fill_ref": ref(f.get("fill_id")),
                "order_ref": ref(cid),
                "fill_utc": f.get("utc", ""),
                "ticker": f.get("ticker", ""),
                "side": "no",
                "count": f.get("count", ""),
                "no_price": f.get("no_price", ""),
                "yes_price": f.get("yes_price", ""),
                "fee": f.get("fee", ""),
                "is_taker": f.get("is_taker", ""),
                "minutes_before_tip": _minutes(f.get("utc"), intent.get("tip_utc")),
            }
            for k in FILL_COLUMNS:
                if k not in row and k in INTENT_FIELDS:
                    row[k] = intent.get(k, "")
            for h in (5, 15, 60):
                m = markouts.get((f.get("fill_id"), h), {})
                row[f"markout_mid_{h}m"] = m.get("mid_move_dollars", "")
                row[f"markout_bid_{h}m"] = m.get("bid_move_dollars", "")
            fill_rows.append(row)
    settlement_rows = [
        {
            "market": market,
            "ticker": ticker,
            "settled_utc": s.get("utc", ""),
            "strategy_version": intent_by_ticker.get(ticker, {}).get(
                "strategy_version", ""
            ),
            **{k: s.get(k, "") for k in SETTLEMENT_FIELDS},
        }
        for ticker, s in settlements.items()
    ]
    return orders, fill_rows, settlement_rows, latest


# --- the spread maker ------------------------------------------------------------
# It buys YES or NO (up to 5 contracts) and holds to settlement; a YES+NO pair
# in one market closes at once, so its realized P&L comes from its fills (the
# same ledger its loss stops use), not from settlement records.
SPREAD_INTENT_FIELDS = [
    "ticker",
    "series",
    "event_ticker",
    "side",
    "price_cents",
    "count",
    "cost",
    "spread",
    "market_expiration_utc",
    "event_start_utc",  # v2 (pregame only): the start the order respected
    "expires_utc",
    "strategy_version",
]
SPREAD_FILL_FIELDS = [
    "fill_id",
    "order_id",
    "utc",
    "ticker",
    "side",
    "action",
    "outcome_side",
    "book_side",
    "count_fp",
    "count",
    "yes_price_dollars",
    "no_price_dollars",
    "fee_cost",
    "is_taker",
]
KEEP_SPREAD = {
    "intent": {"utc", "client_order_id", *SPREAD_INTENT_FIELDS},
    "accepted": {"utc", "client_order_id", "order_id", "reconciled"},
    "rejected_4xx": {"utc", "client_order_id", "http_status"},
    "reconciled_absent": {"utc", "client_order_id"},
    "unknown_outcome": {"utc", "client_order_id"},
    "cancel_intent": {"utc", "order_id", "reason"},
    "cancel_accepted": {"utc", "order_id", "reduced_by", "expected"},
    "cancel_moot": {"utc", "order_id"},
    "fill": set(SPREAD_FILL_FIELDS),
    "settlement": {"ticker", "utc", "market_result", "revenue_dollars"},
}
SPREAD_ORDER_COLUMNS = [
    "market",
    "order_ref",
    "intent_utc",
    *[f for f in SPREAD_INTENT_FIELDS],
    "hours_before_expiration",
    "minutes_before_start",
    "status",
    "accepted_utc",
    "reconciled",
    "cancel_requested_utc",
    "cancel_reason",
    "cancel_result",
    "cancel_reduced_by",
    "filled_contracts",
    "first_fill_utc",
    "avg_fill_price",
    "fill_fees_dollars",
]
SPREAD_FILL_COLUMNS = [
    "market",
    "fill_ref",
    "order_ref",
    "fill_utc",
    "ticker",
    "series",
    "side",
    "count",
    "price",
    "yes_price",
    "no_price",
    "fee",
    "is_taker",
    "price_cents",
    "spread",
]
SPREAD_SETTLEMENT_COLUMNS = [
    "market",
    "ticker",
    "settled_utc",
    "market_result",
    "revenue_dollars",
]
SPREAD_PNL_COLUMNS = ["market", "day", "realized_pnl_dollars", "cumulative_dollars"]


def spread_tables(stream, now=None):
    """(orders, fills, settlements, P&L by day, ledger, latest event time).

    The ledger is ``live.shared_account_risk.spread_ledger`` (the calculation
    the bot's loss stops use) on the fills and settlements the bot has copied
    into its journal. The bot copies them on every live pass, so while it is
    disarmed or stopped, later fills and settlements appear here only after
    its next live pass. Each event is held once (memory grows with orders).
    """
    from live.shared_account_risk import spread_ledger

    intents, status, accepted, reconciled, acceptances = {}, {}, {}, set(), []
    client_of, cancel, cancel_done, fills, settlements = {}, {}, {}, {}, {}
    latest = None
    for kind, e in stream:
        e["event"] = kind  # the ledger reads these same records
        stamp = _time(e.get("utc"))
        if stamp and (latest is None or stamp > latest):
            latest = stamp
        cid, oid = e.get("client_order_id"), e.get("order_id")
        oid = str(oid) if oid else None
        if kind == "intent" and cid:
            intents[cid] = e
            status.setdefault(cid, "intent_only")
        elif kind == "accepted" and cid:
            accepted[cid] = e.get("utc", "")
            status[cid] = "accepted"
            if e.get("reconciled"):
                reconciled.add(cid)
            if oid:
                client_of[oid] = cid
                acceptances.append(e)
        elif kind == "rejected_4xx" and cid:
            status[cid] = "refused_4xx"
        elif kind == "reconciled_absent" and cid:
            status[cid] = "never_placed_reconciled"
        elif kind == "unknown_outcome" and cid and status.get(cid) == "intent_only":
            status[cid] = "unknown_outcome"
        elif kind == "settlement" and e.get("ticker"):
            settlements[e["ticker"]] = e
        elif kind == "cancel_intent" and oid:
            cancel[oid] = e
        elif kind == "cancel_accepted" and oid:
            reduced, expected = _number(e.get("reduced_by")), _number(e.get("expected"))
            partial = expected is not None and (reduced is None or reduced < expected)
            cancel_done[oid] = (
                "partial" if partial else "canceled",
                e.get("reduced_by"),
            )
        elif kind == "cancel_moot" and oid:
            cancel_done[oid] = ("already_filled_or_expired", "")
        elif kind == "fill" and oid and e.get("fill_id"):
            fills.setdefault(oid, {})[str(e["fill_id"])] = e
    try:
        # Stamped by the newest journal event, not the clock, like the rest
        # of the export (identical input, identical files).
        records = [
            *intents.values(),
            *acceptances,
            *(f for per_order in fills.values() for f in per_order.values()),
            *settlements.values(),
        ]
        ledger = spread_ledger(records, [], [], now or latest or datetime.now(UTC))
    except Exception as error:  # report it; never invent a number
        ledger = {"unavailable": str(error)[:120]}
    order_of = {cid: oid for oid, cid in client_of.items()}
    orders, fill_rows = [], []
    for cid, intent in intents.items():
        oid = order_of.get(cid)
        side = intent.get("side", "")
        own = list(fills.get(oid, {}).values()) if oid else []
        priced, filled = [], 0.0
        for f in own:
            count = _number(
                f.get("count_fp") if f.get("count_fp") is not None else f.get("count")
            )
            price = _number(f.get(f"{side}_price_dollars"))
            filled += count or 0.0
            if count and price is not None:
                priced.append((count, price))
        stop = cancel.get(oid, {}) if oid else {}
        done = cancel_done.get(oid, ("", "")) if oid else ("", "")
        fees = [_number(f.get("fee_cost")) for f in own]
        orders.append(
            {
                "market": "spread",
                "order_ref": ref(cid),
                "intent_utc": intent.get("utc", ""),
                **{k: intent.get(k, "") for k in SPREAD_INTENT_FIELDS},
                "hours_before_expiration": round(
                    _minutes(intent.get("utc"), intent.get("market_expiration_utc"))
                    / 60,
                    2,
                )
                if _minutes(intent.get("utc"), intent.get("market_expiration_utc"))
                != ""
                else "",
                "minutes_before_start": (
                    round(_minutes(intent.get("utc"), intent.get("event_start_utc")), 1)
                    if _minutes(intent.get("utc"), intent.get("event_start_utc")) != ""
                    else ""
                ),
                "status": status.get(cid, ""),
                "accepted_utc": accepted.get(cid, ""),
                "reconciled": "yes" if cid in reconciled else "",
                "cancel_requested_utc": stop.get("utc", ""),
                "cancel_reason": stop.get("reason", ""),
                "cancel_result": done[0],
                "cancel_reduced_by": done[1],
                "filled_contracts": filled,
                "first_fill_utc": min((f.get("utc", "") for f in own), default=""),
                "avg_fill_price": round(
                    sum(c * p for c, p in priced) / sum(c for c, _ in priced), 4
                )
                if priced
                else "",
                "fill_fees_dollars": round(sum(f for f in fees if f is not None), 6)
                if own
                else "",
            }
        )
        for f in own:
            count = (
                f.get("count_fp") if f.get("count_fp") is not None else f.get("count")
            )
            fill_rows.append(
                {
                    "market": "spread",
                    "fill_ref": ref(f.get("fill_id")),
                    "order_ref": ref(cid),
                    "fill_utc": f.get("utc", ""),
                    "ticker": f.get("ticker") or intent.get("ticker", ""),
                    "series": intent.get("series", ""),
                    "side": side,
                    "count": count if count is not None else "",
                    "price": f.get(f"{side}_price_dollars", ""),
                    "yes_price": f.get("yes_price_dollars", ""),
                    "no_price": f.get("no_price_dollars", ""),
                    "fee": f.get("fee_cost", ""),
                    "is_taker": f.get("is_taker", ""),
                    "price_cents": intent.get("price_cents", ""),
                    "spread": intent.get("spread", ""),
                }
            )
    settlement_rows = [
        {
            "market": "spread",
            "ticker": ticker,
            "settled_utc": e.get("utc", ""),
            "market_result": e.get("market_result", ""),
            "revenue_dollars": e.get("revenue_dollars", ""),
        }
        for ticker, e in settlements.items()
    ]
    pnl_rows, running = [], 0.0
    for day, amount in (ledger.get("by_day") or {}).items():
        running += amount
        pnl_rows.append(
            {
                "market": "spread",
                "day": day,
                "realized_pnl_dollars": round(amount, 4),
                "cumulative_dollars": round(running, 4),
            }
        )
    return orders, fill_rows, settlement_rows, pnl_rows, ledger, latest


def shadow_expected(through, flow, size):
    """E[min(Binomial(through, flow), size)] (the spread maker's shadow rule)."""
    import math

    n = int(math.floor(through))
    if n <= 0 or size <= 0:
        return 0.0
    if flow >= 1:
        return float(min(n, size))
    pmf = math.exp(n * math.log1p(-flow))
    below, total = 0.0, 0.0
    for k in range(1, int(size) + 1):
        below += pmf
        total += max(0.0, 1.0 - below)
        pmf *= (n - (k - 1)) / k * flow / (1 - flow)
    return total


def live_fill_share(path, orders):
    """Our share of the contracts that public prints show traded at or
    through each finished live order's price (up to its size): the live
    measurement of the backtest's first-in-line assumption. The windows are
    scored by the bot from public data into its shadow file; the fills are
    this export's live order rows."""
    windows = {}
    stream, _ = events(path, {"live_window": {"client_order_id", "size", "through"}})
    for _, e in stream:
        if e.get("client_order_id"):
            windows[ref(e["client_order_id"])] = (
                _number(e.get("size")) or 0.0,
                _number(e.get("through")) or 0.0,
            )
    filled = {o["order_ref"]: _number(o.get("filled_contracts")) or 0.0 for o in orders}
    capacity = got = cautious = 0.0
    scored = traded = filled_when_traded = 0
    for order_ref, (size, through) in windows.items():
        if not (math.isfinite(size) and math.isfinite(through)):
            continue  # an unusable record is left out, never guessed
        scored += 1
        room = min(through, size)
        mine = min(filled.get(order_ref, 0.0), size)
        capacity += room
        got += min(mine, room)
        cautious += min(shadow_expected(through, 0.25, size), room)
        if through > 0:
            traded += 1
            filled_when_traded += mine > 0
    return {
        "orders_scored": scored,
        "orders_traded_through": traded,
        "orders_filled_when_traded_through": filled_when_traded,
        "first_in_line_contracts": round(capacity, 2),
        "filled_contracts": round(got, 2),
        "fill_share": round(got / capacity, 3) if capacity else None,
        "cautious_replay_share": round(cautious / capacity, 3) if capacity else None,
        "note": (
            "1.0 = the backtest's first-in-line assumption; cautious_replay_share = "
            "what the flow-share-0.25 replay would have filled on these same windows"
        ),
    }


def shadow_summary(path, flow=0.25):
    """Counts and simulated profit of the spread maker's shadow ledger.

    SIMULATED from public trade prints (first in line, and at flow share
    0.25); kept apart from live results and never added to them.
    """
    quotes, fills, results = {}, {}, {}
    keep = {
        "shadow_quote": {"id", "ticker", "side", "price_cents", "contracts"},
        "shadow_fill": {"id", "through"},
        "shadow_result": {"ticker", "result"},
    }
    stream, skipped = events(path, keep)
    for kind, e in stream:
        if kind == "shadow_quote" and e.get("id"):
            quotes[e["id"]] = e
        elif kind == "shadow_fill" and e.get("id"):
            fills[e["id"]] = _number(e.get("through")) or 0.0
        elif kind == "shadow_result" and e.get("ticker"):
            results[e["ticker"]] = e.get("result")
    first_n = first_pnl = flow_n = flow_pnl = 0.0
    filled = settled = 0
    for qid, through in fills.items():
        q = quotes.get(qid)
        if q is None or through < 1:
            continue
        filled += 1
        result = results.get(q.get("ticker"))
        if result not in ("yes", "no"):
            continue
        settled += 1
        size = int(_number(q.get("contracts")) or 1)
        pnl = (
            float(result == q.get("side")) - (_number(q.get("price_cents")) or 0) / 100
        )
        first = min(int(through), size)
        expected = shadow_expected(through, flow, size)
        first_n, first_pnl = first_n + first, first_pnl + first * pnl
        flow_n, flow_pnl = flow_n + expected, flow_pnl + expected * pnl
    return {
        "note": "SIMULATED from public trade prints; never add to live results",
        "quotes": len(quotes),
        "scored": len(fills),
        "filled_quotes": filled,
        "settled_filled_quotes": settled,
        "skipped_lines": skipped["lines"],
        "first_in_line": {
            "contracts": first_n,
            "dollars": round(first_pnl, 2),
            "cents_per_contract": round(100 * first_pnl / first_n, 2)
            if first_n
            else None,
        },
        f"flow_share_{flow:g}": {
            "contracts": round(flow_n, 2),
            "dollars": round(flow_pnl, 2),
            "cents_per_contract": round(100 * flow_pnl / flow_n, 2) if flow_n else None,
        },
    }


def _csv(columns, rows):
    out = io.StringIO()
    writer = csv.DictWriter(
        out, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for row in sorted(
        rows, key=lambda r: tuple(str(r.get(c, "")) for c in columns[:4])
    ):
        writer.writerow({c: "" if row.get(c) is None else row.get(c) for c in columns})
    return out.getvalue()


def build_files(journals, shadow=None):
    """({path in the private repo: text}, summary, markets read completely).

    The summary is stamped with the newest journal event, not the clock, so
    an export with nothing new produces identical files (and no commit).
    A market whose journal is missing or unreadable produces no files, and
    its existing files in the private repo are left alone.
    """
    files, summary, complete = {}, {"markets": {}}, set()
    for market, path in journals.items():
        if not path.exists():
            summary["markets"][market] = {"status": "journal_missing"}
            continue
        if market == "spread":
            try:
                stream, skipped = events(path, KEEP_SPREAD)
                orders, fills, settlements, pnl, ledger, latest = spread_tables(stream)
            except Exception as error:
                summary["markets"][market] = {"status": f"error_{type(error).__name__}"}
                continue
            if not ledger.get("unavailable"):
                # Only a complete read may remove files it no longer writes
                # (never the last good pnl_by_day.csv on a bad ledger).
                complete.add(market)
            for name, columns, rows, when in (
                ("orders", SPREAD_ORDER_COLUMNS, orders, "intent_utc"),
                ("fills", SPREAD_FILL_COLUMNS, fills, "fill_utc"),
                ("settlements", SPREAD_SETTLEMENT_COLUMNS, settlements, "settled_utc"),
            ):
                by_day = {}
                for row in rows:
                    by_day.setdefault(_day(row.get(when)), []).append(row)
                for day, day_rows in by_day.items():
                    files[f"data/spread/{name}/{day}.csv"] = _csv(columns, day_rows)
            if pnl:
                files["data/spread/pnl_by_day.csv"] = _csv(SPREAD_PNL_COLUMNS, pnl)
            versions = {}
            for o in orders:
                v = versions.setdefault(
                    str(o.get("strategy_version") or "unknown"),
                    {"orders": 0, "filled_orders": 0},
                )
                v["orders"] += 1
                v["filled_orders"] += 1 if o["filled_contracts"] else 0
            summary["markets"][market] = {
                "status": "ok",
                "data_through_utc": latest.astimezone(UTC).isoformat()
                if latest
                else None,
                "skipped_lines": skipped["lines"],
                "orders": len(orders),
                "accepted_orders": sum(o["status"] == "accepted" for o in orders),
                "never_placed_orders": sum(
                    o["status"] in ("refused_4xx", "never_placed_reconciled")
                    for o in orders
                ),
                "filled_orders": sum(1 for o in orders if o["filled_contracts"]),
                "filled_contracts": sum(o["filled_contracts"] or 0 for o in orders),
                "fills": len(fills),
                "settled_markets": len(settlements),
                "realized_pnl_dollars": None
                if ledger.get("unavailable")
                else round(ledger["cumulative"], 2),
                "realized_pnl_note": ledger.get("unavailable")
                or "From the bot's own fills: a YES+NO pair counts when its second "
                "leg fills, a held contract when its market settles (fees included).",
                "markets_still_held": None
                if ledger.get("unavailable")
                else len(ledger.get("open", {})),
                "by_strategy_version": versions,
            }
            if shadow is not None and Path(shadow).exists():
                try:
                    summary["markets"][market]["live_fill_share"] = live_fill_share(
                        Path(shadow), orders
                    )
                except Exception as error:
                    summary["markets"][market]["live_fill_share"] = {
                        "status": f"error_{type(error).__name__}"
                    }
            continue
        try:
            stream, skipped = events(path)
            orders, fills, settlements, latest = tables(market, stream)
        except Exception as error:  # one bad journal must not stop the other
            summary["markets"][market] = {"status": f"error_{type(error).__name__}"}
            continue
        complete.add(market)
        for name, columns, rows, when in (
            ("orders", ORDER_COLUMNS, orders, "intent_utc"),
            ("fills", FILL_COLUMNS, fills, "fill_utc"),
            ("settlements", SETTLEMENT_COLUMNS, settlements, "settled_utc"),
        ):
            by_day = {}
            for row in rows:
                by_day.setdefault(_day(row.get(when)), []).append(row)
            for day, day_rows in by_day.items():
                files[f"data/{market}/{name}/{day}.csv"] = _csv(columns, day_rows)
        profits = [_number(s.get("net_profit_dollars")) for s in settlements]
        versions = {}
        for o in orders:
            v = versions.setdefault(
                str(o.get("strategy_version") or "unknown"),
                {"orders": 0, "filled_orders": 0},
            )
            v["orders"] += 1
            v["filled_orders"] += 1 if o["filled_contracts"] else 0
        summary["markets"][market] = {
            "status": "ok",
            "data_through_utc": latest.astimezone(UTC).isoformat() if latest else None,
            "skipped_lines": skipped["lines"],
            "orders": len(orders),
            "accepted_orders": sum(o["status"] == "accepted" for o in orders),
            "filled_orders": sum(1 for o in orders if o["filled_contracts"]),
            "fills": len(fills),
            "settled_markets": len(settlements),
            "settled_net_profit_dollars": round(
                sum(p for p in profits if p is not None), 2
            )
            if settlements and all(p is not None for p in profits)
            else None,
            "by_strategy_version": versions,
        }
    if shadow is not None and Path(shadow).exists():
        try:
            summary["spread_shadow_simulated"] = shadow_summary(Path(shadow))
        except Exception as error:
            summary["spread_shadow_simulated"] = {
                "status": f"error_{type(error).__name__}"
            }
    files["data/summary.json"] = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    files["README.md"] = README
    return files, summary, complete


README = """# Private bot data (do not make this repository public)

Written every hour by `tools/export_private_fills.py` on the trading server,
from the bots' journals. Never edit by hand: the next export rewrites it.
These are LIVE results; never mix them with replays or simulations.

- `data/<nba|nfl>/orders/<day>.csv`: one row per order the bot submitted (or
  tried to), by Eastern date of submission. Entry evidence (price, sportsbook
  and model probability, edge, Kalshi bid/ask, minutes before tip-off), then
  what happened: accepted, queue position, cancel request/confirmation,
  reason and veto, filled contracts and price, fees.
  `market_settlement_net_profit_dollars` is the settled profit of the whole
  MARKET (ticker), repeated on each order for that market; the bots post at
  most one order per market, but never sum it across orders without checking.
- `data/<nba|nfl>/fills/<day>.csv`: one row per fill, with the entry evidence
  of its order and the NO-price moves 5, 15 and 60 minutes after the fill
  (positive = the market moved our way; fees not included).
- `data/<nba|nfl>/settlements/<day>.csv`: one row per settled market: revenue,
  costs, fees and net profit as Kalshi reported them.
- `data/summary.json`: counts and settled profit by market and rules version,
  up to the newest journal event (`data_through_utc`).

## Spread maker (`data/spread/`)

The third bot quotes BOTH sides (YES and NO, up to 5 contracts) of wide-spread
markets and holds fills to settlement.

- `orders/<day>.csv`: one row per order: side, price, contracts, the
  market's spread and series, hours before expected expiration, status
  (`accepted`, `refused_4xx`, `never_placed_reconciled`, `unknown_outcome`),
  cancel request and result (`canceled`, `partial` = some filled first,
  `already_filled_or_expired`), filled contracts, average fill price, fees.
- `fills/<day>.csv`: one row per fill, with the side bought and its price.
- `settlements/<day>.csv`: the market result and revenue Kalshi reported.
- `pnl_by_day.csv`: REALIZED P&L by Eastern day from the bot's own fills
  (the calculation its loss stops use): a YES+NO pair counts when its second
  leg fills; a contract still held counts when its market settles. Kalshi
  nets YES against NO, so settlement records alone miss closed pairs. It
  uses the fills and settlements the bot copies into its journal on every
  live pass; while the bot is disarmed or stopped, later settlements show up
  only after its next live pass (`markets_still_held` in the summary counts
  what is still open).
- `data/summary.json` → `markets.spread.live_fill_share`: of the contracts
  that public trade prints show traded at or through each finished live
  order's price (up to its size), the share the bot actually got. The
  backtest assumed 1.0 (first in line); `cautious_replay_share` is what the
  cautious replay (each such contract reaching us with probability 0.25)
  would have filled on the same windows. This is the measurement that says
  how much of the simulated edge is real.
- `data/summary.json` → `spread_shadow_simulated`: the shadow ledger's
  SIMULATED results (first in line, and at flow share 0.25). Compare it
  with the live numbers; never add the two together.

`order_ref` and `fill_ref` are one-way hashes of the exchange identifiers,
for joining the files. NBA and NFL name a few entry fields differently
(e.g. `p_yes` and `p_yes_used`); both columns exist, one is blank per market.
"""


# --- pushing ---------------------------------------------------------------------


def blob_sha(text):
    data = text.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could carry the token to another host: refuse them all."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ExportError(f"github_redirect_refused_{code}")


_OPENER = urllib.request.build_opener(_NoRedirect)


def urlopen(request, timeout):
    return _OPENER.open(request, timeout=timeout)


def github(method, path, token, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"https://api.github.com{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "smm-private-export",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        # Never print the response body or headers (tokens, data).
        raise ExportError(f"github_{method.lower()}_http_{error.code}") from None
    except URLError:
        raise ExportError(f"github_{method.lower()}_unreachable") from None


def check_private(info, repo):
    if str(info.get("full_name", "")).lower() != repo.lower():
        raise ExportError("refuse_repository_name_mismatch")
    if (
        info.get("private") is not True
        or info.get("visibility", "private") != "private"
    ):
        raise ExportError("refuse_repository_not_private")
    if info.get("has_pages"):
        raise ExportError("refuse_repository_has_pages")
    if info.get("archived"):
        raise ExportError("refuse_repository_archived")


def _remote_summary(call, repo, token, sha):
    blob = call("GET", f"/repos/{repo}/git/blobs/{sha}", token)
    try:
        return json.loads(base64.b64decode(blob.get("content", "")))
    except ValueError:
        return {}


def _went_backwards(new, old, markets):
    """Markets whose journal now shows fewer orders or older data than the
    export already in the repo (a replaced, truncated or restored journal)."""
    backwards = []
    for market in sorted(markets):
        a = new.get("markets", {}).get(market, {})
        b = old.get("markets", {}).get(market, {})
        if b.get("status") != "ok" or a.get("status") != "ok":
            continue
        fewer = (a.get("orders") or 0) < (b.get("orders") or 0)
        older = str(a.get("data_through_utc") or "") < str(
            b.get("data_through_utc") or ""
        )
        if fewer or older:
            backwards.append(market)
    return backwards


def push(files, repo, token, complete=(), call=None):
    """Upload changed files; returns (changed, deleted).

    Changes go up in as few commits as possible (one unless they exceed
    BATCH_BYTES), each saved before the next, so a huge rewrite finishes over
    several runs instead of failing every hour. Files under data/<market>/
    that this export no longer produces are deleted, but only for markets
    read completely this run, and never more than MAX_DELETE_SHARE of a
    market's files at once. If a journal shows fewer orders or older data
    than what is already exported, nothing is pushed at all.
    """
    call = call or github  # looked up at call time (tests replace it)
    if not token:
        raise ExportError("private_export_token_not_configured")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo or ""):
        raise ExportError("private_export_repo_invalid")
    if repo.lower() == PUBLIC_REPO.lower():
        raise ExportError("refuse_public_project_repository")
    info = call("GET", f"/repos/{repo}", token)
    check_private(info, repo)
    branch = info.get("default_branch") or "main"
    head = call("GET", f"/repos/{repo}/git/ref/heads/{branch}", token)["object"]["sha"]
    tree_sha = call("GET", f"/repos/{repo}/git/commits/{head}", token)["tree"]["sha"]
    listing = call("GET", f"/repos/{repo}/git/trees/{tree_sha}?recursive=1", token)
    if listing.get("truncated"):
        raise ExportError("tree_listing_truncated")
    remote = {
        t["path"]: t["sha"] for t in listing.get("tree", []) if t.get("type") == "blob"
    }
    summary = "data/summary.json"
    if summary in remote and summary in files:
        old = _remote_summary(call, repo, token, remote[summary])
        backwards = _went_backwards(json.loads(files[summary]), old, complete)
        if backwards:
            raise ExportError(f"journal_went_backwards_{'_'.join(backwards)}")
    changed = [
        p for p, text in sorted(files.items()) if remote.get(p) != blob_sha(text)
    ]
    deleted = []
    for market in sorted(complete):
        prefix = f"data/{market}/"
        mine = [p for p in remote if p.startswith(prefix)]
        stale = [p for p in mine if p not in files]
        if stale and len(stale) <= max(2, MAX_DELETE_SHARE * len(mine)):
            deleted += stale
    if not changed and not deleted:
        return 0, 0
    batches, size = [[]], 0
    for path in changed:
        n = len(files[path].encode())
        if batches[-1] and size + n > BATCH_BYTES:
            batches.append([])
            size = 0
        batches[-1].append(path)
        size += n
    for number, batch in enumerate(batches, start=1):
        entries = [
            {"path": p, "mode": "100644", "type": "blob", "content": files[p]}
            for p in batch
        ]
        if number == len(batches):
            entries += [
                {"path": p, "mode": "100644", "type": "blob", "sha": None}
                for p in deleted
            ]
        tree_sha = call(
            "POST",
            f"/repos/{repo}/git/trees",
            token,
            {"base_tree": tree_sha, "tree": entries},
        )["sha"]
        head = call(
            "POST",
            f"/repos/{repo}/git/commits",
            token,
            {
                "message": f"Export part {number}/{len(batches)}: "
                f"{len(batch)} changed"
                + (f", {len(deleted)} removed" if number == len(batches) else ""),
                "tree": tree_sha,
                "parents": [head],
            },
        )["sha"]
        call(
            "PATCH",
            f"/repos/{repo}/git/refs/heads/{branch}",
            token,
            {"sha": head, "force": False},
        )
    return len(changed), len(deleted)


def _inside_git_checkout(path):
    path = path.resolve()
    return any((p / ".git").exists() for p in (path, *path.parents))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--push", action="store_true", help="upload to PRIVATE_EXPORT_REPO"
    )
    parser.add_argument(
        "--out", type=Path, help="also write the files under this folder"
    )
    parser.add_argument("--nba-journal", type=Path, default=JOURNALS["nba"])
    parser.add_argument("--nfl-journal", type=Path, default=JOURNALS["nfl"])
    parser.add_argument("--spread-journal", type=Path, default=JOURNALS["spread"])
    parser.add_argument("--spread-shadow", type=Path, default=SPREAD_SHADOW)
    args = parser.parse_args(argv)
    try:
        if args.push and (
            args.nba_journal != JOURNALS["nba"]
            or args.nfl_journal != JOURNALS["nfl"]
            or args.spread_journal != JOURNALS["spread"]
            or args.spread_shadow != SPREAD_SHADOW
        ):
            # Pushing from another journal could overwrite the real export.
            raise ExportError("refuse_push_with_other_journals")
        if args.out and _inside_git_checkout(args.out):
            # A checkout might be committed and pushed somewhere public.
            raise ExportError("refuse_out_inside_git_checkout")
        files, summary, complete = build_files(
            {
                "nba": args.nba_journal,
                "nfl": args.nfl_journal,
                "spread": args.spread_journal,
            },
            shadow=args.spread_shadow,
        )
        if args.out:
            for path, text in files.items():
                target = args.out / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        counts = {
            m: {
                k: v
                for k, v in s.items()
                if k
                in ("status", "orders", "fills", "settled_markets", "skipped_lines")
            }
            for m, s in summary["markets"].items()
        }
        changed = None
        if args.push:
            changed = push(
                files,
                os.environ.get("PRIVATE_EXPORT_REPO", ""),
                os.environ.get("PRIVATE_EXPORT_TOKEN", ""),
                complete=complete,
            )
        print(
            json.dumps({"counts": counts, "changed_removed": changed}, sort_keys=True)
        )
    except Exception as error:
        # Error type and safe code only: never data, URLs or tokens.
        reason = str(error) if isinstance(error, ExportError) else type(error).__name__
        print(f"PRIVATE EXPORT FAILED: {reason}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
