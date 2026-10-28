import json
import tempfile
import unittest
from pathlib import Path

from deploy.pause_spread_entries import owned_ids, owned_resting, set_stop, wait_idle


class PauseSpreadTests(unittest.TestCase):
    def test_preserves_existing_stop_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stop = root / "KILL"
            self.assertTrue(set_stop(stop))
            stop.write_text("prior owner reason")
            self.assertFalse(set_stop(stop))
            self.assertEqual(stop.read_text(), "prior owner reason")
            stop.unlink()
            target = root / "unrelated"
            target.write_text("unchanged")
            stop.symlink_to(target)
            with self.assertRaises(ValueError):
                set_stop(stop)
            self.assertEqual(target.read_text(), "unchanged")

    def test_owned_only_and_missing_identity_fails_closed(self):
        rows = [
            {"order_id": "known", "status": "resting", "client_order_id": "old"},
            {"order_id": "new", "status": "resting", "client_order_id": "smm-spread-x"},
            {"order_id": "other", "status": "resting", "client_order_id": "smm-nba"},
        ]
        self.assertEqual(owned_resting(rows, {"known"}), rows[:2])
        with self.assertRaises(ValueError):
            owned_resting([{"status": "resting"}], set())

    def test_drain_wait_and_journal_read_do_not_change_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "lock"
            lock.touch()
            wait_idle(lock, timeout=0)
            journal = root / "journal.jsonl"
            text = json.dumps({"event": "accepted", "order_id": "known"}) + "\n"
            journal.write_text(text)
            self.assertEqual(owned_ids(journal), {"known"})
            self.assertEqual(journal.read_text(), text)
            journal.write_text(text.rstrip())
            with self.assertRaises(ValueError):
                owned_ids(journal)


if __name__ == "__main__":
    unittest.main()
