"""Track 3: weather markets against National Weather Service forecasts, a
forward recorder (RESEARCH_LOG.md, 2026-11-26, "Four more tracks"). Public
data only; places no order.

Every hour: for each Kalshi daily high-temperature series (KXHIGH...), every
open bracket's bid and ask; for the cities whose settlement station is
mapped, the NWS hourly forecast's maximum for each market date (local day).

    python -m research.weather_record --due
    python -m research.weather_record

Appends to outputs/weather/quotes_<YYYY-MM>.csv; last_run.txt beside it.
"""

import csv
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path("outputs/weather")
MIN_MINUTES_BETWEEN = 50
NWS = "https://api.weather.gov"
AGENT = "sports-market-maker research (github.com/akilatrades/sports-market-maker)"
# Kalshi settles on the NWS climate report for these stations.
STATIONS = {
    "KXHIGHNY": ("Central Park", 40.7789, -73.9692, "America/New_York"),
    "KXHIGHCHI": ("Chicago Midway", 41.7868, -87.7522, "America/Chicago"),
    "KXHIGHMIA": ("Miami Intl", 25.7959, -80.2870, "America/New_York"),
    "KXHIGHAUS": ("Austin Bergstrom", 30.1830, -97.6799, "America/Chicago"),
    "KXHIGHDEN": ("Denver Intl", 39.8466, -104.6562, "America/Denver"),
    "KXHIGHLAX": ("Los Angeles Intl", 33.9382, -118.3866, "America/Los_Angeles"),
    "KXHIGHPHIL": ("Philadelphia Intl", 39.8683, -75.2311, "America/New_York"),
}
FIELDS = ["utc", "series", "event_ticker", "ticker", "market_date", "strike_type",
          "floor_strike", "cap_strike", "yes_bid", "yes_ask", "volume", "close_time",
          "nws_max_f", "nws_hours", "station"]  # fmt: skip
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}  # fmt: skip


def due(now, out=OUT):
    try:
        last = datetime.fromisoformat((out / "last_run.txt").read_text("utf-8").strip())
    except (OSError, ValueError):
        return True
    return (now - last).total_seconds() >= MIN_MINUTES_BETWEEN * 60


def nws_json(url, timeout=20):
    request = urllib.request.Request(
        url, headers={"User-Agent": AGENT, "Accept": "application/geo+json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def market_date(event_ticker):
    """'KXHIGHNY-26NOV27' -> date(2026, 11, 27)."""
    code = str(event_ticker).rsplit("-", 1)[-1]
    try:
        return datetime(2000 + int(code[:2]), MONTHS[code[2:5]], int(code[5:7])).date()
    except (KeyError, ValueError):
        return None


def daily_max(periods, zone):
    """Local date -> (max forecast temperature in F, hours covered)."""
    out = {}
    tz = ZoneInfo(zone)
    for p in periods:
        try:
            start = datetime.fromisoformat(p["startTime"]).astimezone(tz)
            temp = float(p["temperature"])
        except (KeyError, TypeError, ValueError):
            continue
        if str(p.get("temperatureUnit", "F")).upper() == "C":
            temp = temp * 9 / 5 + 32
        best, hours = out.get(start.date(), (None, 0))
        out[start.date()] = (temp if best is None else max(best, temp), hours + 1)
    return out


def forecasts(fetch=nws_json):
    """Series -> {local date: (max F, hours)}; a failed city is left out."""
    out = {}
    for series, (_, lat, lon, zone) in STATIONS.items():
        try:
            point = fetch(f"{NWS}/points/{lat},{lon}")
            hourly = fetch(point["properties"]["forecastHourly"])
            out[series] = daily_max(hourly["properties"]["periods"], zone)
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return out


def rows(series, markets, forecast, utc):
    out = []
    for m in markets:
        day = market_date(m.get("event_ticker", ""))
        nws = forecast.get(day) if day else None
        out.append({
            "utc": utc, "series": series, "event_ticker": m.get("event_ticker", ""),
            "ticker": m.get("ticker", ""), "market_date": day.isoformat() if day else "",
            "strike_type": m.get("strike_type", ""), "floor_strike": m.get("floor_strike", ""),
            "cap_strike": m.get("cap_strike", ""), "yes_bid": m.get("yes_bid_dollars", ""),
            "yes_ask": m.get("yes_ask_dollars", ""), "volume": m.get("volume_fp", ""),
            "close_time": m.get("close_time", ""),
            "nws_max_f": "" if not nws else round(nws[0], 1), "nws_hours": "" if not nws else nws[1],
            "station": STATIONS.get(series, ("",))[0],
        })  # fmt: skip
    return out


def main(argv=None, out=OUT, fetch_markets=None, fetch=nws_json, now=None):
    argv = sys.argv[1:] if argv is None else argv
    out = Path(out)
    now = now or datetime.now(UTC)
    if "--due" in argv:
        print("due" if due(now, out) else "not due")
        return 0
    if fetch_markets is None:
        from kalshi.api import fetch_markets
    fc = forecasts(fetch)
    utc = now.isoformat(timespec="minutes")
    all_rows, counts = [], {}
    for series in STATIONS:
        try:
            markets = fetch_markets(series, status="open", historical=False)
        except OSError:
            markets = []
        got = rows(series, markets, fc.get(series, {}), utc)
        counts[series] = {"markets": len(got), "forecast_days": len(fc.get(series, {}))}
        all_rows += got
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"quotes_{now:%Y-%m}.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(all_rows)
    (out / "last_run.txt").write_text(now.isoformat(timespec="seconds"), "utf-8")
    print(json.dumps({"utc": utc, "rows": len(all_rows), "by_series": counts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
