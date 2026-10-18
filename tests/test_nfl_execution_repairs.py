"""Regression checks using local fixtures; never contact an exchange."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from kalshi.maker import fills
from live import prod_nfl_auto as auto
from research.quote_placement import policy_orders


class ExecutionRepairs(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.row = SimpleNamespace(
            ticker="KXNFLRECYDS-TEST-PLAYER-30",
            game_id="game",
            team="team",
            tip_utc=pd.Timestamp(self.now + timedelta(hours=1)),
            price=0.60,
        )

    def test_sizes_fit_every_cap_at_all_supported_prices(self):
        for cents in range(10, 91):
            with self.subTest(cents=cents):
                order, _ = auto.order_from_row(self.row, self.now, cents / 100)
                original_count = order.count
                cost = auto.fit_order_to_budget(order, [], [], self.row, self.now)
                self.assertIsNotNone(cost)
                self.assertLessEqual(order.count, original_count)
                self.assertLessEqual(auto.reserve(cost), auto.MAX_GAME_COST)
                self.assertTrue(auto.room_for([], [], self.row, cost, self.now))
                self.assertTrue(order.post_only)

    def test_sixty_cent_order_shrinks_instead_of_being_rejected(self):
        order, _ = auto.order_from_row(self.row, self.now)
        self.assertEqual(order.count, 5)
        cost = auto.fit_order_to_budget(order, [], [], self.row, self.now)
        self.assertEqual(order.count, 4)
        self.assertEqual(cost, 2.40)
        self.assertEqual(auto.reserve(cost), 2.64)

    def test_remaining_game_budget_is_respected(self):
        attempts = [
            {
                "cost": 2.0,
                "game_id": self.row.game_id,
                "team": self.row.team,
                "utc": self.now.isoformat(),
            }
        ]
        order, _ = auto.order_from_row(self.row, self.now)
        cost = auto.fit_order_to_budget(order, attempts, attempts, self.row, self.now)
        self.assertEqual(order.count, 1)
        self.assertEqual(cost, 0.60)
        self.assertTrue(auto.room_for(attempts, attempts, self.row, cost, self.now))

    def test_exhausted_lifetime_budget_stays_blocked(self):
        attempts = [
            {
                "cost": 3.0,
                "game_id": f"past{i}",
                "team": f"past{i}",
                "utc": (self.now - timedelta(days=1)).isoformat(),
            }
            for i in range(15)
        ]
        order, _ = auto.order_from_row(self.row, self.now)
        self.assertIsNone(
            auto.fit_order_to_budget(order, attempts, [], self.row, self.now)
        )
        self.assertIn(
            "lifetime_submission_budget",
            auto.budget_blockers(attempts, [], self.row, 0.60, self.now),
        )

    def test_current_and_legacy_cost_fields_have_identical_profit(self):
        current = {
            "revenue": 500,
            "yes_total_cost_dollars": "0.0000",
            "no_total_cost_dollars": "2.5000",
            "fee_cost": "0.0300",
        }
        legacy = {
            "revenue": 500,
            "yes_total_cost": 0,
            "no_total_cost": 250,
            "fee_cost": "0.0300",
        }
        self.assertEqual(
            auto.settlement_accounting(current), auto.settlement_accounting(legacy)
        )
        result = auto.settlement_accounting(current)
        self.assertEqual(result["net_profit_dollars"], 2.47)
        self.assertTrue(result["accounting_complete"])

    def test_missing_cost_or_fee_is_not_silently_zero(self):
        result = auto.settlement_accounting({"revenue": 500, "fee_cost": "0.03"})
        self.assertIsNone(result["no_cost_dollars"])
        self.assertIsNone(result["net_profit_dollars"])
        self.assertFalse(result["accounting_complete"])

    def test_legacy_journal_record_gets_one_append_only_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "journal.jsonl"
            old = {"event": "settlement", "ticker": "NFL-A", "fee_cents": ".03"}
            auto.write_event(journal, old)
            settlement = {
                "ticker": "NFL-A",
                "revenue": 500,
                "yes_total_cost_dollars": "0",
                "no_total_cost_dollars": "2.5",
                "fee_cost": ".03",
            }
            for _ in range(2):
                auto.record_execution(
                    journal,
                    auto.load_journal(journal),
                    [{"ticker": "NFL-A"}],
                    {},
                    [],
                    [settlement],
                )
            events = auto.load_journal(journal)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0], old)
            self.assertEqual(events[1]["net_profit_dollars"], 2.47)

    def test_no_candidate_report_explains_entry_window(self):
        frame = pd.DataFrame(
            [
                {
                    "injury_status": "",
                    "tip_utc": self.row.tip_utc,
                    "hours_to_tip": 5.0,
                    "ticker": self.row.ticker,
                }
            ]
        )
        counts = {}
        self.assertEqual(auto.select_candidates(frame, [], {}, self.now, counts), [])
        self.assertEqual(counts["verified_availability_and_time"], 1)
        self.assertEqual(counts["in_entry_window"], 0)

    def test_live_pass_uses_reduced_quantity_and_refreshes_queue(self):
        priced = pd.DataFrame(
            [
                {
                    **vars(self.row),
                    "injury_status": "",
                    "hours_to_tip": 1.0,
                    "yes_bid_dollars": 0.39,
                    "yes_ask_dollars": 0.42,
                    "p_model": 0.35,
                    "p_book": 0.30,
                }
            ]
        )
        client = Mock(env="prod", dry_run=False, can_sign=True)
        client.orders.return_value = []
        client.positions.return_value = []
        client.settlements.return_value = []
        client.fills.return_value = []
        client.balance.return_value = {"balance": 250.0}
        client.place.return_value = {"order_id": "owned-order"}
        client.queue_position.return_value = 4.0
        quote = {
            "status": "active",
            "yes_bid_dollars": "0.39",
            "yes_ask_dollars": "0.42",
        }
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "journal.jsonl"
            with patch.object(auto, "fetch_market", return_value=quote):
                self.assertTrue(
                    auto.pass_once(client, auto.REQUIRED, priced, self.now, journal)
                )
                report = json.loads((Path(directory) / "last_scan.json").read_text())
                self.assertEqual(report["decision"], "exchange_accepted")
                self.assertEqual(report["contracts"], 4)
                self.assertEqual(client.place.call_args.args[0].count, 4)
                client.orders.return_value = [
                    {"ticker": self.row.ticker, "order_id": "owned-order"}
                ]
                self.assertFalse(
                    auto.pass_once(client, auto.REQUIRED, priced, self.now, journal)
                )
            queues = [e for e in auto.load_journal(journal) if e["event"] == "queue"]
            self.assertEqual(len(queues), 2)
            self.assertEqual(client.place.call_count, 1)

    def test_two_tick_backtest_does_not_invent_one_tick_spread_priority(self):
        order = pd.DataFrame(
            [
                {
                    "ticker": "EXAMPLE",
                    "end_ts": 0,
                    "tip_ts": 10,
                    "yes_bid": 0.49,
                    "yes_ask": 0.50,
                    "p_model": 0.45,
                }
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "ticker": "EXAMPLE",
                    "ts": 5,
                    "yes_price": 0.50,
                    "count": 10,
                    "taker_outcome_side": "yes",
                }
            ]
        )
        for policy in ("improve1", "improve2"):
            quoted = policy_orders(order, policy)
            self.assertFalse(bool(quoted.iloc[0].improved))
            self.assertTrue(fills(quoted, trades).empty)


if __name__ == "__main__":
    unittest.main()
