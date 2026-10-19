"""Read-only health snapshot of production services, NBA input files and journals.

No Kalshi credentials are loaded. This never contacts an exchange, places an
order, changes a systemd service or prints account balances / order IDs.

Run from the deployed checkout:
    python -m tools.production_status
"""
import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from live.nba_inputs import validate

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
    return state if state in {
        "active", "inactive", "failed", "activating", "deactivating"
    } else "unavailable"


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
        age = validate(data, meta, now)
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
            "rows_with_two_books": sum(
                float(r.get("book_n") or 0) >= 2 for r in rows
            ),
        }
    except (OSError, ValueError, csv.Error):
        return {"status": "unreadable", "rows": None}


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
            key: {unit: service(unit) for unit in units}
            for key, units in UNITS.items()
        },
        "nba_inputs": model_bundle(nba, now),
        "nba_sportsbooks": sportsbook_rows(nba / "nba_books.csv"),
        "journals": {
            market: journal_summary(
                root / f"prod-{market}-auto" / "journal.jsonl"
            )
            for market in MARKETS
        },
    }


def main():
    print(json.dumps(snapshot(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
