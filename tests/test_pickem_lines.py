"""The pick'em app lines for the player-pool page: what is read, kept and
spent. No network."""

import ast
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import kalshi.books
from research import pickem_lines as P

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 21, 20, 0, tzinfo=UTC)
WORKFLOW = (ROOT / ".github/workflows/pickem-lines.yml").read_text("utf-8")
OWNER_ONLY = (
    "github.actor == 'akilatrades'",
    "github.triggering_actor == 'akilatrades'",
)


def both(player, point, price=-119):
    return [
        {"name": side, "description": player, "price": price, "point": point}
        for side in ("Over", "Under")
    ]


def market(key, outcomes, seen="2026-11-21T19:55:00Z"):
    return {"key": key, "last_update": seen, "outcomes": outcomes}


def reply(event_id="ev1", tip="2026-11-22T00:30:00Z"):
    """An event-odds reply in the feed's shape: the two apps, a third app,
    and a sportsbook that must not be read as an app."""
    one_side = {
        "name": "Over",
        "description": "Deni Avdija",
        "price": -137,
        "point": 22.5,
    }
    return {
        "id": event_id,
        "commence_time": tip,
        "home_team": "New York Knicks",
        "away_team": "Portland Trail Blazers",
        "bookmakers": [
            {
                "key": "prizepicks",
                "markets": [
                    market("player_points", both("Jalen Brunson", 26.5) + [one_side]),
                    market("player_points_alternate", both("Jalen Brunson", 30.5)),
                ],
            },
            {
                "key": "underdog",
                "markets": [
                    market(
                        "player_rebounds",
                        both("Karl-Anthony Towns", 12.5),
                        seen="2026-11-21T19:40:00Z",
                    )
                ],
            },
            {
                "key": "pick6",
                "markets": [market("player_points", both("Jalen Brunson", 27.5))],
            },
            {
                "key": "draftkings",
                "markets": [market("player_points", both("Jalen Brunson", 25.5))],
            },
        ],
    }


def test_only_the_two_apps_standard_lines_are_kept_and_never_a_price():
    frame = P.app_lines(reply(), NOW)
    assert list(frame.columns) == P.COLUMNS
    assert not {"odds", "price", "book"} & set(frame.columns)
    rows = {
        (r.app, r.player_key, r.stat): (r.line, r.sides)
        for r in frame.itertuples(index=False)
    }
    assert rows == {
        ("PrizePicks", "jalen brunson", "points"): (26.5, "both"),
        # An app can post one side only; the page must not offer the other.
        ("PrizePicks", "deni avdija", "points"): (22.5, "over"),
        # The same spelling the sportsbook lines are keyed on.
        ("Underdog", "karl anthony towns", "rebounds"): (12.5, "both"),
    }
    # Teams as Kalshi spells them, so the page can match the game.
    assert set(frame.home) == {"NYK"} and set(frame.away) == {"POR"}
    assert set(frame.snapshot_utc) == {"2026-11-21T20:00+00:00"}
    towns = frame[frame.stat == "rebounds"].iloc[0]
    assert towns.updated_utc == "2026-11-21T19:40:00+00:00"
    # The feed's indicative prices are not in the file at all.
    text = frame.to_csv(index=False)
    assert "-119" not in text and "-137" not in text


def test_an_event_with_no_app_lines_gives_no_rows():
    odds = reply()
    odds["bookmakers"] = odds["bookmakers"][2:]
    frame = P.app_lines(odds, NOW)
    assert frame.empty and list(frame.columns) == P.COLUMNS


def test_a_pull_is_due_only_after_the_gap(tmp_path):
    path = tmp_path / "nba_latest.csv"
    assert P.due(NOW, path)  # no file yet
    path.write_text(",".join(P.COLUMNS) + "\n", "utf-8")
    assert P.due(NOW, path)  # a file with no rows
    P.app_lines(reply(), NOW).to_csv(path, index=False)
    assert P.last_pull(path) == NOW
    gap = timedelta(hours=P.MIN_HOURS_BETWEEN)
    assert not P.due(NOW + gap - timedelta(minutes=1), path)
    assert P.due(NOW + gap, path)
    path.write_text("snapshot_utc\nnot a time\n", "utf-8")
    assert P.due(NOW, path)
    # About four pulls a day, and the bot's credits come first.
    assert P.MIN_HOURS_BETWEEN >= 5
    assert P.MIN_CREDITS_LEFT >= 10_000


