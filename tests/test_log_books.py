"""Near-term odds refreshes: what is fetched and how the latest file updates."""

import re
from pathlib import Path

import pandas as pd
import pytest

import kalshi.books as books
from kalshi.books import LINE_COLUMNS, parse_event
from live import log_books
from tests.test_books import EVENT

ROOT = Path(__file__).resolve().parents[1]


def _event(event_id, hours_from_now):
    start = pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=hours_from_now)
    return {**EVENT, "id": event_id, "commence_time": start.isoformat()}


def test_near_scope_fetches_only_games_about_to_start(monkeypatch):
    listed = [_event("started", -0.5), _event("soon", 3), _event("later", 10)]
    fetched = []
    monkeypatch.setattr(
        books, "events", lambda key, sport: (listed, {"remaining": "9"})
    )

    def event_odds(key, event_id, sport, markets):
        fetched.append(event_id)
        return {**EVENT, "id": event_id}, {"remaining": "8"}

    monkeypatch.setattr(books, "event_odds", event_odds)
    books.props("k", hours_ahead=6.5, started_hours=0)
    assert fetched == ["soon"]
    fetched.clear()
    books.props("k")  # full scope: 36 h ahead and games started under 1 h ago
    assert fetched == ["started", "soon", "later"]


def test_merge_replaces_refreshed_games_and_keeps_the_rest():
    previous = pd.DataFrame(
        {"event_id": ["a", "a", "b"], "line": [1, 2, 3], "snapshot_utc": ["old"] * 3}
    )
    fresh = pd.DataFrame({"event_id": ["a"], "line": [9], "snapshot_utc": ["new"]})
    merged = log_books.merge_latest(previous, fresh)
    assert sorted(merged.line.tolist()) == [3, 9]
    assert log_books.merge_latest(previous, fresh.iloc[0:0]).equals(previous)


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(log_books, "OUT", tmp_path)
    monkeypatch.setattr(log_books, "api_key", lambda: "k")
    return tmp_path


def test_near_refresh_with_no_game_close_spends_nothing_and_writes_nothing(
    out_dir, monkeypatch
):
    latest = out_dir / "nba_latest.csv"
    latest.write_text("event_id,line\nold,1\n")
    empty = pd.DataFrame(columns=LINE_COLUMNS)
    monkeypatch.setattr(log_books, "props", lambda *a, **k: (empty, {"remaining": "5"}))
    log_books.main("nba", "near")
    assert latest.read_text() == "event_id,line\nold,1\n"
    assert not list(out_dir.glob("nba_2*.csv.gz"))


def test_near_refresh_updates_only_its_games_in_the_latest_file(out_dir, monkeypatch):
    fresh_lines = parse_event(EVENT, snapshot_utc="2026-01-09T19:00:00Z")
    monkeypatch.setattr(
        log_books, "props", lambda *a, **k: (fresh_lines, {"remaining": "5"})
    )
    latest = out_dir / "nba_latest.csv"
    pd.DataFrame(
        {"event_id": ["ev1", "other"], "player_key": ["stale", "keep"], "line": [1, 2]}
    ).to_csv(latest, index=False)
    log_books.main("nba", "near")
    after = pd.read_csv(latest)
    assert "stale" not in set(after.player_key)
    assert "keep" in set(after.player_key)
    assert (after.event_id == "ev1").sum() >= 1


def test_workflow_marks_the_same_slots_full_that_it_schedules():
    text = (ROOT / ".github/workflows/books.yml").read_text(encoding="utf-8")
    full = re.search(r'- cron: "(15 [^"]+)"', text).group(1)
    assert f'"$SCHEDULE" == "{full}"' in text
    assert '"5,25,45 10-23 * * *"' in text and '"5,25,45 0-3 * * *"' in text
    assert "python -m live.log_books nba --near" in text


def test_per_book_prices_are_saved_only_when_asked(out_dir, monkeypatch, tmp_path):
    lines = parse_event(EVENT, snapshot_utc="2026-01-09T19:00:00Z")
    monkeypatch.setattr(log_books, "props", lambda *a, **k: (lines, {"remaining": "5"}))
    monkeypatch.delenv(log_books.PER_BOOK_ENV, raising=False)
    log_books.main("nba", "full")
    assert not list(tmp_path.glob("per_book/*"))  # off by default
    monkeypatch.setenv(log_books.PER_BOOK_ENV, str(tmp_path / "per_book"))
    log_books.main("nba", "full")
    files = list((tmp_path / "per_book").glob("nba_*.csv.gz"))
    assert len(files) == 1
    rows = pd.read_csv(files[0])
    assert list(rows.columns) == log_books.PER_BOOK_COLUMNS
    assert rows.p_over.between(0, 1).all() and rows.book.nunique() >= 1
    # The averaged file is the same either way.
    averaged = pd.read_csv(out_dir / "nba_latest.csv")
    one_book = rows.groupby(["player_key", "stat", "line"]).p_over.mean()
    joined = averaged.set_index(["player_key", "stat", "line"]).p_book
    common = one_book.index.intersection(joined.index)
    assert len(common) and (abs(one_book[common] - joined[common]) < 1e-3).all()
    # The committed files carry no per-book column (licensed raw odds).
    for committed in out_dir.glob("nba_*.csv*"):
        assert "book" not in pd.read_csv(committed).columns


def test_a_per_book_failure_never_stops_the_feed(out_dir, monkeypatch, tmp_path):
    lines = parse_event(EVENT, snapshot_utc="2026-01-09T19:00:00Z")
    monkeypatch.setattr(log_books, "props", lambda *a, **k: (lines, {"remaining": "5"}))
    blocked = tmp_path / "file"
    blocked.write_text("not a folder")
    monkeypatch.setenv(log_books.PER_BOOK_ENV, str(blocked))
    log_books.main("nba", "full")  # does not raise
    assert (out_dir / "nba_latest.csv").exists()


def test_the_workflow_caches_per_book_prices_and_never_commits_them():
    flow = (ROOT / ".github/workflows/books.yml").read_text()
    assert "BOOKS_PER_BOOK_DIR: state/books_per_book" in flow
    assert "path: state/books_per_book" in flow
    assert "git add -A outputs/books" in flow and "git add -A state" not in flow
    assert "upload-artifact" not in flow  # artifacts are public on this repository
    assert "/state/" in (ROOT / ".gitignore").read_text().splitlines()
