"""Evidence safety tests with no account connection or credentials."""

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import pytest
from tools import account_reconciliation_snapshot as R

NOW = datetime(2026, 10, 25, 17, tzinfo=UTC)


def evidence():
    return {
        "source": "signed_exchange_gets",
        "complete_pagination": True,
        "stable_capture": True,
        "started_utc": NOW.isoformat(),
        "finished_utc": NOW.isoformat(),
        "journals": {
            "spread": [
                {
                    "event": "intent",
                    "client_order_id": "c",
                    "ticker": "T",
                    "utc": NOW.isoformat(),
                },
                {"event": "accepted", "client_order_id": "c", "order_id": "bot"},
            ]
        },
        "fills": [
            {"fill_id": "f", "order_id": "manual", "ticker": "T", "count_fp": "5.00"}
        ],
        "resting_orders": [],
        "positions": [],
    }


def test_manual_fill_remains_review_only():
    s = evidence()
    before = deepcopy(s)
    p = R.plan(s, NOW)
    assert p["candidate_external_fills"][0]["fill_id"] == "f"
    assert s == before
    assert p["safe_to_resume"] is False and p["positions_verified"] is False
    assert p["journal_changes"] == 0


def test_stale_and_partial_capture_rejected():
    with pytest.raises(R.ReconciliationError):
        R.plan(evidence(), NOW + timedelta(minutes=6))
    for field in ("complete_pagination", "stable_capture"):
        s = evidence()
        s[field] = False
        with pytest.raises(R.ReconciliationError):
            R.plan(s, NOW)


def test_conflicting_fill_copies_rejected():
    s = evidence()
    s["fills"].append({**s["fills"][0], "count_fp": "6.00"})
    with pytest.raises(R.ReconciliationError):
        R.plan(s, NOW)


def test_identical_duplicate_deduplicated():
    s = evidence()
    s["fills"] *= 2
    assert len(R.plan(s, NOW)["candidate_external_fills"]) == 1


def test_unknown_orders_never_adopted():
    s = evidence()
    s["resting_orders"] = [{"order_id": "unknown"}]
    assert len(R.plan(s, NOW)["unowned_resting_orders"]) == 1


def test_private_output_cannot_overwrite(tmp_path):
    p = tmp_path / "private.json"
    R.write_private(p, {"private": "value"})
    assert os.stat(p).st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        R.write_private(p, {})
    assert json.loads(p.read_text()) == {"private": "value"}


def test_repeated_cursor_not_complete():
    class Client:
        def _request(self, *args):
            return {"fills": [], "cursor": "repeat"}

    with pytest.raises(R.ReconciliationError):
        R.pages(Client(), "/portfolio/fills")


def test_capture_rejects_changing_account(tmp_path):
    for cohort in ("nba", "nfl", "spread"):
        p = tmp_path / f"prod-{cohort}-auto"
        p.mkdir()
        (p / "journal.jsonl").write_text(
            json.dumps({"event": "intent", "utc": NOW.isoformat()}) + "\n"
        )

    class Client:
        reads = 0

        def _request(self, method, path, params):
            assert method == "GET"
            key = R.READ_PATHS[path]
            if key == "market_positions":
                self.reads += 1
                return {key: [{"position": self.reads}]}
            return {key: []}

    with pytest.raises(R.ReconciliationError, match="changed"):
        R.capture(Client(), tmp_path, NOW)
