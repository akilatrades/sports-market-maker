"""Frozen, prospective paper comparison. No credentials or order methods."""

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from research.spread_forward_core import EvidenceError, instant

PROTOCOL = "nba-equal-size-entry-v1"
END = "2026-11-24T21:47:54.024216+00:00"
DRAIN_END = "2026-12-01T21:47:54.024216+00:00"
POLICIES = ("no_baseline", "model_veto", "fresh_books_veto")
ASSUMPTIONS = ("through", "touch")


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceError("nonfinite_number")
    return result


def fee(price, multiplier=1, count=1, rate="0.07"):
    p, m, n = map(lambda x: Decimal(str(x)), (price, multiplier, count))
    if not all(x.is_finite() for x in (p, m, n)) or not (
        0 < p < 1 and m >= 0 and n > 0
    ):
        raise EvidenceError("invalid_fee_input")
    return float(
        (Decimal(rate) * m * n * p * (1 - p)).quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
    )


def eligible(rows, at):
    """Select one rung per game/player/stat using only the quoted midpoint."""
    groups = defaultdict(list)
    for raw in rows:
        try:
            r = dict(raw)
            age = (at - instant(r["snapshot_utc"])).total_seconds()
            lead = (instant(r["tip_utc"]) - at).total_seconds() / 3600
            p = number(r["p_model"])
            bid, ask = number(r["yes_bid_dollars"]), number(r["yes_ask_dollars"])
            if not (
                0 <= age <= 1800
                and 2 <= lead <= 6
                and 0 <= p <= 1
                and 0 < bid < ask < 1
            ):
                continue
            if r.get("injury_status") or not all(
                r.get(k) for k in ("game_id", "player_id", "stat", "ticker")
            ):
                continue
            groups[(r["game_id"], r["player_id"], r["stat"])].append(r)
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(
        (
            min(
                rs,
                key=lambda r: (
                    abs(
                        (number(r["yes_bid_dollars"]) + number(r["yes_ask_dollars"]))
                        / 2
                        - 0.5
                    ),
                    r["ticker"],
                ),
            )
            for rs in groups.values()
        ),
        key=lambda r: (r["tip_utc"], r["game_id"], r["ticker"]),
    )


def opportunity(row, book, fees, at):
    """Fresh public book precedes paper entry; both filters share this price."""
    from research.spread_forward_core import external_book

    levels = external_book(book, row["ticker"], [])
    if not levels["yes"] or not levels["no"]:
        raise EvidenceError("missing_two_sided_depth")
    bid, ask = number(levels["yes"][0][0]), 1 - number(levels["no"][0][0])
    if not 0 < bid < ask < 1:
        raise EvidenceError("crossed_book")
    if fees.get("fee_type") not in ("quadratic", "quadratic_with_maker_fees"):
        raise EvidenceError("unsupported_fee_type")
    multiplier = number(fees["fee_multiplier"])
    improved = ask - bid >= 0.02 - 1e-9
    price = round(1 - ask + (0.01 if improved else 0), 4)
    charge = fee(price, multiplier)
    p = number(row["p_model"])
    source_age = (at - instant(row["snapshot_utc"])).total_seconds()
    lead = (instant(row["tip_utc"]) - at).total_seconds() / 3600
    if not (0 <= p <= 1 and 0 <= source_age <= 1800 and 2 <= lead <= 6):
        raise EvidenceError("input_expired_during_fetch")
    book_ok = False
    book_age = None
    try:
        book_age = (at - instant(row["book_updated_utc"])).total_seconds()
        p_book = number(row["p_book"])
        book_ok = (
            number(row["book_n"]) >= 2
            and 0 <= book_age <= 1800
            and instant(row["book_commence_utc"]) == instant(row["tip_utc"])
            and 0 <= p_book <= 1
            and 1 - p_book - price - charge >= -1e-9
        )
    except (KeyError, ValueError, TypeError):
        pass
    evidence_keys = (
        "snapshot_utc",
        "book_updated_utc",
        "book_commence_utc",
        "p_book",
        "book_n",
        "last_player_game_utc",
        "minutes_estimate_source",
        "lineup_confirmation_status",
        "historical_minutes_baseline",
        "last_game_minutes",
        "recent_start_rate",
        "requires_book",
        "line",
        "team",
        "player_id",
        "stat",
    )
    return {
        "ticker": row["ticker"],
        "game_id": row["game_id"],
        "slot": "|".join(row[k] for k in ("game_id", "player_id", "stat")),
        "quoted_at": at.isoformat(),
        "tip_utc": row["tip_utc"],
        "side": "no",
        "quantity": 1,
        "price": price,
        "improved": improved,
        "yes_level": round(1 - price, 4),
        "p_model_yes": p,
        "fee_upper_estimate": charge,
        "fee_type": fees["fee_type"],
        "fee_multiplier": multiplier,
        "source_age_seconds": source_age,
        "book_age_seconds": book_age,
        "entry_book": levels,
        "inputs": {k: row.get(k) for k in evidence_keys},
        "policies": {
            "no_baseline": True,
            "model_veto": 1 - p - price - charge >= -1e-9,
            "fresh_books_veto": book_ok,
        },
        "execution_status": "pending",
        "outcome_status": "pending",
    }


