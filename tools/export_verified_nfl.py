"""Export privacy-filtered NFL production orders and exchange-verified fills.

READ ONLY. Uses the same GET-only signed Kalshi client as the private account
dashboard; cannot place or cancel orders. Never exports credentials, balances,
client order IDs, exchange order IDs or exchange fill IDs.

Run on the DigitalOcean worker with the production EnvironmentFile loaded:
  python tools/export_verified_nfl.py --output /tmp/nfl_verified_execution.json
"""
import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from live.account_dashboard import ReadOnlyClient, read_journal
from live.nfl_policy import STATE, settlement_accounting


def num(value):
    try:
        x = float(value)
        return round(x, 8) if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def dollars(row, key, legacy=None):
    v = num(row.get(key))
    if v is not None:
        return v
    v = num(row.get(legacy)) if legacy else None
    return round(v / 100, 8) if v is not None else None



def fill_direction(fill):
    """Resolve current Kalshi V2 fields and legacy action/side consistently.

    Under the V2 single-YES-book protocol, a buy-NO order is an ASK that can
    appear as legacy sell-YES. Direction is NO in both cases. An unmatched or
    contradictory record is reported for investigation, never assumed to be NO.
    """
    fields = {
        key: (str(fill[key]).strip().lower()
              if fill.get(key) is not None else None)
        for key in ("outcome_side", "book_side", "action", "side")
    }
    outcome = fields["outcome_side"]
    book = fields["book_side"]
    action = fields["action"]
    side = fields["side"]
    issues = []
    if outcome not in (None, "yes", "no"):
        issues.append("invalid_outcome_side")
    if book not in (None, "bid", "ask"):
        issues.append("invalid_book_side")
    if action not in (None, "buy", "sell"):
        issues.append("invalid_legacy_action")
    if side not in (None, "yes", "no"):
        issues.append("invalid_legacy_side")
    if (action is None) != (side is None):
        issues.append("incomplete_legacy_direction")
    legacy = {
        ("buy", "yes"): "yes",
        ("sell", "no"): "yes",
        ("buy", "no"): "no",
        ("sell", "yes"): "no",
    }.get((action, side))
    directions = [v for v in (
        outcome if outcome in ("yes", "no") else None,
        {"bid": "yes", "ask": "no"}.get(book),
        legacy,
    ) if v is not None]
    if not directions:
        issues.append("no_direction_evidence")
    if len(set(directions)) > 1:
        issues.append("conflicting_direction_fields")
    if directions and directions[0] != "no":
        issues.append("unexpected_yes_direction")
    return ("verified_no" if not issues else "review_required", issues, fields)


