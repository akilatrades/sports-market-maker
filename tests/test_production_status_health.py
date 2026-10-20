"""Status output distinguishes healthy timers from stale worker and input data."""

import json
from datetime import UTC, datetime, timedelta

from tools.production_status import nfl_data_status, scan_result

NOW = datetime(2026, 10, 20, 2, tzinfo=UTC)


def test_recent_and_stale_completed_scans(tmp_path):
    path = tmp_path / "last_scan.json"
    assert scan_result(path, NOW)["status"] == "no_completed_scan"
    path.write_text(
        json.dumps(
            {
                "run_utc": (NOW - timedelta(minutes=4)).isoformat(),
                "decision": "no_eligible_candidates",
            }
        )
    )
    assert scan_result(path, NOW)["status"] == "recent_completed_scan"
    path.write_text(
        json.dumps(
            {
                "utc": (NOW - timedelta(hours=1)).isoformat(),
                "decision": "all_candidates_blocked",
            }
        )
    )
    assert scan_result(path, NOW)["status"] == "stale_scan"


def test_nfl_input_health_never_claims_exchange_verified(tmp_path):
    root = tmp_path / "inputs" / "nfl"
    assert nfl_data_status(root, NOW)["status"] == "missing_verified_bundle"
    (root / "active" / "data/nfl").mkdir(parents=True)
    (root / "active" / "data/nfl/retrieval.json").write_text(
        json.dumps({"retrieved": "2026-10-20"})
    )
    (root / "last_check.json").write_text(
        json.dumps(
            {
                "checked_utc": (NOW - timedelta(minutes=2)).isoformat(),
                "source_commit": "a" * 40,
                "model_ladder": "week07.csv.gz",
            }
        )
    )
    healthy = nfl_data_status(root, NOW)
    assert healthy["status"] == "locally_fresh"
    assert healthy["source_commit_short"] == "a" * 12
    assert nfl_data_status(root, NOW + timedelta(hours=50))["status"] == "stale"
