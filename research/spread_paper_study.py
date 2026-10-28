"""Prospective paper entry/exit ablations; no exchange order methods."""

import copy
import random
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from research.nba_entry_study import fee
from research.spread_forward_core import EvidenceError, amount, consume, instant

PROTOCOL = "spread-paper-execution-v1"
ENTRY_RULES = ("baseline", "depth", "fresh", "depth_fresh")
EXECUTIONS = ("through", "flow25")
HORIZONS = (600, 1800, 3600)


def make_opportunity(candidate, sample, fees, at):
    if not candidate.get("eligible"):
        raise EvidenceError("candidate_not_eligible")
    start = instant(candidate["event_start_utc"])
    if (start - at).total_seconds() < 85 * 60:
        raise EvidenceError("start_too_close")
    if not 0 <= (at - instant(candidate["at"])).total_seconds() <= 900:
        raise EvidenceError("candidate_expired")
    if not sample.get("valid") or not 0 <= (at - instant(sample["requested_at"])).total_seconds() <= 20:
        raise EvidenceError("entry_book_not_fresh")
    if instant(sample["completed_at"]) > at:
        raise EvidenceError("future_entry_book")
    if fees.get("fee_type") not in ("quadratic", "quadratic_with_maker_fees"):
        raise EvidenceError("unsupported_fee_type")
    book = sample["external_book"]
    if not book["yes"] or not book["no"]:
        raise EvidenceError("two_sided_book_required")
    bid, ask = amount(book["yes"][0][0]), 1 - amount(book["no"][0][0])
    if not Decimal("0.08") <= ask - bid or not 0 < bid < ask < 1:
        raise EvidenceError("spread_too_narrow_or_crossed")
    prices = {"yes": bid + Decimal("0.01"), "no": 1 - ask + Decimal("0.01")}
    sides = {}
    for side, p in prices.items():
        if not Decimal("0.02") <= p <= Decimal("0.98"):
            raise EvidenceError("price_outside_range")
        charge = Decimal(str(fee(p, fees["fee_multiplier"])))
        exit_value = consume(copy.deepcopy(book[side]), Decimal(1), amount(fees["fee_multiplier"]))
        full = amount(exit_value["remaining"]) == 0
        gap = p + charge - amount(exit_value["proceeds"]) + amount(exit_value["fee_estimate"]) if full else None
        sides[side] = {"price": str(p), "fee": str(charge), "depth_pass": full and gap <= Decimal("0.05"), "exit_gap": str(gap) if gap is not None else None}
    return {
        "ticker": candidate["ticker"], "event": candidate["event_ticker"],
        "game": candidate["event_ticker"].split("-", 1)[-1],
        "quoted_at": at.isoformat(), "event_start": start.isoformat(),
        "expires_at": (at + timedelta(minutes=65)).isoformat(),
        "observe_until": min(at + timedelta(minutes=126), start).isoformat(),
        "sides": sides, "quantity": 1, "fee_multiplier": fees["fee_multiplier"],
        "entry_book": sample, "history_status": "pending", "outcome": None,
    }


def first_fill(row, side, trades, minutes, execution):
    start = instant(row["quoted_at"])
    end = min(start + timedelta(minutes=minutes), instant(row["event_start"]))
    volume = Decimal(0)
    seen = set()
    first = None
    price = amount(row["sides"][side]["price"])
    for trade in sorted(trades, key=lambda t: (t["created_time"], t["trade_id"])):
        tid = trade.get("trade_id")
        if not tid or tid in seen or trade.get("ticker") != row["ticker"]:
            raise EvidenceError("invalid_or_duplicate_trade_identity")
        seen.add(tid)
        at = instant(trade["created_time"])
        if not start < at < end or trade.get("is_block_trade"):
            continue
        taker = trade.get("taker_outcome_side") or trade.get("taker_side")
        yes = amount(trade["yes_price_dollars"])
        no = amount(trade["no_price_dollars"])
        q = amount(trade["count_fp"], True)
        if taker not in ("yes", "no") or yes + no != 1:
            raise EvidenceError("invalid_public_trade")
        traded_price = yes if side == "yes" else no
        if taker != side and traded_price < price:
            volume += q
            if volume >= (4 if execution == "flow25" else 1) and first is None:
                first = at
    return first


def side_result(row, side, rule, take_profit, execution, slip, books, at):
    detail = row["sides"][side]
    if "depth" in rule and not detail["depth_pass"]:
        return {"status": "abstained", "pnl": 0.0, "filled": False, "due": 0, "valid": 0}
    if row["history_status"] != "complete":
        return {"status": "execution_unknown", "pnl": None, "filled": None, "due": 0, "valid": 0}
    filled = first_fill(row, side, row["trades"], 15 if "fresh" in rule else 65, execution)
    if filled is None:
        return {"status": "no_fill", "pnl": 0.0, "filled": False, "due": 0, "valid": 0}
    price, charge = amount(detail["price"]), amount(detail["fee"])
    left, pnl = Decimal(1), -charge
    due = valid = 0
    missing, attempted = False, False
    for horizon in HORIZONS:
        scheduled = filled + timedelta(seconds=horizon)
        if scheduled >= instant(row["event_start"]):
            continue
        if at <= scheduled + timedelta(seconds=60):
            continue
        due += 1
        candidates = [b for b in books if b.get("valid")
                      and b["ticker"] == row["ticker"]
                      and scheduled <= instant(b["requested_at"]) <= instant(b["completed_at"]) <= scheduled + timedelta(seconds=60)]
        if not candidates:
            if not attempted:
                missing = True
            continue
        valid += 1
        b = min(candidates, key=lambda x: instant(x["completed_at"]))
        levels = copy.deepcopy(b["external_book"][side])
        if take_profit and not attempted and levels and amount(levels[0][0]) >= price + Decimal("0.10"):
            sale = consume(levels, left, amount(row["fee_multiplier"]), Decimal(slip) / 100)
            sold = amount(sale["quantity"])
            pnl += amount(sale["proceeds"]) - amount(sale["fee_estimate"]) - sold * price
            left -= sold
            attempted = True
    base = {"filled": True, "fill_at": filled.isoformat(), "due": due, "valid": valid}
    if take_profit and missing:
        return {**base, "status": "exit_observation_unknown", "pnl": None}
    # Do not settle or claim an exit before all eligible horizons have elapsed.
    last_due = min(filled + timedelta(seconds=3660), instant(row["event_start"]))
    if take_profit and not attempted and at < last_due:
        return {**base, "status": "exit_pending", "pnl": None}
    if left:
        result = row.get("outcome")
        if result not in ("yes", "no"):
            return {**base, "status": "settlement_pending_or_nonbinary", "pnl": None}
        pnl += left * (int(result == side) - price)
    return {**base, "status": "resolved", "pnl": float(pnl)}


