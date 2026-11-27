import unittest
from research.microstructure_features import build_features, price_dollars, diagnostics


class MicrostructureFeatureTests(unittest.TestCase):
    def test_price_dollar_and_legacy_cent(self):
        self.assertEqual(price_dollars("0.45"), 0.45)
        self.assertEqual(price_dollars(45), 0.45)
        self.assertEqual(price_dollars(1), 1.0)

    def test_book_parsing_and_imbalance(self):
        events = [
            {
                "market_id": "M1",
                "event_id": "E1",
                "event_type": "book_snapshot",
                "source_timestamp": "2026-01-01T00:00:00Z",
                "yes_bid_levels": [["0.40", 10], ["0.39", 4]],
                "no_bid_levels": [["0.50", 5], ["0.49", 2]],
            },
            {
                "market_id": "M1",
                "event_id": "E1",
                "event_type": "book_snapshot",
                "source_timestamp": "2026-01-01T00:05:00Z",
                "yes_bid_levels": [["0.41", 12]],
                "no_bid_levels": [["0.49", 4]],
            },
            {
                "market_id": "M1",
                "event_id": "E1",
                "event_type": "book_snapshot",
                "source_timestamp": "2026-01-01T00:15:00Z",
                "yes_bid_levels": [["0.42", 12]],
                "no_bid_levels": [["0.48", 3]],
            },
        ]
        rows = build_features(events)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0]["yes_ask"], 0.5)
        self.assertAlmostEqual(rows[0]["mid"], 0.45)
        self.assertAlmostEqual(rows[0]["imbalance_1"], (10 - 5) / (10 + 5))
        self.assertAlmostEqual(rows[0]["mid_return_5m"], 0.01)
        self.assertAlmostEqual(rows[0]["mid_return_15m"], 0.02)
        self.assertEqual(rows[0]["mid_return_5m_observed_gap"], 5)
        self.assertEqual(rows[0]["mid_return_15m_observed_gap"], 15)

    def test_trade_flow_features(self):
        events = [
            {
                "market_id": "M2",
                "event_id": "E2",
                "event_type": "public_trade",
                "source_timestamp": "2026-01-01T00:04:00Z",
                "count_fp": "3",
                "taker_outcome_side": "yes",
            },
            {
                "market_id": "M2",
                "event_id": "E2",
                "event_type": "public_trade",
                "source_timestamp": "2026-01-01T00:04:30Z",
                "count_fp": "2",
                "taker_outcome_side": "no",
            },
            {
                "market_id": "M2",
                "event_id": "E2",
                "event_type": "book_snapshot",
                "source_timestamp": "2026-01-01T00:05:00Z",
                "yes_bid_levels": [["0.40", 10]],
                "no_bid_levels": [["0.50", 5]],
            },
        ]
        row = build_features(events)[0]
        self.assertEqual(row["public_trade_count_5m"], 2)
        self.assertEqual(row["public_volume_5m"], 5)
        self.assertAlmostEqual(row["public_flow_imbalance_5m"], 0.2)

    def test_diagnostics_sample_guard(self):
        rows = [{"imbalance_1": i / 10, "mid_return_5m": i / 100} for i in range(10)]
        result = diagnostics(rows)
        self.assertTrue(result)
        self.assertGreaterEqual(result[0]["n"], 6)


if __name__ == "__main__":
    unittest.main()
