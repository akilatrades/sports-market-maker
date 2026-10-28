import copy
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from deploy.paused_research_control import cron
from research.nba_model_diagnostics import calibration, input_quality
from research.spread_cash_reconciliation import reconciliation
from research.spread_forward_core import EvidenceError, digest
from research.spread_paper_study import first_fill, make_opportunity, report, side_result
from tools.export_private_fills import ExportError, paused_research_file

AT = datetime(2026, 10, 28, 18, tzinfo=UTC)


def book(at=AT, yes="0.4", no="0.4", quantity="10"):
    return {"ticker": "KXTEST-GAME-TEAM", "requested_at": at.isoformat(),
            "completed_at": (at + timedelta(seconds=1)).isoformat(), "valid": True,
            "external_book": {"yes": [[yes, quantity]], "no": [[no, quantity]]}}


def opportunity(**changes):
    candidate = {"eligible": True, "ticker": "KXTEST-GAME-TEAM", "event_ticker": "KXTEST-GAME",
                 "at": AT.isoformat(), "event_start_utc": (AT + timedelta(hours=4)).isoformat()}
    row = make_opportunity(candidate, changes.pop("sample", book()), {"fee_type": "quadratic", "fee_multiplier": 1}, AT + timedelta(seconds=2))
    row.update(changes)
    return row


def trade(at=AT + timedelta(minutes=10), side="no", yes="0.4", count="1", tid="print"):
    return {"trade_id": tid, "ticker": "KXTEST-GAME-TEAM", "created_time": at.isoformat(),
            "taker_outcome_side": side, "yes_price_dollars": yes,
            "no_price_dollars": str(1 - Decimal(yes)), "count_fp": count, "is_block_trade": False}


def events_and_fill(side="yes", price="0.32", quantity="0.01"):
    events = [{"event": "intent", "utc": AT.isoformat(), "client_order_id": "client",
               "ticker": "KXTEST-GAME-TEAM", "event_ticker": "KXTEST-GAME", "side": side,
               "price_cents": float(price) * 100, "strategy_version": "v3"},
              {"event": "accepted", "client_order_id": "client", "order_id": "order"}]
    yes = price if side == "yes" else str(1 - Decimal(price))
    raw = {"fill_id": "fill", "order_id": "order", "ticker": "KXTEST-GAME-TEAM",
           "created_time": AT.isoformat(), "outcome_side": side,
           "book_side": "bid" if side == "yes" else "ask", "count_fp": quantity,
           "yes_price_dollars": yes, "no_price_dollars": str(1 - Decimal(yes)), "fee_cost": "0"}
    return events, raw


