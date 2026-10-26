"""Offline tests for research/exchange_gaps.py (synthetic replies, no network)."""

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from research import exchange_gaps as X

NOW = datetime(2026, 10, 24, 15, 15, tzinfo=UTC)  # an early-run hour


def american(p):
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def book(key, markets):
    return {
        "key": key,
        "markets": [{"key": m, "outcomes": o} for m, o in markets.items()],
    }


def prop(over, under, player="P1", point=20.5):
    return [
        {
            "name": "Over",
            "description": player,
            "point": point,
            "price": american(over),
        },
        {
            "name": "Under",
            "description": player,
            "point": point,
            "price": american(under),
        },
    ]


def reply(event, start, novig_over, sb_over):
    """Two sportsbooks around ``sb_over`` (fair over) and a Novig quote."""
    return {
        "id": event,
        "commence_time": start.isoformat(),
        "home_team": "H",
        "away_team": "A",
        "bookmakers": [
            book(
                "draftkings",
                {"player_points": prop(sb_over + 0.025, 1 - sb_over + 0.025)},
            ),
            book(
                "fanduel", {"player_points": prop(sb_over + 0.02, 1 - sb_over + 0.03)}
            ),
            book("novig", {"player_points": prop(novig_over, 1 - novig_over + 0.08)}),
        ],
    }


def test_take_edges_flag_a_cheap_exchange_price():
    two = X.two_sided(pd.DataFrame(X.flatten(reply("e1", NOW, 0.45, 0.52))))
    edges = X.take_edges(two, X.consensus(two))
    over = edges[(edges.book == "novig") & (edges.side == "a")].iloc[0]
    assert round(over.fair, 2) == 0.52 and over.edge > 0.06  # paid 45c for ~52%
    assert set(edges.book) == {"novig"}  # sportsbooks are never "taken"


def test_moneylines_without_a_point_are_kept():
    ev = {
        "id": "e2",
        "commence_time": NOW.isoformat(),
        "home_team": "H",
        "away_team": "A",
        "bookmakers": [
            book(
                "draftkings",
                {"h2h": [{"name": "H", "price": -150}, {"name": "A", "price": 130}]},
            ),
            book(
                "fanduel",
                {"h2h": [{"name": "H", "price": -145}, {"name": "A", "price": 125}]},
            ),
            book(
                "kalshi",
                {"h2h": [{"name": "H", "price": -140}, {"name": "A", "price": 135}]},
            ),
        ],
    }
    two = X.two_sided(pd.DataFrame(X.flatten(ev)))
    assert len(two) == 3 and set(two.kind) == {"game lines"}
    assert len(X.consensus(two)) == 1


def test_flags_early_then_scores_them_at_the_close(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "OUT", tmp_path / "out")
    monkeypatch.setattr(X, "STATE", tmp_path / "state")
    start = NOW + timedelta(hours=5)
    state = {"close": False, "remaining": 90000}

    def events(key, sport):
        evs = (
            [{"id": "e1", "commence_time": start.isoformat()}]
            if sport == "basketball_nba"
            else []
        )
        return evs, {
            "remaining": state["remaining"],
            "used": 100000 - state["remaining"],
        }

    def event_odds(key, event_id, sport, markets, regions):
        # Early: Novig over at 45c, consensus 52%. Close: consensus 55%.
        state["remaining"] -= 14
        r = reply(event_id, start, 0.45, 0.55 if state["close"] else 0.52)
        return r, {"remaining": state["remaining"], "used": 100000 - state["remaining"]}

    monkeypatch.setattr(X.books, "api_key", lambda: "k")
    monkeypatch.setattr(X.books, "events", events)
    monkeypatch.setattr(X.books, "event_odds", event_odds)
    X.main(NOW)  # early run: flags, no score yet
    summary = json.loads((tmp_path / "out" / "clv_summary.json").read_text())
    assert summary["flags_recorded"] >= 1 and summary["flags_scored"] == 0
    state["close"] = True
    X.main(start - timedelta(minutes=40))  # not an early hour; the game is closing
    summary = json.loads((tmp_path / "out" / "clv_summary.json").read_text())
    row = summary["novig 5+ pts"]
    # About 55% at the close against 45c paid (odds rounding moves it a little).
    assert row["flags"] == 1 and row["clv_mean"] == pytest.approx(0.095, abs=0.01)
    # The game is scored once; a later run does not fetch it again.
    before = state["remaining"]
    X.main(start - timedelta(minutes=20))
    assert state["remaining"] == before
    history = (tmp_path / "out" / "history.jsonl").read_text().splitlines()
    assert json.loads(history[0])["monthly_quota"] == 100000  # used + remaining


def test_runs_stop_before_the_shared_key_runs_low(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "OUT", tmp_path / "out")
    monkeypatch.setattr(X, "STATE", tmp_path / "state")
    calls = []
    monkeypatch.setattr(X.books, "api_key", lambda: "k")
    monkeypatch.setattr(
        X.books,
        "events",
        lambda key, sport: (
            [{"id": "e1", "commence_time": (NOW + timedelta(hours=3)).isoformat()}],
            {"remaining": X.MIN_REMAINING - 1, "used": 1},
        ),
    )
    monkeypatch.setattr(X.books, "event_odds", lambda *a, **k: calls.append(a))
    X.main(NOW)
    assert calls == []