def interval(values):
    if len(values) < 2:
        return None
    rng = random.Random(20261028)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(2000))
    return [round(means[49], 6), round(means[1949], 6)]


def report(rows, books, at, end, start=None):
    comparisons, game_values = {}, {}
    indexed = defaultdict(list)
    for book in books:
        indexed[book["ticker"]].append(book)
    for execution in EXECUTIONS:
        for rule in ENTRY_RULES:
            for exit_rule in (False, True):
                for slip in ((0, 1, 2) if exit_rule else (0,)):
                    key = f"{execution}/{rule}/{'exit' if exit_rule else 'hold'}/slip{slip}"
                    games, unknown_games = defaultdict(float), set()
                    stats = defaultdict(int)
                    for row in rows:
                        for side in ("yes", "no"):
                            r = side_result(row, side, rule, exit_rule, execution, slip, indexed[row["ticker"]], at)
                            stats[r["status"]] += 1
                            stats["due_checkpoints"] += r["due"]
                            stats["valid_checkpoints"] += r["valid"]
                            if r["pnl"] is None:
                                unknown_games.add(row["game"])
                            else:
                                games[row["game"]] += r["pnl"]
                    closed = {g: p for g, p in games.items() if g not in unknown_games}
                    ranked = sorted(closed.values(), reverse=True)
                    comparisons[key] = {
                        "counts": dict(stats), "complete_games": len(closed),
                        "pending_or_unknown_games": len(unknown_games),
                        "net_pnl_complete_games": round(sum(ranked), 6),
                        "without_best_game": round(sum(ranked[1:]), 6),
                        "without_best_three_games": round(sum(ranked[3:]), 6),
                        "game_mean_95_interval": interval(ranked),
                        "due_checkpoint_coverage": stats["valid_checkpoints"] / stats["due_checkpoints"] if stats["due_checkpoints"] else None,
                    }
                    game_values[key] = closed
    primary_key = "flow25/depth_fresh/exit/slip2"
    base_key = "flow25/baseline/hold/slip0"
    primary, base = game_values[primary_key], game_values[base_key]
    matched = sorted(set(primary) & set(base))
    delta = [primary[g] - base[g] for g in matched]
    ci = interval(delta)
    score = comparisons[primary_key]
    coverage = score["due_checkpoint_coverage"]
    split = instant(start) + (instant(end) - instant(start)) / 2 if start else None
    periods = {"first_half": [], "second_half": []}
    if split:
        game_start = {}
        for row in rows:
            game_start[row["game"]] = min(game_start.get(row["game"], instant(row["quoted_at"])), instant(row["quoted_at"]))
        for game in matched:
            periods["first_half" if game_start[game] < split else "second_half"].append(primary[game])
    reasons = []
    if at < instant(end):
        reasons.append("enrollment_not_finished")
    if len(matched) < 30:
        reasons.append("fewer_than_30_independent_complete_games")
    if score["pending_or_unknown_games"]:
        reasons.append("unresolved_evidence")
    if coverage is not None and coverage < .95:
        reasons.append("checkpoint_coverage_below_95_percent")
    if not score["game_mean_95_interval"] or score["game_mean_95_interval"][0] <= 0:
        reasons.append("positive_edge_not_established")
    if not ci or ci[0] <= 0:
        reasons.append("improvement_over_baseline_not_established")
    if score["without_best_three_games"] <= 0:
        reasons.append("results_depend_on_best_games")
    if not split or any(len(v) < 10 or sum(v) <= 0 for v in periods.values()):
        reasons.append("positive_results_across_calendar_halves_not_established")
    return {
        "opportunities": len(rows) * 2, "games": len({r["game"] for r in rows}),
        "comparisons": comparisons,
        "primary_comparison": {"candidate": primary_key, "baseline": base_key, "matched_games": len(matched), "mean_improvement_95_interval": ci},
        "primary_calendar_halves": {k: {"complete_games": len(v), "pnl": round(sum(v), 6)} for k, v in periods.items()},
        "review_gate": {"status": "not_ready" if reasons else "manual_review_only", "reasons": reasons, "automatic_live_enable": False},
        "limitations": ["Public trade-through and 25% volume sensitivity do not establish actual queue priority.", "One contract per side and one quote per market; this is not a replay of funded v3 capacity or requotes.", "Common $5/game opportunity budget never recycles proceeds; filtered rules leave budget unused.", "Displayed exit depth is an estimate; missing exit observations and scalar outcomes stay unknown.", "A fixed primary comparison is assessed once after enrollment and settlement; other ablations are exploratory."],
    }
