"""Verify V2 NO fills and malformed directions without account access."""

import unittest

from tools.export_verified_nfl import build, fill_direction


class Direction(unittest.TestCase):
    def test_v2_sell_yes_is_buy_no_exposure(self):
        value, issues, fields = fill_direction(
            {
                "action": "sell",
                "side": "yes",
                "outcome_side": "no",
                "book_side": "ask",
            }
        )
        self.assertEqual((value, issues), ("verified_no", []))
        self.assertEqual(fields["action"], "sell")

    def test_legacy_buy_no_remains_valid(self):
        self.assertEqual(
            fill_direction({"action": "buy", "side": "no"})[0], "verified_no"
        )

    def test_v2_without_deprecated_fields(self):
        self.assertEqual(
            fill_direction({"outcome_side": "no", "book_side": "ask"})[0],
            "verified_no",
        )

    def test_canonical_no_overrides_conflicting_deprecated_fields(self):
        status, issues, _ = fill_direction(
            {
                "action": "sell",
                "side": "no",
                "outcome_side": "no",
                "book_side": "ask",
            }
        )
        self.assertEqual(status, "verified_no")
        self.assertEqual(issues, ["legacy_direction_mismatch"])

    def test_conflicting_canonical_fields_never_count_as_no(self):
        status, issues, _ = fill_direction(
            {"outcome_side": "yes", "book_side": "ask"}
        )
        self.assertEqual(status, "review_required")
        self.assertIn("conflicting_canonical_directions", issues)

    def test_actual_production_payload_with_legacy_mismatch_is_counted(self):
        data = {
            "outcome_side": "no",
            "book_side": "ask",
            "action": "sell",
            "side": "no",
        }
        status, issues, _ = fill_direction(data)
        self.assertEqual(status, "verified_no")
        self.assertEqual(issues, ["legacy_direction_mismatch"])

    def test_unknown_direction_is_reported(self):
        self.assertEqual(fill_direction({})[0], "review_required")

    def test_exchange_fill_joined_and_summarized(self):
        events = [
            {
                "event": "intent",
                "client_order_id": "c",
                "utc": "2026-10-18T12:00:00Z",
                "ticker": "KXNFLRECYDS-TEST",
                "price_cents": 60,
                "count": 3,
                "cost": 1.8,
                "team": "DAL",
                "game_id": "TEST",
                "player": "Fixture",
            },
            {
                "event": "accepted",
                "client_order_id": "c",
                "order_id": "o",
                "utc": "2026-10-18T12:00:01Z",
            },
            {
                "event": "queue",
                "order_id": "o",
                "ahead": 6,
                "utc": "2026-10-18T12:00:02Z",
            },
        ]
        fills = [
            {
                "fill_id": "f",
                "order_id": "o",
                "ticker": "KXNFLRECYDS-TEST",
                "action": "sell",
                "side": "yes",
                "outcome_side": "no",
                "book_side": "ask",
                "count_fp": "2.00",
                "no_price_dollars": "0.6000",
                "fee_cost": "0.0000",
                "created_time": "2026-10-18T12:01:00Z",
                "is_taker": False,
            }
        ]
        result = build(events, fills, [])
        self.assertEqual(result["summary"]["exchange_verified_filled_contracts"], 2)
        self.assertEqual(result["summary"]["exchange_accepted_orders"], 1)
        self.assertEqual(result["summary"]["direction_review_fill_events"], 0)
        self.assertEqual(result["orders_including_zero_fills"][0]["filled_cost"], 1.2)
        self.assertEqual(result["orders_including_zero_fills"][0]["queue_initial"], 6)
        self.assertEqual(
            result["orders_including_zero_fills"][0]["queue_history"][0]["ahead"],
            6,
        )
        fills[0]["outcome_side"] = "yes"
        changed = build(events, fills, [])
        self.assertEqual(changed["summary"]["exchange_verified_filled_contracts"], 0)
        self.assertEqual(changed["summary"]["direction_review_fill_events"], 1)


if __name__ == "__main__":
    unittest.main()
