"""Offline regressions for the worker's memory use and projection selection."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from markets.nfl.data import load_schedule
from markets.nfl.paper import latest_ladder


class LightweightInputs(unittest.TestCase):
    def test_dashboard_does_not_import_the_analysis_stack(self):
        script = """
import importlib.abc
import sys
class BlockAnalysis(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pandas', 'numpy', 'scipy', 'sklearn'}:
            raise AssertionError('Dashboard imported ' + fullname)
sys.meta_path.insert(0, BlockAnalysis())
import live.account_dashboard
assert 'live.prod_nfl_auto' not in sys.modules
"""
        subprocess.run([sys.executable, "-c", script], check=True, timeout=20)

    def test_schedule_does_not_require_player_history(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "games.csv").write_text("game_id,gameday\nG,2026-10-18\n")
            self.assertEqual(load_schedule(folder).game_id.tolist(), ["G"])

    def test_latest_rows_survive_chunk_and_file_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            base = self.row("A", "2026-10-18T12:00:00Z", 0.2)
            # Place the replacement in a later read chunk, then a later file.
            pd.DataFrame(
                [base] * 10_000 + [self.row("A", "2026-10-18T13:00:00Z", 0.3)]
            ).to_csv(folder / "test_2026-10-18T1300Z.csv.gz", index=False)
            pd.DataFrame(
                [
                    self.row("A", "2026-10-18T14:00:00Z", 0.4),
                    self.row("stale", "2026-10-16T01:00:00Z", 0.5),
                    self.row("future", "2026-10-19T01:00:00Z", 0.5),
                ]
            ).to_csv(folder / "test_2026-10-18T1400Z.csv.gz", index=False)
            result = latest_ladder(pd.Timestamp("2026-10-18T15:00Z"), folder, 36)
            self.assertEqual(result.player_id.tolist(), ["A"])
            self.assertEqual(result.p_over.tolist(), [0.4])

    def test_conflicts_block_without_reviving_older_probabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pd.DataFrame(
                [
                    self.row("A", "2026-10-18T12:00:00Z", 0.2),
                    self.row("A", "2026-10-18T13:00:00Z", 0.3),
                    self.row("B", "2026-10-18T13:00:00Z", 0.5),
                ]
            ).to_csv(folder / "test_2026-10-18T1300Z.csv.gz", index=False)
            pd.DataFrame(
                [
                    self.row("A", "2026-10-18T13:00:00Z", 0.4),
                    self.row("B", "2026-10-18T13:00:00Z", 0.5),
                ]
            ).to_csv(folder / "test_2026-10-18T1400Z.csv.gz", index=False)
            result = latest_ladder(pd.Timestamp("2026-10-18T15:00Z"), folder, 36)
            self.assertEqual(result.player_id.tolist(), ["B"])
            pd.DataFrame([self.row("A", "2026-10-18T14:30:00Z", 0.6)]).to_csv(
                folder / "test_2026-10-18T1430Z.csv.gz", index=False
            )
            result = latest_ladder(pd.Timestamp("2026-10-18T15:00Z"), folder, 36)
            self.assertEqual(
                result.set_index("player_id").p_over.to_dict(), {"A": 0.6, "B": 0.5}
            )

    @staticmethod
    def row(player, made, probability):
        return {
            "game_id": "G",
            "player_id": player,
            "player": player,
            "stat": "receiving_yards",
            "line": 49.5,
            "p_over": probability,
            "made_utc": made,
        }


if __name__ == "__main__":
    unittest.main()
