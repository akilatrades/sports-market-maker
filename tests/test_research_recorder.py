import tempfile
import unittest
from pathlib import Path

from research.recorder import append_records, validate_record

VALID = {
    "event_id": "evt-001",
    "market_id": "market-001",
    "event_type": "market_snapshot",
    "source_timestamp": "2026-11-26T18:00:00Z",
    "price_yes": 0.52,
}

class RecorderTests(unittest.TestCase):
    def test_validation_adds_schema_and_ingest_time(self):
        result = validate_record(VALID)
        self.assertEqual(result["schema_version"], 1)
        self.assertIn("ingested_at", result)

    def test_missing_fields_rejected(self):
        with self.assertRaises(ValueError):
            validate_record({"event_type": "fill"})

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            validate_record(dict(VALID, event_type="mystery"))

    def test_invalid_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            validate_record(dict(VALID, source_timestamp="not-a-date"))

    def test_append_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subdir" / "events.jsonl"
            self.assertEqual(append_records(path, [VALID, VALID]), 2)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

if __name__ == "__main__":
    unittest.main()
