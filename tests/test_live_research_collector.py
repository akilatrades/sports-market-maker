import unittest
from research.live_kalshi_collector import normalize_market, best_bid_levels
from research.research_monitor import summarize

class CollectorTests(unittest.TestCase):
    def test_normalize_market_uses_collection_time(self):
        row = normalize_market({"ticker":"KXNBA-X","event_ticker":"KXNBA-E","yes_bid_dollars":"0.43","volume_fp":"22"}, "2026-11-26T12:00:00+00:00")
        self.assertEqual(row["market_id"], "KXNBA-X")
        self.assertEqual(row["event_id"], "KXNBA-E")
        self.assertEqual(row["yes_bid_dollars"], "0.43")
        self.assertIn("collector_observation_time", row["snapshot_time_semantics"])

    def test_book_legacy_and_dollar_fields(self):
        self.assertEqual(best_bid_levels({"yes":[[40,10]],"no":[[50,5]]})["yes"], [[40,10]])
        self.assertEqual(best_bid_levels({"yes_dollars":[["0.4",10]],"no_dollars":[["0.5",5]]})["no"], [["0.5",5]])

    def test_public_print_not_own_fill_semantics_in_dashboard(self):
        counts, markets = summarize([{"market_id":"M","event_type":"public_trade"},{"market_id":"M","event_type":"fill"}])
        self.assertEqual(counts["public_trade"], 1)
        self.assertEqual(markets["M"]["private_fill_count"], 1)

if __name__ == "__main__":
    unittest.main()
