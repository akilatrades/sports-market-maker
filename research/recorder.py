"""Append-only JSONL research event recorder. No exchange API and no order placement.

Use to persist normalized, timestamped market snapshots and order lifecycle observations.
The caller is responsible for collecting data and passing already-normalized records.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EVENT_TYPES = {
    "market_snapshot",
    "book_snapshot",
    "sportsbook_snapshot",
    "order_attempt",
    "order_ack",
    "order_reject",
    "order_cancel_request",
    "order_cancel_ack",
    "fill",
    "partial_fill",
    "settlement",
    "heartbeat",
}
REQUIRED = ("event_id", "market_id", "event_type", "source_timestamp")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED if record.get(key) in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    if record["event_type"] not in EVENT_TYPES:
        raise ValueError(f"Unknown event_type: {record['event_type']}")
    # Keep source time distinct from ingestion time. Preserve source format, but
    # require an ISO-like string so records can be audited and sorted.
    if not isinstance(record["source_timestamp"], str):
        raise ValueError("source_timestamp must be an ISO timestamp string")
    result = dict(record)
    result.setdefault("schema_version", 1)
    result.setdefault("ingested_at", utc_now())
    return result


def append_records(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with destination.open("a", encoding="utf-8") as handle:
        for record in records:
            normalized = validate_record(record)
            handle.write(json.dumps(normalized, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and append normalized research events from stdin JSON.")
    parser.add_argument("--output", default="data/research/events.jsonl")
    args = parser.parse_args()
    records = []
    for line in __import__("sys").stdin:
        line = line.strip()
        if line:
            records.append(json.loads(line))
    n = append_records(args.output, records)
    print(f"appended {n} validated records to {args.output}")


if __name__ == "__main__":
    main()