def listed_events():
    def event(event_id, hours):
        tip = NOW + timedelta(hours=hours)
        return {"id": event_id, "commence_time": tip.strftime("%Y-%m-%dT%H:%M:%SZ")}

    return [event("started", -1), event("tonight", 4.5), event("tomorrow", 30)]


def test_a_pull_asks_only_for_tonights_games_in_the_pickem_group(monkeypatch):
    calls = []

    def event_odds(key, event_id, sport, markets, regions):
        calls.append((event_id, sport, tuple(markets), regions))
        return reply(event_id), {"remaining": "61234"}

    monkeypatch.setattr(
        kalshi.books,
        "events",
        lambda key, sport: (listed_events(), {"remaining": "61238"}),
    )
    monkeypatch.setattr(kalshi.books, "event_odds", event_odds)
    frame, summary = P.pull(NOW, "k")
    # One paid request: not the game under way, not tomorrow's.
    assert [call[0] for call in calls] == ["tonight"]
    _, sport, markets, regions = calls[0]
    assert sport == "basketball_nba" and regions == "us_dfs"
    # Four main markets, so at most 4 credits a game; no "_alternate" lines.
    assert len(markets) == 4 and not [m for m in markets if "alternate" in m]
    assert len(frame) == 3
    assert summary == {"games": 1, "credits_remaining": "61234"}


def test_low_credits_stop_the_pull_before_any_paid_request(monkeypatch):
    left = str(P.MIN_CREDITS_LEFT - 1)
    monkeypatch.setattr(
        kalshi.books,
        "events",
        lambda key, sport: (listed_events(), {"remaining": left}),
    )
    monkeypatch.setattr(
        kalshi.books, "event_odds", lambda *a, **k: pytest.fail("spent credits")
    )
    frame, summary = P.pull(NOW, "k")
    assert frame.empty and summary["games"] == 0 and "skipped" in summary["note"]


def test_a_slow_feed_cannot_hold_the_job(monkeypatch):
    ticks = iter(range(0, 10_000, P.TIME_BUDGET_SECONDS))
    events = [e | {"id": f"g{i}"} for i, e in enumerate([listed_events()[1]] * 5)]
    monkeypatch.setattr(
        kalshi.books, "events", lambda key, sport: (events, {"remaining": "50000"})
    )
    monkeypatch.setattr(
        kalshi.books, "event_odds", lambda key, event_id, **k: (reply(event_id), {})
    )
    _, summary = P.pull(NOW, "k", clock=lambda: next(ticks))
    assert summary["games"] < 5 and "out of time" in summary["note"]


def test_main_writes_its_own_folder_and_respects_the_gap(tmp_path, monkeypatch):
    pulls = []

    def pull(now, key):
        pulls.append(now)
        return P.app_lines(reply(), now), {"games": 1, "credits_remaining": "60000"}

    monkeypatch.setattr(P, "OUT", tmp_path)
    monkeypatch.setattr(P, "LATEST", tmp_path / "nba_latest.csv")
    monkeypatch.setattr(P, "pull", pull)
    monkeypatch.setattr(kalshi.books, "api_key", lambda: "k")
    books_before = sorted(p.name for p in (ROOT / "outputs/books").glob("nba_latest*"))

    assert P.main([]) == 0
    assert len(pulls) == 1
    latest = pd.read_csv(tmp_path / "nba_latest.csv")
    assert list(latest.columns) == P.COLUMNS and len(latest) == 3
    logs = list(tmp_path.glob("nba_*.csv.gz"))
    assert len(logs) == 1 and len(pd.read_csv(logs[0])) == 3
    # Nothing else was written, here or beside the bot's consensus.
    assert {p.name for p in tmp_path.iterdir()} == {"nba_latest.csv", logs[0].name}
    after = sorted(p.name for p in (ROOT / "outputs/books").glob("nba_latest*"))
    assert after == books_before

    # A second start inside the gap spends nothing; the owner's button does.
    assert P.main([]) == 0 and len(pulls) == 1
    assert P.main(["--force"]) == 0 and len(pulls) == 2
    assert len(pd.read_csv(logs[0])) == 6


