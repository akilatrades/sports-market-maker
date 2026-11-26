"""Weather recorder with fake NWS and Kalshi replies (no network)."""

import csv
from datetime import UTC, date, datetime, timedelta

from research import weather_record as W

NOW = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)


def test_event_dates_and_local_daily_maximum():
    assert W.market_date("KXHIGHNY-26NOV27") == date(2026, 11, 27)
    assert W.market_date("KXHIGHNY-BAD") is None
    periods = [
        {
            "startTime": "2026-11-27T14:00:00-05:00",
            "temperature": 48,
            "temperatureUnit": "F",
        },
        {
            "startTime": "2026-11-27T23:00:00-05:00",
            "temperature": 41,
            "temperatureUnit": "F",
        },
        {
            "startTime": "2026-11-28T00:00:00-05:00",
            "temperature": 55,
            "temperatureUnit": "F",
        },
        {
            "startTime": "2026-11-27T15:00:00-05:00",
            "temperature": 10,
            "temperatureUnit": "C",
        },
    ]
    got = W.daily_max(periods, "America/New_York")
    assert got[date(2026, 11, 27)] == (50.0, 3) and got[date(2026, 11, 28)] == (55.0, 1)


def test_a_run_records_brackets_with_the_forecast(tmp_path):
    def fetch(url):
        if "/points/" in url:
            return {"properties": {"forecastHourly": "hourly-url"}}
        start = datetime(2026, 11, 27, 18, tzinfo=UTC)
        return {"properties": {"periods": [
            {"startTime": (start + timedelta(hours=h)).isoformat(), "temperature": 40 + h,
             "temperatureUnit": "F"} for h in range(4)]}}  # fmt: skip

    def fetch_markets(series, status="open", historical=False):
        if series != "KXHIGHNY":
            return []
        return [{"ticker": "KXHIGHNY-26NOV27-B42.5", "event_ticker": "KXHIGHNY-26NOV27",
                 "strike_type": "between", "floor_strike": 42, "cap_strike": 43,
                 "yes_bid_dollars": "0.30", "yes_ask_dollars": "0.34"}]  # fmt: skip

    W.main([], out=tmp_path, fetch_markets=fetch_markets, fetch=fetch, now=NOW)
    rows = list(csv.DictReader(open(tmp_path / "quotes_2026-11.csv")))
    assert (
        len(rows) == 1
        and rows[0]["nws_max_f"] == "43.0"
        and rows[0]["station"] == "Central Park"
    )
    assert not W.due(NOW + timedelta(minutes=10), tmp_path)


def test_a_failed_forecast_never_stops_the_prices(tmp_path):
    def broken(url):
        raise OSError("down")

    W.main([], out=tmp_path, fetch_markets=lambda *a, **k: [{"event_ticker": "KXHIGHCHI-26NOV27",
           "ticker": "T"}], fetch=broken, now=NOW)  # fmt: skip
    rows = list(csv.DictReader(open(tmp_path / "quotes_2026-11.csv")))
    assert len(rows) == len(W.STATIONS) and all(r["nws_max_f"] == "" for r in rows)


def test_the_recorder_runs_in_the_hourly_job():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    flow = (root / ".github/workflows/paper-mentions.yml").read_text()
    assert (
        "python -m research.weather_record --due" in flow and "outputs/weather" in flow
    )
    text = (root / "research/weather_record.py").read_text()
    assert "import pandas" not in text  # the due check runs before the install