def complete_trades(get, ticker, start, end):
    """Every required history page must succeed; use the published archive cut."""
    payload = get("/historical/cutoff", {})
    if not isinstance(payload, dict):
        raise EvidenceError("archive_cutoff_unavailable")
    cutoff = instant(payload.get("trades_created_ts"))
    paths = []
    if end >= cutoff:
        paths.append("/markets/trades")
    if start <= cutoff:
        paths.append("/historical/trades")
    unique = {}
    for path in paths:
        cursors, cursor = set(), None
        for _ in range(200):
            params = {
                "ticker": ticker,
                "min_ts": int(start.timestamp()) - 1,
                "max_ts": int(end.timestamp()) + 1,
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor
            page = get(path, params)
            if not isinstance(page, dict) or not isinstance(page.get("trades"), list):
                raise EvidenceError("trade_history_unavailable")
            for t in page["trades"]:
                identity = t.get("trade_id")
                if not identity or t.get("ticker") != ticker:
                    raise EvidenceError("trade_identity_missing")
                if identity in unique and unique[identity] != t:
                    raise EvidenceError("conflicting_trade_history")
                unique[identity] = t
            cursor = page.get("cursor")
            if not cursor:
                break
            if cursor in cursors:
                raise EvidenceError("trade_cursor_cycle")
            cursors.add(cursor)
        else:
            raise EvidenceError("trade_page_limit")
    after = get("/historical/cutoff", {})
    if not isinstance(after, dict) or instant(after.get("trades_created_ts")) != cutoff:
        raise EvidenceError("archive_cutoff_changed_retry")
    return sorted(unique.values(), key=lambda t: (t["created_time"], t["trade_id"]))


def execution(row, trades):
    start, end = instant(row["quoted_at"]), instant(row["tip_utc"])
    volume = {key: 0.0 for key in ASSUMPTIONS}
    first = {}
    for t in trades:
        at = instant(t["created_time"])
        if not start <= at < end or t.get("is_block_trade"):
            continue
        side = t.get("taker_outcome_side") or t.get("taker_side")
        price, count = number(t["yes_price_dollars"]), number(t["count_fp"])
        if not (side in ("yes", "no") and 0 < price < 1 and count >= 0):
            raise EvidenceError("invalid_trade")
        if side != "yes":
            continue
        for key in ASSUMPTIONS:
            crossed = price > row["yes_level"] + 1e-9
            touched = row["improved"] and abs(price - row["yes_level"]) <= 1e-9
            if crossed or (key == "touch" and touched):
                volume[key] += count
                if volume[key] >= 1 and key not in first:
                    first[key] = {"at": t["created_time"], "yes_price": price}
    result = {}
    for key in ASSUMPTIONS:
        markouts = {}
        if key in first:
            fill_at = instant(first[key]["at"])
            for horizon in (60, 300):
                later = [
                    t
                    for t in trades
                    if not t.get("is_block_trade")
                    and horizon
                    <= (instant(t["created_time"]) - fill_at).total_seconds()
                    <= horizon + 60
                    and instant(t["created_time"]) < end
                ]
                if later:
                    t = min(later, key=lambda t: instant(t["created_time"]))
                    markouts[str(horizon)] = round(
                        1 - number(t["yes_price_dollars"]) - row["price"], 6
                    )
        result[key] = {
            "filled": volume[key] >= 1,
            "first_fill_print": first.get(key),
            "later_trade_markouts": markouts,
        }
    return result


def report(rows):
    results = {}
    for assumption in ASSUMPTIONS:
        for policy in POLICIES:
            chosen = [r for r in rows if r["policies"][policy]]
            known = [r for r in chosen if r["execution_status"] == "complete"]
            filled = [r for r in known if r["execution"][assumption]["filled"]]
            settled = [r for r in filled if r["outcome_status"] == "settled"]
            games, exposure = defaultdict(float), defaultdict(float)
            for r in chosen:
                if r["outcome_status"] != "settled" and (
                    r["execution_status"] != "complete"
                    or r["execution"][assumption]["filled"]
                ):
                    exposure[r["game_id"]] += r["price"] + r["fee_upper_estimate"]
            for r in settled:
                games[r["game_id"]] += (
                    (r["result"] == "no") - r["price"] - r["fee_upper_estimate"]
                )
            profits = sorted(games.values(), reverse=True)
            markouts = {}
            for horizon in ("60", "300"):
                values = [
                    r["execution"][assumption]["later_trade_markouts"][horizon]
                    for r in filled
                    if horizon
                    in r["execution"][assumption].get("later_trade_markouts", {})
                ]
                markouts[horizon] = {
                    "observations": len(values),
                    "mean": sum(values) / len(values) if values else None,
                }
            results[assumption + "/" + policy] = {
                "orders": len(chosen),
                "execution_known": len(known),
                "filled": len(filled),
                "settled": len(settled),
                "settled_games": len(games),
                "pending_or_unknown_execution": len(chosen) - len(known),
                "net_pnl_fee_upper_estimate": round(sum(profits), 4),
                "pnl_without_best_game": round(sum(profits[1:]), 4),
                "pnl_without_best_three_games": round(sum(profits[3:]), 4),
                "forecast_win_probability": (
                    sum(1 - r["p_model_yes"] for r in settled) / len(settled)
                )
                if settled
                else None,
                "actual_win_rate": (
                    sum(r["result"] == "no" for r in settled) / len(settled)
                )
                if settled
                else None,
                "brier_filled": (
                    sum(
                        ((1 - r["p_model_yes"]) - (r["result"] == "no")) ** 2
                        for r in settled
                    )
                    / len(settled)
                )
                if settled
                else None,
                "exposure_by_game": dict(sorted(exposure.items())),
                "trade_print_markouts_not_executable_quotes": markouts,
            }
    resolved = [r for r in rows if r["outcome_status"] == "settled"]
    return {
        "comparisons": results,
        "all_opportunities_resolved": len(resolved),
        "brier_all_resolved": (
            sum((r["p_model_yes"] - (r["result"] == "yes")) ** 2 for r in resolved)
            / len(resolved)
        )
        if resolved
        else None,
        "interpretation": "Paper execution sensitivity only; public prints do not prove queue fills. Correlated games, not contracts, are independent observations.",
    }


def audit(rows):
    """Historical diagnostic, not an out-of-sample model-free comparison."""
    groups, errors, seen = defaultdict(list), [], set()
    for r in rows:
        key = (r["rule"], r["ticker"], r["placed_ts"])
        if key in seen:
            errors.append("duplicate_order")
        seen.add(key)
        if r["status"] != "settled":
            continue
        try:
            n, price, model = (
                number(r["filled_contracts"]),
                number(r["price"]),
                number(r["p_model"]),
            )
            side, result = r["side"], r["result"]
            if not (
                n > 0
                and 0 < price < 1
                and 0 <= model <= 1
                and side in ("yes", "no")
                and result in ("yes", "no")
            ):
                raise EvidenceError("invalid_settlement")
            if (
                abs(number(r["yes_level"]) - (price if side == "yes" else 1 - price))
                > 0.00001
            ):
                raise EvidenceError("side_price_mismatch")
            if abs(number(r["settlement_value"]) - (result == "yes")) > 0.00001:
                raise EvidenceError("settlement_value_mismatch")
            expected_fee = fee(price, count=n, rate="0.0175")
            expected = n * ((side == result) - price) - expected_fee
            if (
                abs(expected_fee - number(r["fee"])) > 0.00001
                or abs(expected - number(r["profit"])) > 0.011
            ):
                raise EvidenceError("pnl_arithmetic_mismatch")
            if number(r["placed_ts"]) >= number(r["tip_ts"]):
                raise EvidenceError("order_after_tip")
            groups[r["rule"]].append(r)
        except (KeyError, ValueError, TypeError) as e:
            errors.append(str(e) if type(e) is EvidenceError else "invalid_row")
    out = {}
    for rule, rs in groups.items():
        n = sum(number(r["filled_contracts"]) for r in rs)
        expected = sum(
            number(r["filled_contracts"])
            * (number(r["p_model"]) if r["side"] == "yes" else 1 - number(r["p_model"]))
            for r in rs
        )
        wins = sum(
            number(r["filled_contracts"]) * (r["side"] == r["result"]) for r in rs
        )
        games = defaultdict(float)
        for r in rs:
            games[r["game_id"]] += number(r["profit"])
        pnl = sorted(games.values(), reverse=True)
        out[rule] = {
            "settled_orders": len(rs),
            "games": len(games),
            "contracts": n,
            "forecast_win_probability": expected / n,
            "actual_win_rate": wins / n,
            "net_pnl": round(sum(pnl), 2),
            "without_best_game": round(sum(pnl[1:]), 2),
            "without_best_three_games": round(sum(pnl[3:]), 2),
        }
    return {
        "rules": out,
        "accounting_errors": errors,
        "limitations": [
            "Existing no_seller uses a model veto; it is not a model-free control.",
            "Different sizing and candidate baskets confound existing variant comparisons.",
            "Historical ledger lacks book timestamps and confirmed minutes/lineups; freshness is unknown.",
            "Small, correlated game sample cannot establish profitability.",
        ],
    }


def code_hash():
    root = Path(__file__).parent
    return hashlib.sha256(
        b"".join(
            (root / f).read_bytes()
            for f in (
                "nba_entry_study.py",
                "nba_entry_runner.py",
                "spread_forward_core.py",
            )
        )
    ).hexdigest()


def load_csv(path):
    with Path(path).open() as handle:
        return list(csv.DictReader(handle))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def utcnow():
    return datetime.now(UTC)