def test_main_keeps_the_last_file_when_nothing_comes_back(
    tmp_path, monkeypatch, capsys
):
    latest = tmp_path / "nba_latest.csv"
    monkeypatch.setattr(P, "OUT", tmp_path)
    monkeypatch.setattr(P, "LATEST", latest)
    monkeypatch.setattr(kalshi.books, "api_key", lambda: "k")
    old = P.app_lines(reply(), NOW - timedelta(days=1))
    old.to_csv(latest, index=False)

    empty = pd.DataFrame(columns=P.COLUMNS)
    monkeypatch.setattr(P, "pull", lambda now, key: (empty, {"games": 2}))
    assert P.main([]) == 0
    assert len(pd.read_csv(latest)) == 3 and "no app lines" in capsys.readouterr().out

    def broken(now, key):
        raise kalshi.books.BooksError("odds api /x: HTTP 422 unknown region")

    monkeypatch.setattr(P, "pull", broken)
    assert P.main([]) == 1
    assert len(pd.read_csv(latest)) == 3 and "::error::" in capsys.readouterr().out


def test_the_due_check_runs_before_anything_is_installed(capsys, monkeypatch):
    """The workflow asks "--due" first, so the top of the file is standard
    library only."""
    tree = ast.parse((ROOT / "research/pickem_lines.py").read_text("utf-8"))
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            top.add(node.module.split(".")[0])
    assert top and top <= set(sys.stdlib_module_names)
    monkeypatch.setattr(P, "LATEST", ROOT / "no such file.csv")
    assert P.main(["--due"]) == 0 and capsys.readouterr().out == "due\n"


def test_the_bots_consensus_is_out_of_reach():
    source = (ROOT / "research/pickem_lines.py").read_text("utf-8")
    assert P.OUT == Path("outputs/pickem") and P.LATEST.parent == P.OUT
    # It reads the feed's replies; it never builds or merges a consensus.
    for word in ("consensus(", "merge_latest", "attach", "books.LATEST"):
        assert word not in source
    assert set(P.APPS) == {"prizepicks", "underdog"}


def test_the_workflow_cannot_run_on_a_pull_request_or_a_push():
    head = WORKFLOW[: WORKFLOW.index("\njobs:\n")]
    triggers = head[head.index("\non:\n") : head.index("\npermissions:")]
    assert "pull_request" not in WORKFLOW
    assert not re.search(r"^  push:", triggers, re.M)
    books = (ROOT / ".github/workflows/books.yml").read_text("utf-8")
    name = re.search(r"^name: (.+)$", books, re.M).group(1)
    assert f'workflows: ["{name}"]' in triggers
    assert "workflow_dispatch:" in triggers and "schedule:" in triggers


def test_the_workflow_spends_credits_only_on_main_and_by_hand_only_for_the_owner():
    assert "github.ref == 'refs/heads/main'" in WORKFLOW
    for check in OWNER_ONLY:
        assert check in WORKFLOW
    assert re.findall(r"secrets\.(\w+)", WORKFLOW) == ["ODDS_API_KEY"]
    # Installing, the paid step and the commit all wait for the due check.
    assert WORKFLOW.count("if: steps.due.outputs.state == 'due'") == 3
    assert WORKFLOW.index("research.pickem_lines --due") < WORKFLOW.index("pip install")


def test_the_workflow_writes_only_the_pickem_folder():
    assert re.search(r"^permissions:\n  contents: read\n", WORKFLOW, re.M)
    assert re.findall(r"git add (.+)", WORKFLOW) == ["-A outputs/pickem"]
    code = "\n".join(
        line for line in WORKFLOW.splitlines() if not line.lstrip().startswith("#")
    )
    assert "outputs/books" not in code and "log_books" not in code
    # The sportsbook job is left exactly as it was.
    books = (ROOT / ".github/workflows/books.yml").read_text("utf-8")
    assert "pickem" not in books
    page = (ROOT / ".github/workflows/player-pool-page.yml").read_text("utf-8")
    assert "tests/test_pickem_lines.py" in page and "secrets." not in page
