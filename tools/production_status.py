"""Read-only health snapshot of production services, NBA input files and journals.

No Kalshi credentials are loaded. This never contacts an exchange, places an
order, changes a systemd service or prints account balances / order IDs.

Run from an updated checkout or as a standalone downloaded script:
    python -m tools.production_status
    python /tmp/production_status.py
"""

import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

# Keep this diagnostic independent of the server's Python checkout version.
# It can run as a standalone downloaded script without installing new modules.
EXPECTED_SCHEMA = 2
EXPECTED_MODEL_VERSION = "nba-opening-v2"

STATE_ROOT = Path("/home/trader")
MARKETS = ("nfl", "nba")
UNITS = {
    market: (
        f"market-maker-prod-{market}-auto.timer",
        f"market-maker-prod-{market}-auto.service",
    )
    for market in MARKETS
}


def command(args):
    try:
        return subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=6
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


def service(unit):
    state = command(["systemctl", "is-active", unit])
    return (
        state
        if state in {"active", "inactive", "failed", "activating", "deactivating"}
        else "unavailable"
    )


def journal_summary(path):
    if not path.exists():
        return {"status": "missing"}
    try:
        raw = path.read_text(encoding="utf-8")
        if raw and not raw.endswith("\n"):
            return {"status": "write_in_progress"}
        events = [json.loads(line) for line in raw.splitlines() if line]
    except (OSError, ValueError):
        return {"status": "unreadable"}
    count = Counter(e.get("event") for e in events)
    return {
        "status": "local_snapshot_only_not_exchange_reconciled",
        "intents": count["intent"],
        "accepted": count["accepted"],
        "fill_events": count["fill"],
        "settlement_events": count["settlement"],
        "unknown_submissions": count["unknown_outcome"],
        "last_event_utc": events[-1].get("utc") if events else None,
    }


def model_bundle(folder, now):
    csv_path = folder / "latest.csv"
    meta_path = folder / "latest_meta.json"
    if not csv_path.exists() or not meta_path.exists():
        return {"status": "missing"}
    try:
        data = csv_path.read_bytes()
        meta = json.loads(meta_path.read_text())
        if (
            meta.get("schema_version") != EXPECTED_SCHEMA
            or meta.get("model_version") != EXPECTED_MODEL_VERSION
        ):
            return {"status": "blocked", "reason": "schema_or_model_version"}
        if hashlib.sha256(data).hexdigest() != meta.get("sha256"):
            return {"status": "blocked", "reason": "checksum_mismatch"}
        stamp = datetime.fromisoformat(meta["generated_utc"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return {"status": "blocked", "reason": "naive_timestamp"}
        age = (now - stamp).total_seconds() / 3600
        if not 0 <= age <= 9:
            return {"status": "blocked", "reason": "timestamp_outside_9_hours"}
        rows = sum(1 for _ in csv.DictReader(data.decode().splitlines()))
        if rows != meta["rows"]:
            return {"status": "row_count_mismatch"}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"status": "blocked", "reason": type(error).__name__}
    return {
        "status": "schema_hash_and_age_valid",
        "age_hours": round(age, 2),
        "rows": rows,
        "source_commit_short": str(meta.get("source_commit", ""))[:12],
    }


def sportsbook_rows(path):
    if not path.exists():
        return {"status": "missing", "rows": None}
    try:
        with path.open() as source:
            rows = list(csv.DictReader(source))
        return {
            "status": "file_present_not_feed_approval",
            "rows": len(rows),
            "rows_with_two_books": sum(float(r.get("book_n") or 0) >= 2 for r in rows),
        }
    except (OSError, ValueError, csv.Error):
        return {"status": "unreadable", "rows": None}


def scan_result(path, now):
    """A working timer is not proof that the last trading scan succeeded."""
    if not path.exists():
        return {"status": "no_completed_scan"}
    try:
        info = json.loads(path.read_text())
        when = datetime.fromisoformat(
            str(info.get("run_utc") or info.get("utc")).replace("Z", "+00:00")
        )
        if when.tzinfo is None:
            raise ValueError("Naive timestamp")
        age = (now - when).total_seconds() / 60
        if age < 0:
            raise ValueError("Scan timestamp in the future")
        return {
            "status": "recent_completed_scan" if age <= 20 else "stale_scan",
            "age_minutes": round(age, 1),
            "decision": info.get("decision"),
            "strategy_version": info.get("strategy_version"),
        }
    except (OSError, TypeError, ValueError, KeyError):
        return {"status": "unreadable_scan"}


def nfl_data_status(path, now):
    """Local input freshness only; NOT a validation of any trading edge."""
    bundle = path / "active"
    check = path / "last_check.json"
    if not bundle.is_dir() or not check.exists():
        return {"status": "missing_verified_bundle"}
    try:
        receipt = json.loads(check.read_text())
        stamp = datetime.fromisoformat(receipt["checked_utc"])
        if stamp.tzinfo is None:
            raise ValueError("No timezone")
        check_age = (now - stamp).total_seconds() / 60
        retrieved = json.loads((bundle / "data/nfl/retrieval.json").read_text())
        source_date = datetime.fromisoformat(retrieved["retrieved"]).replace(
            tzinfo=UTC
        )
        age = (now - source_date).total_seconds() / 3600
        if check_age < 0 or age < 0:
            raise ValueError("Future data")
        okay = check_age <= 20 and age <= 48
        return {
            "status": "locally_fresh" if okay else "stale",
            "check_age_minutes": round(check_age, 1),
            "schedule_age_hours": round(age, 1),
            "model_ladder": receipt.get("model_ladder"),
            "source_commit_short": str(receipt.get("source_commit", ""))[:12],
        }
    except (OSError, TypeError, ValueError, KeyError):
        return {"status": "unreadable_verified_bundle"}


def snapshot(root=STATE_ROOT, now=None):
    now = now or datetime.now(UTC)
    nba = root / "prod-nba-auto" / "inputs"
    return {
        "generated_utc": now.isoformat(),
        "provenance": (
            "LOCAL files and systemctl only; this is not a Kalshi API "
            "preflight or proof of live orders/fills/profit."
        ),
        "deployed_commit": command(["git", "rev-parse", "--short", "HEAD"]),
        "systemd": {
            key: {unit: service(unit) for unit in units} for key, units in UNITS.items()
        },
        "nba_inputs": model_bundle(nba, now),
        "nfl_verified_inputs": nfl_data_status(
            root / "prod-nfl-auto" / "inputs" / "nfl", now
        ),
        "last_completed_scans": {
            sport: scan_result(root / f"prod-{sport}-auto" / "last_scan.json", now)
            for sport in MARKETS
        },
        "nba_sportsbooks": sportsbook_rows(nba / "nba_books.csv"),
        "journals": {
            market: journal_summary(root / f"prod-{market}-auto" / "journal.jsonl")
            for market in MARKETS
        },
    }


def main():
    print(json.dumps(snapshot(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
