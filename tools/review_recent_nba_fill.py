"""Private NBA first-fill audit; prints ONLY a bounded, de-identified summary.

This runs over SSH on the DigitalOcean host, from GitHub Actions, without
deploying trading code or requiring any Kalshi write permission. It reads the
already-running GET-only localhost account dashboard and the private NBA
order journal. Never print raw snapshot, ticker, market, balance, user IDs,
order IDs, trade IDs, or per-market settlement data into public CI logs.
"""

import json
import math
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DASHBOARD = "http://127.0.0.1:8765/api/account"
JOURNAL = Path("/home/trader/prod-nba-auto/journal.jsonl")
MAX_AGE_SECONDS = 180
MAX_RECENT_FILLS = 3
FILLED_STATES = {
    "fully_filled",
    "partially_filled_resting",
    "partially_filled_closed",
}


# Public, coarse labels for the strategy version that placed an order.
GENERATIONS = {
    "nba-no-v4-smaller-orders-edge3-baseline": "baseline_v4",
    "nba-no-v5-one-contract-breadth": "breadth_v5",
    "nba-no-v6-three-contracts": "three_contracts_v6",
}


def parse_time(value):
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts.astimezone(UTC) if ts.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def finite(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def rounded(value, digits=3):
    n = finite(value)
    return round(n, digits) if n is not None else None


def cents(value):
    n = finite(value)
    return round(n * 100, 2) if n is not None else None


def read_events(path):
    if not path.is_file():
        raise ValueError("NBA journal unavailable")
    raw = path.read_text(encoding="utf-8")
    if raw and not raw.endswith("\n"):
        raise ValueError("NBA journal append in progress")
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not all(isinstance(event, dict) for event in events):
        raise ValueError("Malformed NBA journal")
    return events


def summarize(snapshot, events, now):
    """Join signed order-audit rows to their original intent, without identities."""
    as_of = parse_time(snapshot.get("updated_utc"))
    if (
        snapshot.get("status") != "ok"
        or as_of is None
        or not -60 <= (now - as_of).total_seconds() <= MAX_AGE_SECONDS
    ):
        raise ValueError("Account dashboard unavailable or stale")
    audit = snapshot.get("order_audit", {}).get("nba", {})
    if audit.get("status") != "verified_snapshot":
        raise ValueError("Signed NBA order audit unavailable")
    rows = audit.get("orders")
    if not isinstance(rows, list):
        raise ValueError("NBA order list unavailable")

    intents = {}
    owned_orders = {}
    journal_fills = {}
    marks = {}
    for event in events:
        kind = event.get("event")
        if kind == "intent":
            cid = event.get("client_order_id")
            if not cid or cid in intents:
                raise ValueError("Ambiguous NBA intent record")
            intents[cid] = event
        elif kind == "accepted":
            oid = event.get("order_id")
            cid = event.get("client_order_id")
            if not oid or oid in owned_orders or cid not in intents:
                raise ValueError("Ambiguous NBA acceptance")
            owned_orders[oid] = intents[cid]
        elif kind == "fill":
            fid = event.get("fill_id")
            if fid and event.get("order_id"):
                journal_fills.setdefault(event["order_id"], set()).add(fid)
        elif kind == "markout" and event.get("fill_id"):
            marks.setdefault(event["fill_id"], []).append(event)

    filled = [
        row
        for row in rows
        if isinstance(row, dict) and (finite(row.get("filled_contracts")) or 0) > 0
    ]
    filled.sort(key=lambda row: row.get("first_fill_utc") or "", reverse=True)
    result = {
        "source": "fresh_private_dashboard_signed_exchange_read_and_local_NBA_journal",
        "as_of_utc": as_of.isoformat(timespec="seconds"),
        "exchange_nba_accepted_orders": audit.get("accepted_orders"),
        "exchange_nba_filled_orders": len(filled),
        "exchange_nba_fill_records": audit.get("fill_records"),
        "unreconciled_or_unknown_orders": audit.get("unknown_or_unreconciled"),
        "no_filled_owned_orders": len(filled) == 0,
        "latest_fills": [],
    }

    pnl = snapshot.get("live_pnl", {}).get("nba", {})
    result["cohort_realized_pnl"] = {
        "status": pnl.get("status"),
        "settled_markets": pnl.get("settled_markets"),
        "total_net_dollars": rounded(pnl.get("settled_profit_dollars"), 2)
        if pnl.get("status") == "verified"
        else None,
        "note": "Cohort-wide, not attributable to one fill without settlement join",
    }
    validation = snapshot.get("nba_validation", {})
    result["forward_validation"] = {
        "status": validation.get("status"),
        "independent_games_filled": validation.get("independent_games_filled"),
        "proof_of_edge": False,
    }

    for row in filled[:MAX_RECENT_FILLS]:
        oid = row.get("order_id")
        if oid not in owned_orders:
            raise ValueError("Exchange NBA fill has no matching strategy intent")
        intent = owned_orders[oid]
        placed = parse_time(row.get("submitted_utc")) or parse_time(intent.get("utc"))
        filled_at = parse_time(row.get("first_fill_utc"))
        tip = parse_time(intent.get("tip_utc"))
        expiry = None
        try:
            if intent.get("expiration_ts") is not None:
                expiry = datetime.fromtimestamp(int(intent["expiration_ts"]), UTC)
        except (ValueError, TypeError, OverflowError, OSError):
            pass
        qty = finite(row.get("filled_contracts"))
        maker_qty = finite(row.get("maker_filled_contracts"))
        maker = (
            "all_maker"
            if maker_qty is not None and qty is not None and abs(maker_qty - qty) < 1e-6
            else "part_maker"
            if maker_qty is not None and maker_qty > 0
            else "not_verified_maker"
        )
        by_horizon = {}
        for fid in journal_fills.get(oid, set()):
            for mark in marks.get(fid, []):
                horizon = finite(mark.get("horizon_minutes"))
                if horizon not in (5, 15, 60):
                    continue
                key = f"{int(horizon)}m"
                if key in by_horizon:
                    continue
                by_horizon[key] = {
                    "NO_mid_move_cents_before_fees": cents(
                        mark.get("mid_move_dollars")
                    ),
                    "NO_executable_bid_move_cents_before_fees": cents(
                        mark.get("bid_move_dollars")
                    ),
                    "observation_issue": mark.get("issue")
                    if mark.get("issue")
                    in {
                        "missed_observation_window",
                        "quote_unavailable",
                        "invalid_quote",
                    }
                    else None,
                }

        result["latest_fills"].append(
            {
                "fill_time_utc": filled_at.isoformat(timespec="minutes")
                if filled_at
                else None,
                "state": row.get("state"),
                "exchange_order_status": row.get("exchange_status"),
                "filled_contracts": qty,
                "ordered_contracts": finite(row.get("ordered_contracts")),
                "time_to_first_fill_minutes": round(
                    (filled_at - placed).total_seconds() / 60, 2
                )
                if placed and filled_at and filled_at >= placed
                else None,
                "hours_to_tip_at_post": round((tip - placed).total_seconds() / 3600, 3)
                if placed and tip
                else None,
                "exchange_expiry_matches_scheduled_tip": (
                    abs((expiry - tip).total_seconds()) <= 1 if expiry and tip else None
                ),
                "signed_exchange_expiry_matches_tip": row.get(
                    "signed_exchange_expiry_matches_tip"
                ),
                "signed_exchange_expiry_matches_intent": row.get(
                    "signed_exchange_expiry_matches_intent"
                ),
                "expiry_delta_seconds": (
                    round((expiry - tip).total_seconds(), 1)
                    if expiry is not None and tip is not None
                    else None
                ),
                "journal_has_expiry": expiry is not None,
                "intent_strategy_generation": GENERATIONS.get(
                    intent.get("strategy_version"), "earlier_or_unknown"
                ),
                "quoted_NO_cents": rounded(intent.get("price_cents"), 2),
                "actual_fill_NO_cents": cents(row.get("vwap_no_price_dollars")),
                "fill_fees_dollars": rounded(row.get("fill_fees_dollars"), 4),
                "maker_classification": maker,
                "queue_ahead_initial": rounded(row.get("queue_ahead_initial"), 2),
                "queue_ahead_latest": rounded(row.get("queue_ahead_latest"), 2),
                "model_estimated_net_edge_cents_at_post": cents(
                    intent.get("net_edge_after_fee_bound")
                ),
                "probability_source": intent.get("probability_source")
                if intent.get("probability_source") in ("sportsbook", "model")
                else "unknown",
                "sportsbook_count_at_post": intent.get("book_n"),
                "model_generated_utc": intent.get("model_generated_utc"),
                "projected_minutes_at_post": "not_recorded_in_original_intent",
                "lineup_confirmation_at_post": "not_recorded_in_original_intent",
                "markouts_observed": by_horizon,
                "execution_is_not_proof_of_positive_expectancy": True,
            }
        )
    return result


def public_summary(report):
    """Prevent correlating private fills with publicly visible trade prints.

    GitHub Actions logs on a public repository are PUBLIC, even when data
    originates from a private signed exchange read. Do not publish unique
    execution timestamps, exact prices, fill sizes, fees, or settlement P&L.
    """

    def bucket_minutes(value):
        v = finite(value)
        if v is None or v < 0:
            return "unknown"
        if v < 15:
            return "under_15m"
        if v < 60:
            return "15m_to_1h"
        if v < 180:
            return "1h_to_3h"
        return "over_3h"

    def bucket_hours(value):
        v = finite(value)
        if v is None:
            return "unknown"
        if v < 0:
            return "after_tip"
        if v < 2:
            return "under_2h"
        if v <= 6:
            return "2h_to_6h"
        return "over_6h"

    def expiry_gap(value):
        seconds = finite(value)
        if seconds is None:
            return "unknown"
        magnitude = abs(seconds)
        if magnitude <= 1:
            return "matches_tip"
        direction = "before_tip" if seconds < 0 else "after_tip"
        if magnitude < 60:
            band = "under_1m"
        elif magnitude < 3600:
            band = "1m_to_1h"
        elif magnitude < 7200:
            band = "1h_to_2h"
        else:
            band = "over_2h"
        return direction + "_" + band

    def sign(value):
        v = finite(value)
        if v is None:
            return "unknown"
        return (
            "positive"
            if v > 0
            else "negative"
            if v < 0
            else "zero"
            if v == 0
            else "unknown"
        )

    fills = []
    for row in report.get("latest_fills", []):
        fills.append(
            {
                "execution_state": row.get("state"),
                "maker_status": row.get("maker_classification"),
                "resting_duration": bucket_minutes(
                    row.get("time_to_first_fill_minutes")
                ),
                "posting_window": bucket_hours(row.get("hours_to_tip_at_post")),
                "expiry_matched_tip": row.get("exchange_expiry_matches_scheduled_tip"),
                "actual_exchange_expiry_matches_tip": row.get(
                    "signed_exchange_expiry_matches_tip"
                ),
                "actual_exchange_expiry_matches_intent": row.get(
                    "signed_exchange_expiry_matches_intent"
                ),
                "journal_expiry_gap": expiry_gap(row.get("expiry_delta_seconds")),
                "journal_expiry_present": row.get("journal_has_expiry"),
                "intent_strategy_generation": row.get("intent_strategy_generation"),
                "pretrade_edge_sign": sign(
                    row.get("model_estimated_net_edge_cents_at_post")
                ),
                "sportsbook_count_at_least_two": (
                    finite(row.get("sportsbook_count_at_post")) >= 2
                    if finite(row.get("sportsbook_count_at_post")) is not None
                    else None
                ),
                "fees_verified": row.get("fill_fees_dollars") is not None,
                "minutes_verified_at_entry": False,
                "lineup_verified_at_entry": False,
                "postfill_observations": {
                    horizon: {
                        "mid_direction": sign(m.get("NO_mid_move_cents_before_fees")),
                        "bid_direction": sign(
                            m.get("NO_executable_bid_move_cents_before_fees")
                        ),
                        "issue": m.get("observation_issue"),
                    }
                    for horizon, m in row.get("markouts_observed", {}).items()
                    if horizon in {"5m", "15m", "60m"} and isinstance(m, dict)
                },
            }
        )
    return {
        "status": "signed_private_data_redacted_for_public_CI",
        "exchange_nba_accepted_orders": report.get("exchange_nba_accepted_orders"),
        "exchange_nba_filled_orders": report.get("exchange_nba_filled_orders"),
        "unreconciled_or_unknown_orders": report.get("unreconciled_or_unknown_orders"),
        "cohort_settlement_status": report.get("cohort_realized_pnl", {}).get("status"),
        "cohort_settled_markets": report.get("cohort_realized_pnl", {}).get(
            "settled_markets"
        ),
        "cohort_realized_pnl_sign": (
            sign(report.get("cohort_realized_pnl", {}).get("total_net_dollars"))
            if report.get("cohort_realized_pnl", {}).get("status") == "verified"
            else "unknown"
        ),
        "individual_fills": fills,
        "note": "No per-fill prices, exact times, sizes, fees, IDs, balances or PnL in public logs. Not proof of profitability.",
    }


def main():
    try:
        request = urllib.request.Request(
            DASHBOARD, headers={"Host": "127.0.0.1:8765", "User-Agent": "smm-audit/1"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise ValueError("Private dashboard rejected read")
            payload = response.read(3_000_001)
        if len(payload) > 3_000_000:
            raise ValueError("Dashboard read exceeded size bound")
        snapshot = json.loads(payload)
        data = summarize(snapshot, read_events(JOURNAL), datetime.now(UTC))
        print(json.dumps(public_summary(data), sort_keys=True, allow_nan=False))
    except Exception as error:
        # Never echo private HTTP response, exception body, or journal data.
        print(
            json.dumps(
                {
                    "status": "audit_unavailable",
                    "reason_class": type(error).__name__,
                    "no_trade_claim": True,
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
