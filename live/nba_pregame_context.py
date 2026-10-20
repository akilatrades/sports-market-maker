"""Timestamped, identity-checked NBA pregame minutes and confirmed starters.

RotoWire NBA/DailyProjectedMinutes.php and NBA/Lineups.php are licensed
sources; calling them requires ROTOWIRE_API_KEY in the *server environment*.
No public-site scraping, invented starting fives, or unlicensed data copies.
The feeds' RotoWire player IDs are NOT ESPN IDs. Only unique team+full-name
matches are accepted; ambiguous or missing observations stay unverified.

Never equate a historical minutes average with tonight's independent forecast.
"""

from datetime import UTC, datetime
import json
import math
import os
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import pandas as pd
from kalshi.books import normalize_name

API = "https://api.rotowire.com/Basketball/NBA"
ALLOWED_ENDPOINTS = {"DailyProjectedMinutes", "Lineups"}
TEAM_ALIASES = {
    "BKN": "BKN", "BRK": "BKN", "BK": "BKN",
    "GS": "GS", "GSW": "GS", "NYK": "NY", "NY": "NY",
    "NOP": "NO", "NO": "NO", "PHX": "PHX", "PHO": "PHX",
    "SAS": "SA", "SA": "SA", "UTA": "UTAH", "UTAH": "UTAH",
}
MAX_SOURCE_AGE_MINUTES = 15


def _team(value):
    value = str(value or "").strip().upper()
    return TEAM_ALIASES.get(value, value)


def _day(value):
    when = pd.Timestamp(value)
    if pd.isna(when) or when.tzinfo is None:
        raise ValueError("Pregame game timestamp must have timezone")
    return when.tz_convert("America/New_York").strftime("%Y-%m-%d")


def _date(when):
    return pd.Timestamp(when).tz_convert("America/New_York").strftime("%Y-%m-%d")


def _name(player):
    first = str(player.get("FirstName") or player.get("Firstname") or "").strip()
    last = str(player.get("LastName") or player.get("Lastname") or "").strip()
    return normalize_name((" ".join((first, last))).strip())


def fetch(endpoint, day, key):
    """Read only from documented licensed endpoints, never cache API keys."""
    if endpoint not in ALLOWED_ENDPOINTS or not key:
        raise ValueError("Unconfigured or unsupported pregame vendor endpoint")
    url = API + "/" + endpoint + ".php?" + urllib.parse.urlencode(
        {"key": key, "date": day, "format": "json"}
    )
    request = urllib.request.Request(url, headers={"User-Agent": "sports-market-maker/1"})
    with urllib.request.urlopen(request, timeout=12) as response:
        if response.geturl().split("?")[0] != API + "/" + endpoint + ".php":
            raise ValueError("Pregame vendor unexpectedly redirected")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Pregame vendor response too large")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("Date") != day:
        raise ValueError("Wrong-date or malformed NBA pregame vendor snapshot")
    if not isinstance(payload.get("Games"), list):
        raise ValueError("Missing NBA pregame games")
    return payload


def parse_minutes(payload, day):
    """Return (day, ESPN-normalized-team-code, player-name) -> expected minutes."""
    if payload.get("Date") != day or not isinstance(payload.get("Games"), list):
        raise ValueError("Wrong-date minutes report")
    result = {}
    for game in payload["Games"]:
        if not isinstance(game, dict) or _day(game["DateTime"]) != day:
            raise ValueError("Invalid pregame minutes game timestamp")
        for team in game.get("Teams", []):
            code = _team(team.get("Code"))
            if not code or not isinstance(team.get("Players"), list):
                raise ValueError("Invalid pregame minutes team")
            for person in team["Players"]:
                name = _name(person)
                raw = person.get("Projections", {}).get("Minutes")
                try:
                    minutes = float(raw)
                except (TypeError, ValueError) as error:
                    raise ValueError("Invalid projected minutes") from error
                if not name or not math.isfinite(minutes) or not 0 <= minutes <= 48:
                    raise ValueError("Invalid projected minutes or player name")
                key = (day, code, name)
                if key in result:
                    raise ValueError("Ambiguous duplicate pregame minutes identity")
                result[key] = minutes
    return result