class PaperTest(unittest.TestCase):
    def test_virtual_quote_uses_fresh_completed_book(self):
        r = opportunity()
        self.assertEqual(r["sides"]["yes"]["price"], "0.41")
        self.assertEqual(r["quantity"], 1)
        candidate = {"eligible": True, "ticker": r["ticker"], "event_ticker": r["event"], "at": AT.isoformat(), "event_start_utc": r["event_start"]}
        for at in (AT, AT + timedelta(seconds=21)):
            with self.assertRaises(EvidenceError):
                make_opportunity(candidate, book(), {"fee_type": "quadratic", "fee_multiplier": 1}, at)

    def test_depth_screen_does_not_use_future_outcome(self):
        r = opportunity(outcome="yes", sample=book(quantity="0.5"))
        self.assertFalse(r["sides"]["yes"]["depth_pass"])
        result = side_result(r, "yes", "depth", False, "through", 0, [], AT)
        self.assertEqual(result["pnl"], 0)
        self.assertEqual(result["status"], "abstained")

    def test_trade_through_requires_opposite_taker_and_post_quote_volume(self):
        r = opportunity()
        self.assertIsNone(first_fill(r, "yes", [trade(side="yes")], 65, "through"))
        self.assertIsNone(first_fill(r, "yes", [trade(at=AT)], 65, "through"))
        self.assertIsNone(first_fill(r, "yes", [trade(yes="0.41")], 65, "through"))
        self.assertIsNone(first_fill(r, "yes", [trade(count="3.99")], 65, "flow25"))
        self.assertIsNotNone(first_fill(r, "yes", [trade(count="4")], 65, "flow25"))

    def test_short_quote_excludes_late_fill_and_block_prints(self):
        r = opportunity()
        late = trade(at=AT + timedelta(minutes=20))
        self.assertIsNone(first_fill(r, "yes", [late], 15, "through"))
        self.assertIsNotNone(first_fill(r, "yes", [late], 65, "through"))
        late["is_block_trade"] = True
        self.assertIsNone(first_fill(r, "yes", [late], 65, "through"))

    def test_invalid_history_does_not_become_zero_loss(self):
        r = opportunity(history_status="unknown", outcome="yes")
        value = side_result(r, "yes", "baseline", False, "through", 0, [], AT + timedelta(days=1))
        self.assertIsNone(value["pnl"])
        with self.assertRaises(EvidenceError):
            first_fill(r, "yes", [trade(), trade()], 65, "through")

    def test_due_allowance_and_missing_exit_are_distinct_from_hold(self):
        r = opportunity(history_status="complete", trades=[trade()], outcome="no")
        due = AT + timedelta(minutes=20, seconds=60)
        value = side_result(r, "yes", "baseline", True, "through", 0, [], due)
        self.assertEqual(value["due"], 0)
        value = side_result(r, "yes", "baseline", True, "through", 0, [], due + timedelta(seconds=1))
        self.assertEqual(value["status"], "exit_observation_unknown")
        self.assertIsNone(value["pnl"])
        held = side_result(r, "yes", "baseline", False, "through", 0, [], due + timedelta(seconds=1))
        self.assertAlmostEqual(held["pnl"], -.43)

    def test_exit_costs_and_partial_depth_are_not_free(self):
        r = opportunity(history_status="complete", trades=[trade()], outcome="no")
        snapshot = book(AT + timedelta(minutes=20), yes="0.60", quantity="0.5")
        value = side_result(r, "yes", "baseline", True, "through", 2, [snapshot], AT + timedelta(hours=2))
        # Half exits at .58 with .01 fee; half settles to zero; .02 entry fee.
        self.assertAlmostEqual(value["pnl"], -.15)

    def test_no_fills_and_small_samples_cannot_pass_gate(self):
        r = opportunity(history_status="complete", trades=[])
        result = report([r], [], AT + timedelta(days=1), (AT + timedelta(days=30)).isoformat())
        self.assertEqual(result["review_gate"]["status"], "not_ready")
        self.assertFalse(result["review_gate"]["automatic_live_enable"])
        for entry in result["comparisons"].values():
            self.assertEqual(entry["net_pnl_complete_games"], 0)
            self.assertIsNone(entry["due_checkpoint_coverage"])


