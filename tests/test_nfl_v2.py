"""Financial admission checks on fixtures; no network calls or demo trades."""

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from kalshi.trading import Order, TradingError
from live.prod_nfl_auto import entry_evidence
from markets.nfl.paper import latest_ladder


class EntryChecks(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.row = SimpleNamespace(
            p_model=0.1939,
            p_book=None,
            model_made_utc=(self.now - timedelta(hours=1)).isoformat(),
        )
        self.order = Order(ticker="EXAMPLE", side="no", count=4, price_cents=66)

    def test_four_contract_math_uses_cost_plus_full_reserve(self):
        self.row.p_book = 0.1939  # v4: priced from the books only
        evidence = entry_evidence(self.row, self.order, 2.64)
        self.assertEqual(evidence["probability_source"], "sportsbook")
        self.assertEqual(evidence["fee_buffer_dollars"], 0.27)
        self.assertAlmostEqual(evidence["edge_after_fee_buffer"], 0.0786)

    def test_weak_edge_is_rejected_even_though_old_rule_would_enter(self):
        self.row.p_book = 0.32
        with self.assertRaisesRegex(TradingError, "insufficient_edge"):
            entry_evidence(self.row, self.order, 2.64)

    def test_v4_never_prices_from_the_model(self):
        # p_book is None: the model alone (19c YES, a big NO edge) cannot enter.
        with self.assertRaisesRegex(TradingError, "no_book_price"):
            entry_evidence(self.row, self.order, 2.64)

    def test_sportsbook_evidence_controls_when_available(self):
        self.row.p_book = 0.40
        with self.assertRaisesRegex(TradingError, "insufficient_edge"):
            entry_evidence(self.row, self.order, 2.64)

    def test_missing_stale_future_and_invalid_timestamp_block(self):
        for stamp in (
            None,
            "bad",
            self.now - timedelta(hours=37),
            self.now + timedelta(hours=1),
        ):
            with self.subTest(stamp=stamp):
                self.row.model_made_utc = stamp
                with self.assertRaisesRegex(TradingError, "model_timestamp"):
                    entry_evidence(self.row, self.order, 2.64)

    def test_invalid_probability_is_rejected(self):
        self.row.p_book = 0.20
        for probability in (float("nan"), float("inf"), -0.01, 1.01):
            self.row.p_model = probability
            with self.assertRaisesRegex(TradingError, "invalid_probability"):
                entry_evidence(self.row, self.order, 2.64)

    def test_fresh_filename_cannot_hide_stale_or_future_projection_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            rows = []
            for player, hours in (("stale", 37), ("fresh", 6), ("future", -1)):
                rows.append(
                    {
                        "game_id": "G",
                        "player_id": player,
                        "player": player,
                        "stat": "receiving_yards",
                        "line": 49.5,
                        "p_over": 0.4,
                        "made_utc": (self.now - timedelta(hours=hours)).isoformat(),
                    }
                )
            pd.DataFrame(rows).to_csv(
                folder / (self.now.strftime("test_%Y-%m-%dT%H%MZ") + ".csv.gz"),
                index=False,
            )
            ladder = latest_ladder(self.now, folder, max_age_hours=36)
            self.assertEqual(ladder.player.tolist(), ["fresh"])


if __name__ == "__main__":
    unittest.main()