def parse_lineups(payload, day):
    """Only an explicit confirmed status plus exactly five distinct names counts."""
    if payload.get("Date") != day or not isinstance(payload.get("Games"), list):
        raise ValueError("Wrong-date lineups report")
    confirmed, status = {}, {}
    for game in payload["Games"]:
        if not isinstance(game, dict) or _day(game["DateTime"]) != day:
            raise ValueError("Invalid pregame lineup game timestamp")
        for team in game.get("Teams", []):
            code = _team(team.get("Code"))
            key = (day, code)
            if not code or key in status:
                raise ValueError("Duplicate or missing pregame lineup team")
            value = str(team.get("LineupStatus") or team.get("Status") or "").strip().lower()
            is_confirmed = value in {"c", "confirmed", "official"}
            status[key] = "confirmed" if is_confirmed else "unverified"
            if not is_confirmed:
                continue
            people = team.get("Players")
            if not isinstance(people, list):
                raise ValueError("Confirmed lineup missing players")
            names = {_name(p) for p in people}
            if "" in names or len(people) != 5 or len(names) != 5:
                raise ValueError("Malformed confirmed starting five")
            confirmed[key] = names
    return confirmed, status


def load(days, now=None, key=None, getter=fetch):
    """API fetches are optional. Absence is observable, never treated as confirmation."""
    key = key or os.environ.get("ROTOWIRE_API_KEY", "")
    if not key:
        return {"configured": False, "reason": "vendor_api_key_absent"}
    now = now or datetime.now(UTC)
    all_minutes, all_lineups, statuses = {}, {}, {}
    for day in sorted(days):
        minute_report = getter("DailyProjectedMinutes", day, key)
        lineup_report = getter("Lineups", day, key)
        all_minutes.update(parse_minutes(minute_report, day))
        starters, labels = parse_lineups(lineup_report, day)
        all_lineups.update(starters)
        statuses.update(labels)
    return {
        "configured": True,
        "fetched_utc": now.isoformat(),
        "source": "rotowire_licensed",
        "minutes": all_minutes,
        "confirmed_starters": all_lineups,
        "lineup_statuses": statuses,
    }


def enrich(frame, context, now):
    """Attach trusted vendor observations without silently repricing the model.

    The independent minutes forecast is used as a risk gate. Repricing the
    underlying model requires historical calibration; the existing sportsbook
    price remains independently checked and is never misrepresented.
    """
    out = frame.copy()
    out["projected_minutes"] = float("nan")
    out["projected_minutes_source"] = "unverified"
    out["lineup_confirmation_status"] = "unverified"
    out["confirmed_starter"] = None
    if not context.get("configured"):
        return out
    stamp = pd.Timestamp(context["fetched_utc"])
    now_ts = pd.Timestamp(now)
    if (
        stamp.tzinfo is None
        or (now_ts - stamp).total_seconds() < -60
        or (now_ts - stamp).total_seconds() > MAX_SOURCE_AGE_MINUTES * 60
    ):
        raise ValueError("Stale licensed pregame context")
    keys = [
        (
            _date(tip),
            _team(team),
            normalize_name(str(player)),
        )
        for tip, team, player in zip(out.tip_utc, out.team_espn, out.player)
    ]
    minutes = context.get("minutes", {})
    starters = context.get("confirmed_starters", {})
    lineup_statuses = context.get("lineup_statuses", {})
    out["projected_minutes"] = [minutes.get(k, float("nan")) for k in keys]
    out["projected_minutes_source"] = [
        "rotowire_licensed" if k in minutes else "unverified" for k in keys
    ]
    out["lineup_confirmation_status"] = [
        lineup_statuses.get((k[0], k[1]), "unverified") for k in keys
    ]
    out["confirmed_starter"] = [
        k[2] in starters[(k[0], k[1])]
        if (k[0], k[1]) in starters
        else None
        for k in keys
    ]
    return out


def historical_minutes_projection(frame):
    """Prior-only, explicitly model-derived minutes point estimate + uncertainty.

    It is NOT a coach-confirmed rotation, and MUST NOT replace a licensed
    independent as-of forecast in the late-news trading policy.
    """
    baseline = pd.to_numeric(frame.historical_minutes_baseline, errors="coerce")
    last = pd.to_numeric(frame.last_game_minutes, errors="coerce")
    starts = pd.to_numeric(frame.recent_start_rate, errors="coerce")
    estimate = (0.80 * baseline + 0.20 * last).clip(0, 44)
    # Wide enough to communicate rotation instability, not a calibrated CI.
    uncertainty = 6.0 + 0.5 * (last - baseline).abs()
    unstable = starts.isna() | (starts.between(0.2, 0.8))
    uncertainty = uncertainty + unstable.astype(float) * 2
    result = frame.copy()
    result["minutes_forecast_internal"] = estimate
    result["minutes_uncertainty_heuristic"] = uncertainty
    result["minutes_forecast_internal_source"] = "prior_only_uncalibrated"
    return result