class CashTest(unittest.TestCase):
    def test_scalar_credit_is_cash_not_binary_outcome(self):
        events, raw = events_and_fill()
        settlement = {"ticker": raw["ticker"], "settled_time": (AT + timedelta(hours=1)).isoformat(),
                      "market_result": "scalar", "revenue": 0, "yes_count_fp": "0.01", "no_count_fp": "0"}
        r = reconciliation(events, [raw], [settlement], [], AT + timedelta(hours=2))
        self.assertEqual(r["status"], "reconciled")
        self.assertEqual(r["scalar_cash_reconciled"], 1)
        self.assertEqual(r["realized_pnl"], "-0.0032")
        self.assertEqual(r["markets"][0]["settlement_result"], "scalar")

    def test_scalar_requires_matching_quantity_and_flat_position(self):
        events, raw = events_and_fill()
        settlement = {"ticker": raw["ticker"], "settled_time": (AT + timedelta(hours=1)).isoformat(),
                      "market_result": "scalar", "revenue": 0, "yes_count_fp": "1", "no_count_fp": "0"}
        r = reconciliation(events, [raw], [settlement], [], AT + timedelta(hours=2))
        self.assertIsNone(r["realized_pnl"])
        self.assertEqual(r["status"], "needs_review")

    def test_unsettled_cost_is_not_counted_as_realized_loss(self):
        events, raw = events_and_fill(quantity="5")
        r = reconciliation(events, [raw], [], [{"ticker": raw["ticker"], "position_fp": "5"}], AT)
        self.assertEqual(float(r["realized_pnl"]), 0)
        self.assertEqual(float(r["unsettled_cost"]), 1.6)

    def test_unrecognized_shared_account_activity_blocks_totals(self):
        events, raw = events_and_fill()
        other = dict(raw, fill_id="other", order_id="someone-else")
        r = reconciliation(events, [raw, other], [], [], AT)
        self.assertIsNone(r["realized_pnl"])

    def test_missing_signed_journal_fill_cannot_be_silently_dropped(self):
        events, raw = events_and_fill()
        events.append({"event": "fill", "fill_id": "fill", "order_id": "order", "ticker": raw["ticker"]})
        r = reconciliation(events, [], [], [], AT)
        self.assertEqual(r["status"], "needs_review")

    def test_approved_manual_reduction_nets_once(self):
        events, raw = events_and_fill(quantity="1")
        _, close = events_and_fill(side="no", price="0.4", quantity="1")
        close.update(fill_id="close", order_id="manual", created_time=(AT + timedelta(seconds=1)).isoformat())
        events.append({"event": "external_close", "fill": close, "fill_sha256": digest(close),
                       "evidence": "owner_verified_signed_manual_close_v1", "reason": "owner_manual_cashout", "utc": (AT + timedelta(seconds=2)).isoformat()})
        r = reconciliation(events, [raw, close], [], [], AT + timedelta(seconds=3))
        self.assertEqual(r["status"], "reconciled")
        self.assertAlmostEqual(float(r["realized_pnl"]), .28)
        self.assertEqual(r["open_markets"], 0)


class DiagnosticsTest(unittest.TestCase):
    def test_fresh_projection_does_not_confirm_lineup_or_minutes(self):
        r = input_quality([{"snapshot_utc": AT.isoformat(), "minutes_estimate_source": "prior_games_only", "lineup_confirmation_status": "unverified"}], AT)
        self.assertEqual(r["issues"]["fully_verified_rows"], 0)
        self.assertEqual(r["issues"]["tonight_minutes_unverified"], 1)

    def test_calibration_uses_games_and_side_correct_probability(self):
        row = {"p_model_yes": .2, "result": "yes", "game_id": "one-game", "entry_book": book()["external_book"]}
        result = calibration([row, copy.deepcopy(row)])
        self.assertEqual(result["independent_games"], 1)
        self.assertAlmostEqual(result["mean_predicted_win_probability"], .8)
        self.assertAlmostEqual(result["model_brier"], .64)
        self.assertIsNone(result["model_minus_market_brier_game_95_interval"])

    def test_install_preserves_frozen_observer_and_trader_cron_lines(self):
        previous = "* * * * * frozen # spread-forward-readonly-v1\n* * * * * entry # spread-entry-readonly-v1\n"
        result = cron(previous, "* * * * * paper")
        self.assertTrue(result.startswith(previous))
        self.assertEqual(cron(result, "* * * * * paper"), result)

    def test_export_only_publishes_scoped_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text(json.dumps({"protocol": "spread-paper-execution-v1", "generated_at": AT.isoformat(), "report": {}, "raw_signed_fills": ["private"]}))
            out = json.loads(paused_research_file(path, "spread-paper-execution-v1"))
            self.assertNotIn("raw_signed_fills", out)
            with self.assertRaises(ExportError):
                paused_research_file(path, "wrong-version")


if __name__ == "__main__":
    unittest.main()
