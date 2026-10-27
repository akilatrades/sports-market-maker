"""Reporter contracts and atomic installation; synthetic data, no network."""

import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from deploy.repair_spread_export import digest, install_candidate, verify_accounting
from tools import export_private_fills as export

STAMP = "2026-10-27T12:00:00+00:00"
CLOSE = {
    "event": "external_close",
    "utc": STAMP,
    "reason": "owner_manual_cashout",
    "evidence": "owner_verified_signed_manual_close_v1",
    "fill_sha256": "a" * 64,
    "snapshot_sha256": "b" * 64,
    "fill": {"fill_id": "secret-fill", "order_id": "secret-order", "nested": {"private": "preserve-for-hash"}},
}
APPROVED = {
    "secret-fill": {
        "fid": "secret-fill", "oid": "secret-order", "ticker": "TEST-MARKET",
        "when": STAMP, "side": "no", "count": "2", "price": ".55", "fee": ".02",
    }
}
LEDGER = {
    "cumulative": .28, "daily": .28, "by_day": {"2026-10-27": .28},
    "open": {}, "settled": set(), "fills": 2,
}


class ExportRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "journal.jsonl"
        self.path.write_text(json.dumps(CLOSE) + "\n")

    def accounting(self, failure=None):
        def ledger(records, fills, settlements, as_of):
            self.assertEqual(records[-1], CLOSE)
            if failure:
                raise ValueError(failure)
            return copy.deepcopy(LEDGER)

        def approved(records, fills, as_of):
            self.assertEqual(records[-1]["fill"], CLOSE["fill"])
            return copy.deepcopy(APPROVED)

        return SimpleNamespace(spread_ledger=ledger, external_closes=SimpleNamespace(approved=approved))

    def build(self, accounting):
        with patch("live.shared_account_risk", accounting, create=True):
            return export.build_files({"spread": self.path}, forward=self.root / "absent")

    def test_verified_evidence_reaches_ledger_but_raw_identifiers_never_export(self):
        files, summary, complete = self.build(self.accounting())
        result = summary["markets"]["spread"]
        self.assertEqual(complete, {"spread"})
        self.assertEqual(result["realized_pnl_dollars"], .28)
        self.assertEqual(result["realized_pnl_status"], "verified")
        self.assertEqual(result["verified_external_close_fills"], 1)
        text = "".join(files.values())
        for private in ("secret-fill", "secret-order", "preserve-for-hash", "snapshot_sha256"):
            self.assertNotIn(private, text)
        rows = list(csv.DictReader(io.StringIO(files["data/spread/external_closes/2026-10-27.csv"])))
        self.assertEqual(rows[0]["fill_ref"], export.ref("secret-fill"))
        self.assertEqual(rows[0]["source"], "owner_verified_manual_cashout")

    def test_invalid_evidence_clears_pnl_file_and_keeps_unavailable_distinct_from_zero(self):
        files, summary, complete = self.build(self.accounting("evidence rejected"))
        result = summary["markets"]["spread"]
        self.assertEqual(complete, set())
        self.assertIsNone(result["realized_pnl_dollars"])
        self.assertEqual(result["realized_pnl_status"], "unavailable")
        self.assertEqual(list(csv.DictReader(io.StringIO(files["data/spread/pnl_by_day.csv"]))), [])
        self.assertFalse(any("external_closes/" in p for p in files))

    def test_old_runtime_cannot_silently_ignore_manual_close(self):
        old = SimpleNamespace(spread_ledger=lambda *args: copy.deepcopy(LEDGER))
        _, summary, _ = self.build(old)
        self.assertEqual(summary["markets"]["spread"]["realized_pnl_note"], "external_close_ledger_unavailable")

    def test_deployment_preflight_requires_direct_ledger_equality(self):
        with patch("live.shared_account_risk", self.accounting(), create=True):
            verify_accounting(export, [copy.deepcopy(CLOSE)])
            wrong = SimpleNamespace(
                KEEP_SPREAD=export.KEEP_SPREAD,
                spread_tables=lambda *args, **kwargs: (None, None, None, None, {**LEDGER, "cumulative": 999}),
            )
            with self.assertRaisesRegex(ValueError, "accounting_mismatch"):
                verify_accounting(wrong, [copy.deepcopy(CLOSE)])

    def test_atomic_install_backups_and_repeated_install_is_noop(self):
        target, source, backup = (self.root / name for name in ("target", "source", "backup"))
        target.write_bytes(b"old")
        source.write_bytes(b"new")
        target.chmod(0o640)
        self.assertTrue(install_candidate(source, target, backup, digest(b"old")))
        self.assertEqual(backup.read_bytes(), b"old")
        self.assertEqual(target.read_bytes(), b"new")
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertFalse(install_candidate(source, target, backup, digest(b"old")))

    def test_unexpected_baseline_or_backup_refuses_install(self):
        target, source, backup = (self.root / name for name in ("target", "source", "backup"))
        target.write_bytes(b"old")
        source.write_bytes(b"new")
        with self.assertRaisesRegex(ValueError, "baseline"):
            install_candidate(source, target, backup, digest(b"unknown"))
        backup.write_bytes(b"other")
        with self.assertRaisesRegex(ValueError, "backup"):
            install_candidate(source, target, backup, digest(b"old"))
        self.assertEqual(target.read_bytes(), b"old")

    def test_symlink_is_rejected_even_when_content_already_matches(self):
        source, target, backup = (self.root / name for name in ("source", "target", "backup"))
        source.write_bytes(b"same")
        target.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "symlink"):
            install_candidate(source, target, backup)


if __name__ == "__main__":
    unittest.main()
