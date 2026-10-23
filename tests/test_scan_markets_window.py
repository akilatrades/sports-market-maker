"""Scan options for the spread maker's start-time study (RESEARCH_LOG.md, 2026-10-23)."""

import json
from pathlib import Path

import pandas as pd
import pytest

import research.scan_markets as scan


def test_window_is_parsed_and_checked():
    assert scan.parse_window("24,4") == (24, 4)
    assert scan.parse_window("7,4") == (7, 4)
    for bad in ("4,7", "0,0", "49,4", "24", "a,b"):
        with pytest.raises(ValueError):
            scan.parse_window(bad)


def test_milestones_are_kept_only_for_their_own_event(monkeypatch):
    payload = {
        "milestones": [
            {
                "start_date": "2026-03-01T18:00:00Z",
                "type": "basketball_game",
                "primary_event_tickers": ["KXNCAAWBGAME-26MAR01AB"],
            },
            {
                "start_date": "2026-03-01T19:00:00Z",
                "type": "basketball_game",
                "related_event_tickers": ["KXOTHER-26MAR01CD"],
            },
            {"type": "no_start", "primary_event_tickers": ["KXNCAAWBGAME-26MAR01AB"]},
        ]
    }
    seen = {}

    def fake(path, params):
        seen.update(path=path, **params)
        return payload

    monkeypatch.setattr(scan, "get_json", fake)
    out = scan.milestones_for("KXNCAAWBGAME-26MAR01AB")
    assert out == [
        {"start": "2026-03-01T18:00:00Z", "end": None, "type": "basketball_game"}
    ]
    assert seen == {
        "path": "/milestones",
        "related_event_ticker": "KXNCAAWBGAME-26MAR01AB",
        "limit": 100,
    }


def test_event_rows_record_expiry_ticker_start_and_milestones(monkeypatch):
    monkeypatch.setattr(
        scan,
        "milestones_for",
        lambda e: [{"start": "x", "end": None, "type": "t"}] if "AB" in e else [],
    )
    m = pd.DataFrame(
        {
            "event_ticker": [
                "KXDOTA2GAME-26OCT221800AB",
                "KXDOTA2GAME-26OCT221800AB",
                "KXNCAAWBGAME-26MAR01CD",
            ],
            "expiry": pd.to_datetime(
                ["2026-10-23T02:00Z", "2026-10-23T03:00Z", "2026-03-02T01:00Z"],
                utc=True,
            ),
        }
    )
    rows, failed = scan.event_rows(m)
    rows = rows.set_index("event_ticker")
    assert failed == 0
    dota = rows.loc["KXDOTA2GAME-26OCT221800AB"]
    assert dota.expiry.startswith("2026-10-23T03:00")  # the latest market's expiry
    assert dota.ticker_start.startswith("2026-10-22T22:00")  # 18:00 New York time
    assert json.loads(dota.milestones)[0]["type"] == "t"
    assert pd.isna(rows.loc["KXNCAAWBGAME-26MAR01CD"].ticker_start)


def test_main_points_every_stage_at_the_chosen_window_and_folder(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        scan,
        "report_stage",
        lambda: calls.update(out=scan.OUT, window=scan.WINDOW, starts=scan.STARTS),
    )
    monkeypatch.setattr(scan, "WINDOW", (7, 4))
    monkeypatch.setattr(scan, "OUT", Path("outputs/scan"))
    monkeypatch.setattr(scan, "STARTS", False)
    scan.main(
        ["report", "--window", "24,4", "--out", str(tmp_path / "scan_24h"), "--starts"]
    )
    assert calls == {"out": tmp_path / "scan_24h", "window": (24, 4), "starts": True}


def test_workflow_maps_only_fixed_choices_to_the_new_scan():
    text = (
        Path(__file__).resolve().parents[1] / ".github/workflows/scan.yml"
    ).read_text()
    assert "type: choice" in text and '- "24,4"' in text
    assert (
        "SCAN_OUT: ${{ inputs.window == '24,4' && 'outputs/scan_24h' || 'outputs/scan' }}"
        in text
    )
    assert '--window "$SCAN_WINDOW" --out "$SCAN_OUT" $SCAN_STARTS' in text