def build(events, actual_fills, settlements):
    intents = [x for x in events if x.get("event") == "intent"]
    accepted = {x["client_order_id"]: x for x in events
                if x.get("event") == "accepted" and x.get("client_order_id")}
    if len({x.get("client_order_id") for x in intents}) != len(intents):
        raise ValueError("Ambiguous intent identities; audit locally")
    rows, by_order_id = [], {}
    for index, entry in enumerate(intents, 1):
        ack = accepted.get(entry["client_order_id"])
        row = {
            "ref": f"NFL-{index:03d}",
            "accepted": bool(ack),
            "order_utc": entry.get("utc"),
            "accepted_utc": ack.get("utc") if ack else None,
            "ticker": entry.get("ticker"),
            "player": entry.get("player"),
            "game_id": entry.get("game_id"),
            "team": entry.get("team"),
            "strategy_version": entry.get("strategy_version", "original"),
            "model_made_utc": entry.get("model_made_utc"),
            "probability_source": entry.get("probability_source"),
            "p_yes_used": num(entry.get("p_yes_used")),
            "edge_after_fee_buffer": num(entry.get("edge_after_fee_buffer")),
            "baseline_edge": num(entry.get("baseline_edge")),
            "extra_maker_ticks": entry.get("extra_maker_ticks"),
            "quoted_price": round(num(entry.get("price_cents")) / 100, 4)
                            if num(entry.get("price_cents")) is not None else None,
            "quoted_count": num(entry.get("count")),
            "quoted_cost": num(entry.get("cost")),
            "fill_records": 0,
            "filled_contracts": 0.0,
            "filled_cost": 0.0,
            "reported_fill_fees": 0.0,
            "queue_initial": None,
            "queue_last": None,
            "queue_observations": 0,
            "queue_failures": 0,
            "settlement": None,
        }
        rows.append(row)
        if ack:
            oid = ack["order_id"]
            if oid in by_order_id:
                raise ValueError("Repeated accepted order identity")
            by_order_id[oid] = row

    observations = defaultdict(list)
    for e in events:
        if e.get("event") == "queue" and e.get("order_id") in by_order_id:
            observations[e["order_id"]].append(e)
    for oid, samples in observations.items():
        row = by_order_id[oid]
        row["queue_initial"] = num(samples[0].get("ahead"))
        row["queue_last"] = num(samples[-1].get("ahead"))
        row["queue_observations"] = len(samples)
        row["queue_failures"] = sum(bool(s.get("issue")) for s in samples)

    fill_rows, seen_fill_ids, foreign_count = [], set(), 0
    for fill in actual_fills:
        oid = fill.get("order_id")
        if oid not in by_order_id:
            foreign_count += 1
            continue
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid or fid in seen_fill_ids:
            raise ValueError("Missing/duplicate exchange fill identity")
        seen_fill_ids.add(fid)
        row = by_order_id[oid]
        actual_ticker = fill.get("ticker") or fill.get("market_ticker")
        if actual_ticker and actual_ticker != row["ticker"]:
            raise ValueError("Exchange ticker does not match accepted order")
        direction, direction_issues, direction_fields = fill_direction(fill)
        count = num(fill.get("count_fp", fill.get("count")))
        price = dollars(fill, "no_price_dollars", "no_price")
        fee = num(fill.get("fee_cost"))
        if count is None or count <= 0 or price is None or not 0 <= price <= 1:
            raise ValueError("Invalid/missing fill quantity or price")
        # Only validated NO-direction fills contribute to modeled entry cost.
        # Keep direction anomalies as evidence; do not silently drop them.
        if direction == "verified_no":
            row["fill_records"] += 1
            row["filled_contracts"] = round(row["filled_contracts"] + count, 8)
            row["filled_cost"] = round(row["filled_cost"] + count * price, 8)
            row["reported_fill_fees"] = (
                round(row["reported_fill_fees"] + fee, 8)
                if fee is not None and row["reported_fill_fees"] is not None else None
            )
        fill_rows.append({
            "direction_status": direction,
            "direction_issues": direction_issues,
            "direction_fields": direction_fields,
            "order_ref": row["ref"],
            "ticker": row["ticker"],
            "player": row["player"],
            "filled_utc": fill.get("created_time"),
            "contracts": count,
            "no_price": price,
            "fee": fee,
            "is_taker": fill.get("is_taker"),
        })

    settled = {}
    for s in settlements:
        ticker = s.get("ticker") or s.get("market_ticker")
        if ticker:
            settled[ticker] = settlement_accounting(s)
    for row in rows:
        row["settlement"] = settled.get(row["ticker"])
    return {
        "provenance": "Kalshi production signed GET /portfolio/fills and /portfolio/settlements joined with private NFL order journal",
        "generated_utc": datetime.now(UTC).isoformat(),
        "privacy": "No keys, account balances or raw order/fill IDs are included.",
        "summary": {
            "attempted_orders": len(intents),
            "exchange_accepted_orders": len(by_order_id),
            "exchange_verified_fill_events": len(fill_rows),
            "exchange_matched_filled_contracts_all_directions": round(
                sum(f["contracts"] for f in fill_rows), 8
            ),
            "exchange_verified_filled_contracts": round(sum(
                f["contracts"] for f in fill_rows
                if f["direction_status"] == "verified_no"
            ), 8),
            "direction_review_fill_events": sum(
                f["direction_status"] != "verified_no" for f in fill_rows
            ),
            "distinct_orders_filled": len(set(f["order_ref"] for f in fill_rows)),
            "other_exchange_fill_events_excluded": foreign_count,
            "settled_owned_orders": sum(r["settlement"] is not None for r in rows),
            "unconfirmed_intents": len(intents) - len(by_order_id),
        },
        "orders_including_zero_fills": rows,
        "verified_fill_events": fill_rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/nfl_verified_execution.json"))
    args = parser.parse_args()
    events = read_journal(STATE / "journal.jsonl")
    intents = [e for e in events if e.get("event") == "intent"]
    client = ReadOnlyClient()
    if intents:
        stamp = min(datetime.fromisoformat(e["utc"]).timestamp() for e in intents)
        fills = client.pages("/portfolio/fills", "fills", min_ts=int(stamp) - 60)
        settlements = client.pages("/portfolio/settlements", "settlements", min_ts=int(stamp) - 60)
    else:
        fills, settlements = [], []
    report = build(events, fills, settlements)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.output.chmod(0o600)
    s = report["summary"]
    print(f"EXCHANGE VERIFIED: {s['exchange_verified_fill_events']} fill events, "
          f"{s['exchange_verified_filled_contracts']} contracts; "
          f"{s['exchange_accepted_orders']} accepted orders.")
    print(f"Sanitized output: {args.output}. Upload the JSON file, not raw journal or credentials.")


if __name__ == "__main__":
    main()
