"""Offline contract checks for local operator status; no exchange access."""

import json
from datetime import UTC, datetime

import pandas as pd

from live.nba_inputs import publish
from tools.production_status import journal_summary, model_bundle, sportsbook_rows


def test_journal_only_counts_local_events_without_exposing_ids(tmp_path):
    path = tmp_path / "journal.jsonl"
    path.write_text(
        json.dumps({
            "event": "intent", "client_order_id": "private-order",
            "ticker": "KXNBA-PRIVATE", "utc": "2026-10-18T12:00:00Z",
        })
        + "\n"
        + json.dumps({
            "event": "accepted", "order_id": "private-exchange-id",
            "utc": "2026-10-18T12:00:01Z",
        })
        + "\n"
    )
    report = journal_summary(path)
    assert report["intents"] == 1
    assert report["accepted"] == 1
    assert "private-order" not in str(report)
    assert "private-exchange-id" not in str(report)
    path.write_text('{"event":"intent"')
    assert journal_summary(path)["status"] == "write_in_progress"


def test_missing_and_fresh_projection_bundles(tmp_path):
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    assert model_bundle(tmp_path, now)["status"] == "missing"
    frame = pd.DataFrame({"ticker": ["A"], "p_model": [0.5]})
    publish(frame, tmp_path, now, schedule_games=1, open_markets=1)
    assert model_bundle(tmp_path, now)["status"] == "schema_hash_and_age_valid"
    assert model_bundle(
        tmp_path, datetime(2026, 10, 19, 12, tzinfo=UTC)
    )["status"] == "blocked"


def test_sportsbook_header_only_not_mistaken_for_two_book_coverage(tmp_path):
    path = tmp_path / "nba_books.csv"
    path.write_text("player_key,stat,line,p_book,book_n,snapshot_utc\n")
    result = sportsbook_rows(path)
    assert result["rows"] == 0
    assert result["rows_with_two_books"] == 0
