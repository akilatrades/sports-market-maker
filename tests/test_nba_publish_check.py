"""Guard the NBA public projection publication contract without live trading."""

import csv
import io
import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from live.nba_inputs import publish
from live.nba_publish_check import inspect


def frame(ticker="KXNBAPTS-TEST", probability=0.42):
    return pd.DataFrame(
        {
            "ticker": [ticker],
            "p_model": [probability],
            "tip_utc": ["2026-10-20T19:00:00+00:00"],
            "injury_status": [""],
            "game_id": [123],
            "player_id": [555],
            "requires_book": [True],
            "team_espn": ["BOS"],
        }
    )


def bundle(tmp_path, now, frame_to_publish=None, **meta):
    publish(
        frame() if frame_to_publish is None else frame_to_publish,
        tmp_path,
        now,
        schedule_games=meta.get("schedule_games", 1),
        open_markets=meta.get("open_markets", 1),
    )
    return (
        (tmp_path / "latest.csv").read_bytes(),
        json.loads((tmp_path / "latest_meta.json").read_text()),
    )


def test_valid_publish_bundle_contains_current_schema_and_checksum(tmp_path):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    data, meta = bundle(tmp_path, now)
    result = inspect(data, meta, now + timedelta(minutes=5))
    assert result["rows"] == 1
    assert result["schedule_games"] == 1
    assert result["checksum"] == meta["sha256"]


def test_reject_missing_or_duplicated_tickers(tmp_path):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    for value in ("", "KXNBAPTS-TEST"):
        bad = pd.concat([frame(), frame(ticker=value)], ignore_index=True)
        data, meta = bundle(tmp_path, now, bad)
        with pytest.raises(ValueError, match="ticker"):
            inspect(data, meta, now)


def test_reject_nan_or_out_of_range_probabilities(tmp_path):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    for probability in (float("nan"), -0.01, 1.01):
        data, meta = bundle(tmp_path, now, frame(probability=probability))
        with pytest.raises(ValueError, match="probability"):
            inspect(data, meta, now)


def test_refuse_empty_snapshot_when_games_and_markets_open(tmp_path):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    empty = frame().iloc[:0].copy()
    data, meta = bundle(tmp_path, now, empty)
    with pytest.raises(ValueError, match="no_priced_rows"):
        inspect(data, meta, now)
    data, meta = bundle(tmp_path, now, empty, schedule_games=0, open_markets=0)
    assert inspect(data, meta, now)["rows"] == 0


def test_reject_stale_or_corrupted_snapshot(tmp_path):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    data, meta = bundle(tmp_path, now)
    with pytest.raises(ValueError, match="age"):
        inspect(data, meta, now + timedelta(hours=10))
    with pytest.raises(ValueError, match="checksum"):
        inspect(data + b"extra", meta, now)


def test_reject_unexpected_csv_row_count(tmp_path):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    data, meta = bundle(tmp_path, now)
    reader = csv.DictReader(io.StringIO(data.decode()))
    assert list(reader)
    meta["rows"] = 2
    with pytest.raises(ValueError, match="row_count_mismatch"):
        inspect(data, meta, now)
