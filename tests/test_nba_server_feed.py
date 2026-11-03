"""The NBA bot's own server feed (deploy/NBA_SERVER_FEED.md). Offline."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from live import nba_feed, nba_inputs

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
SHA = "a" * 40


def book(stamp, line=20.5):
    return pd.DataFrame(
        {
            "player_key": ["test player"],
            "stat": ["points"],
            "line": [line],
            "p_book": [0.5],
            "book_n": [2],
            "updated_utc": [stamp.isoformat()],
            "snapshot_utc": [stamp.isoformat(timespec="minutes")],
        }
    ).to_csv(index=False)


def github(monkeypatch, tmp_path, made, rows=1, books=None, fail=False):
    """A fake GitHub holding one projection pair (made at ``made``)."""
    source = tmp_path / "github"
    nba_inputs.publish(
        pd.DataFrame({"ticker": [f"G{i}" for i in range(rows)]}), source, made
    )
    if books is not None:
        (source / "nba_latest.csv").write_text(books)

    def get(url):
        if fail:
            raise OSError("GitHub unreachable")
        if "/commits/main" in url:
            return json.dumps({"sha": SHA}).encode()
        name = url.rsplit("/", 1)[-1]
        if not (source / name).exists():
            raise OSError("missing")
        return (source / name).read_bytes()

    monkeypatch.setattr(nba_inputs, "download", get)


def server(tmp_path, made=None, rows=1, books=None):
    feed = tmp_path / "feed"
    if made is not None:
        nba_inputs.publish(
            pd.DataFrame({"ticker": [f"S{i}" for i in range(rows)]}),
            feed / "published",
            made,
        )
    if books is not None:
        (feed / "outputs/books").mkdir(parents=True, exist_ok=True)
        (feed / "outputs/books/nba_latest.csv").write_text(books)
    return feed


def synced(tmp_path, feed):
    dest = tmp_path / "inputs"
    meta = nba_inputs.sync(dest, NOW, feed=feed)
    data, _ = nba_inputs.read(dest, NOW)
    return meta, data.decode(), (dest / "nba_books.csv").read_text()


# --- the bot's choice between the server feed and GitHub -------------------


def test_newer_server_projections_and_books_win(tmp_path, monkeypatch):
    github(
        monkeypatch,
        tmp_path,
        NOW - timedelta(hours=8),
        books=book(NOW - timedelta(hours=3)),
    )
    feed = server(
        tmp_path,
        NOW - timedelta(hours=1),
        books=book(NOW - timedelta(minutes=10), 21.5),
    )
    meta, data, books = synced(tmp_path, feed)
    assert meta["source_commit"] == "server_feed" and "S0" in data
    assert "21.5" in books


def test_newer_github_copy_wins_each_file_separately(tmp_path, monkeypatch):
    github(
        monkeypatch,
        tmp_path,
        NOW - timedelta(hours=1),
        books=book(NOW - timedelta(minutes=5), 22.5),
    )
    feed = server(
        tmp_path, NOW - timedelta(hours=4), books=book(NOW - timedelta(minutes=50))
    )
    meta, data, books = synced(tmp_path, feed)
    assert meta["source_commit"] == SHA and "G0" in data
    assert "22.5" in books


def test_server_feed_carries_the_bot_when_github_is_down(tmp_path, monkeypatch):
    github(monkeypatch, tmp_path, NOW, fail=True)
    feed = server(
        tmp_path, NOW - timedelta(hours=2), books=book(NOW - timedelta(minutes=10))
    )
    meta, data, books = synced(tmp_path, feed)
    assert meta["source_commit"] == "server_feed" and "S0" in data and books


def test_stale_github_does_not_block_a_fresh_server_feed(tmp_path, monkeypatch):
    # GitHub's last pair is older than the 9-hour limit (it skipped runs).
    github(monkeypatch, tmp_path, NOW - timedelta(hours=20))
    feed = server(tmp_path, NOW - timedelta(minutes=30))
    meta, _, _ = synced(tmp_path, feed)
    assert meta["source_commit"] == "server_feed"


def test_a_broken_server_pair_is_ignored_never_repaired(tmp_path, monkeypatch):
    github(monkeypatch, tmp_path, NOW - timedelta(hours=3))
    feed = server(tmp_path, NOW - timedelta(minutes=30))
    (feed / "published/latest.csv").write_text("ticker\nTAMPERED\n")  # checksum fails
    meta, data, _ = synced(tmp_path, feed)
    assert meta["source_commit"] == SHA and "TAMPERED" not in data


def test_a_market_list_beats_a_newer_empty_one(tmp_path, monkeypatch):
    github(monkeypatch, tmp_path, NOW - timedelta(hours=3), rows=2)
    feed = server(tmp_path, NOW - timedelta(minutes=30), rows=0)
    meta, _, _ = synced(tmp_path, feed)
    assert meta["source_commit"] == SHA and meta["rows"] == 2


def test_neither_source_raises_and_missing_books_clear_the_cache(tmp_path, monkeypatch):
    github(monkeypatch, tmp_path, NOW, fail=True)
    with pytest.raises(OSError):
        nba_inputs.sync(tmp_path / "inputs", NOW, feed=tmp_path / "nothing")
    github(monkeypatch, tmp_path, NOW - timedelta(hours=1))  # no books anywhere
    dest = tmp_path / "inputs"
    (dest).mkdir(exist_ok=True)
    (dest / "nba_books.csv").write_text(book(NOW - timedelta(hours=5)))
    nba_inputs.sync(dest, NOW, feed=tmp_path / "nothing")
    assert (dest / "nba_books.csv").read_bytes() == b""


def test_newest_line_reads_update_times():
    assert nba_inputs.newest_line(book(NOW).encode(), NOW) == NOW
    assert nba_inputs.newest_line(b"") is None
    assert nba_inputs.newest_line(b"\xff\xfe") is None


# --- the feed jobs ---------------------------------------------------------


def test_books_job_runs_near_scope_inside_the_feed_and_prunes(tmp_path, monkeypatch):
    from live import log_books

    calls = []
    monkeypatch.setattr(
        log_books,
        "main",
        lambda sport, scope: calls.append((sport, scope, os.getcwd())),
    )
    feed = tmp_path / "feed"
    (feed / "outputs/books").mkdir(parents=True)
    old = feed / "outputs/books/nba_2026-10-01.csv.gz"
    new = feed / "outputs/books/nba_2026-11-03.csv.gz"
    for path in (old, new):
        path.write_bytes(b"x")
    stamp = datetime.now(UTC).timestamp() - 20 * 86400
    os.utime(old, (stamp, stamp))
    here = os.getcwd()
    try:
        nba_feed.books(feed)
    finally:
        os.chdir(here)
    assert calls == [("nba", "near", str(feed))]
    assert not old.exists() and new.exists()


def fake_projections(monkeypatch, rows=1, bad=False):
    from live import nba_projections

    def run():
        frame = pd.DataFrame(
            {
                "ticker": [f"S{i}" for i in range(rows)],
                "p_model": [0.4] * rows,
                "tip_utc": [(datetime.now(UTC) + timedelta(hours=5)).isoformat()]
                * rows,
                "injury_status": [""] * rows,
                "game_id": [1] * rows,
                "player_id": list(range(rows)),
                "requires_book": [False] * rows,
                "team_espn": ["LAL"] * rows,
            }
        )
        meta = nba_inputs.publish(
            frame,
            Path("outputs/projections"),
            datetime.now(UTC),
            schedule_games=1,
            open_markets=rows,
        )
        if bad:
            Path("outputs/projections/latest.csv").write_text("ticker\nX\nY\n")
        return meta

    monkeypatch.setattr(nba_projections, "main", run)


def test_projections_job_publishes_only_a_checked_pair(tmp_path, monkeypatch):
    fetched = []
    monkeypatch.setattr(nba_feed, "refresh_history", lambda feed: fetched.append(feed))
    fake_projections(monkeypatch)
    feed = tmp_path / "feed"
    here = os.getcwd()
    try:
        nba_feed.projections(feed, memory=lambda: 4000)
    finally:
        os.chdir(here)
    assert fetched == [feed]  # no history yet: downloaded first
    data, meta = nba_inputs.read(feed / "published", datetime.now(UTC))
    assert meta["rows"] == 1 and b"S0" in data


def test_a_failed_check_leaves_the_last_published_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(nba_feed, "refresh_history", lambda feed: None)
    feed = tmp_path / "feed"
    nba_inputs.publish(
        pd.DataFrame({"ticker": ["OLD"]}), feed / "published", datetime.now(UTC)
    )
    fake_projections(monkeypatch, bad=True)
    here = os.getcwd()
    try:
        with pytest.raises(ValueError, match="checksum"):
            nba_feed.projections(feed, memory=lambda: 4000)
    finally:
        os.chdir(here)
    assert b"OLD" in (feed / "published/latest.csv").read_bytes()


def test_history_is_downloaded_every_run_unless_just_fetched(tmp_path):
    feed = tmp_path
    (feed / "data").mkdir()
    assert nba_feed.history_age_hours(feed, NOW) is None
    stamp = (NOW - timedelta(hours=5)).isoformat(timespec="seconds")
    (feed / "data/retrieval.json").write_text(json.dumps({"retrieved": stamp}))
    assert nba_feed.history_age_hours(feed, NOW) == pytest.approx(5)
    assert nba_feed.HISTORY_MAX_AGE_HOURS == 2


def test_cli_accepts_only_the_two_jobs():
    with pytest.raises(SystemExit):
        nba_feed.main(["orders"])


# --- the server units --------------------------------------------------------


@pytest.mark.parametrize("job", ["books", "projections"])
def test_units_are_capped_and_cannot_write_the_trading_checkout(job):
    unit = (ROOT / f"deploy/market-maker-nba-feed-{job}.service").read_text()
    timer = (ROOT / f"deploy/market-maker-nba-feed-{job}.timer").read_text()
    assert f"-m live.nba_feed {job}" in unit
    assert "User=trader" in unit and "ProtectHome=read-only" in unit
    assert "ReadWritePaths=/home/trader/nba-feed" in unit
    assert "MemoryMax=" in unit and "MemorySwapMax=0" in unit
    assert "prod-nba-auto.env" not in unit  # never the Kalshi credentials
    assert f"Unit=market-maker-nba-feed-{job}.service" in timer
    if job == "books":
        assert "EnvironmentFile=/etc/market-maker-odds.env" in unit
        assert "OnCalendar=*-*-* *:05,25,45:00 UTC" in timer
    else:
        assert "EnvironmentFile" not in unit
        assert "OnCalendar=*-*-* 10,12,15,18,21:20:00 UTC" in timer
    assert (
        "ExecCondition=+/usr/bin/flock -n /run/lock/smm-production-release.lock" in unit
    )
    assert "InaccessiblePaths=-/home/trader/prod-nba-auto" in unit


def test_setup_never_prints_the_key_file():
    script = (ROOT / "deploy/setup_nba_feed.sh").read_text()
    assert "cat $ENV" not in script and 'cat "$ENV"' not in script
    assert "grep -Eq '^ODDS_API_KEY=" in script  # checked, never shown
    assert "MIN_AVAILABLE_KB=" in script


# --- the NBA readiness check on a day with no NBA props listed ---------------


class _Client:
    env, can_sign = "prod", True

    def balance(self):
        return {"balance": 50.0}


def _ready(monkeypatch, tmp_path, frame):
    from live import prod_nba_auto as nba

    monkeypatch.delenv("SMM_DUAL_MARKET", raising=False)
    monkeypatch.setattr(nba, "assert_nfl_production_stopped", lambda: None)
    monkeypatch.setattr(
        nba,
        "current_production_state",
        lambda *a: {"resting": [], "held": [], "settlements": [], "active": []},
    )
    return nba.preflight(_Client(), frame, NOW, tmp_path / "journal.jsonl")


def _blocked(**diagnostics):
    frame = pd.DataFrame()
    frame.attrs["diagnostics"] = diagnostics
    return frame


def test_no_props_listed_is_idle_not_a_failure(tmp_path, monkeypatch):
    report = _ready(
        monkeypatch, tmp_path, _blocked(blocked="no_priced_markets", open_markets=0)
    )
    assert report["ready"] and report["failures"] == []
    assert report["idle_reason"] == "no_nba_markets_listed"


@pytest.mark.parametrize(
    "diagnostics",
    [
        {"blocked": "projection_age_outside_0_9_hours"},  # stale inputs still fail
        {"blocked": "no_priced_markets", "open_markets": 12},  # props but no rows
        {"blocked": "no_priced_markets"},  # an older pair without the count
    ],
)
def test_other_empty_inputs_still_fail_the_readiness_check(
    tmp_path, monkeypatch, diagnostics
):
    report = _ready(monkeypatch, tmp_path, _blocked(**diagnostics))
    assert not report["ready"]
    assert report["failures"] == ["no_verified_projection_rows"]  # no AttributeError
    assert report["idle_reason"] is None


def test_an_empty_published_pair_reports_how_many_props_were_open(tmp_path):
    from live import prod_nba_auto as nba

    nba_inputs.publish(
        pd.DataFrame(columns=["ticker"]),
        tmp_path,
        NOW,
        schedule_games=10,
        open_markets=0,
    )
    frame = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert frame.empty
    assert frame.attrs["diagnostics"]["blocked"] == "no_priced_markets"
    assert frame.attrs["diagnostics"]["open_markets"] == 0


# --- review fixes (3 November) -----------------------------------------------


def test_default_install_takes_github_inputs_and_server_lines(tmp_path, monkeypatch):
    # Only the sportsbook job is installed: no published pair on the server.
    github(
        monkeypatch,
        tmp_path,
        NOW - timedelta(hours=2),
        books=book(NOW - timedelta(hours=3)),
    )
    feed = server(tmp_path, books=book(NOW - timedelta(minutes=10), 23.5))
    meta, data, books = synced(tmp_path, feed)
    assert meta["source_commit"] == SHA and "G0" in data
    assert "23.5" in books


def test_github_down_keeps_held_inputs_and_fresh_server_lines(tmp_path, monkeypatch):
    dest = tmp_path / "inputs"
    nba_inputs.publish(
        pd.DataFrame({"ticker": ["HELD"]}), dest, NOW - timedelta(hours=1)
    )
    (dest / "nba_books.csv").write_text(book(NOW - timedelta(minutes=90)))
    github(monkeypatch, tmp_path, NOW, fail=True)
    feed = server(tmp_path, books=book(NOW - timedelta(minutes=5), 24.5))
    nba_inputs.sync(dest, NOW, feed=feed)
    assert b"HELD" in nba_inputs.read(dest, NOW)[0]
    assert "24.5" in (dest / "nba_books.csv").read_text()


def test_lines_are_refreshed_even_when_no_inputs_are_valid(tmp_path, monkeypatch):
    dest = tmp_path / "inputs"
    nba_inputs.publish(
        pd.DataFrame({"ticker": ["OLD"]}), dest, NOW - timedelta(hours=10)
    )
    github(monkeypatch, tmp_path, NOW, fail=True)
    feed = server(tmp_path, books=book(NOW - timedelta(minutes=5), 25.5))
    with pytest.raises(OSError):
        nba_inputs.sync(dest, NOW, feed=feed)
    assert "25.5" in (dest / "nba_books.csv").read_text()


def test_a_pass_never_rolls_the_inputs_back(tmp_path, monkeypatch):
    dest = tmp_path / "inputs"
    nba_inputs.publish(
        pd.DataFrame({"ticker": ["NEWER"]}), dest, NOW - timedelta(hours=1)
    )
    (dest / "nba_books.csv").write_text(book(NOW - timedelta(minutes=10), 26.5))
    github(monkeypatch, tmp_path, NOW, fail=True)
    feed = server(
        tmp_path, NOW - timedelta(hours=2), books=book(NOW - timedelta(minutes=110))
    )
    nba_inputs.sync(dest, NOW, feed=feed)
    assert b"NEWER" in nba_inputs.read(dest, NOW)[0]
    assert "26.5" in (dest / "nba_books.csv").read_text()


def test_legacy_sync_stays_github_only(tmp_path, monkeypatch):
    github(monkeypatch, tmp_path, NOW, fail=True)
    server(tmp_path, NOW - timedelta(hours=1))
    with pytest.raises(OSError):
        nba_inputs.sync(tmp_path / "inputs", NOW, feed=False, keep_cache=False)


def test_newest_line_skips_bad_rows_and_future_stamps():
    good = book(NOW - timedelta(minutes=10))
    bad_row = good + "x,points,20.5,0.5,2,not-a-time,also-bad\n"
    assert nba_inputs.newest_line(bad_row.encode(), NOW) == NOW - timedelta(minutes=10)
    assert nba_inputs.newest_line(book(NOW + timedelta(days=1)).encode(), NOW) is None


def test_projections_skip_when_memory_is_short(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(nba_feed, "refresh_history", lambda feed: ran.append(feed))
    here = os.getcwd()
    try:
        assert nba_feed.projections(tmp_path / "feed", memory=lambda: 800) is None
    finally:
        os.chdir(here)
    assert ran == []


def test_a_ledger_error_after_publishing_still_publishes(tmp_path, monkeypatch):
    from live import nba_projections

    monkeypatch.setattr(nba_feed, "refresh_history", lambda feed: None)
    fake_projections(monkeypatch)
    good = nba_projections.main

    def publish_then_fail():
        good()
        raise RuntimeError("paper ledger")

    monkeypatch.setattr(nba_projections, "main", publish_then_fail)
    feed = tmp_path / "feed"
    here = os.getcwd()
    try:
        nba_feed.projections(feed, memory=lambda: 4000)
    finally:
        os.chdir(here)
    assert (feed / "published/latest.csv").exists()


def test_an_old_staged_pair_is_never_published(tmp_path, monkeypatch):
    from live import nba_projections

    monkeypatch.setattr(nba_feed, "refresh_history", lambda feed: None)
    feed = tmp_path / "feed"
    nba_inputs.publish(
        pd.DataFrame({"ticker": ["STALE"]}),
        feed / "outputs/projections",
        datetime.now(UTC) - timedelta(hours=1),
    )

    def fail_before_publishing():
        raise ConnectionError("Kalshi")

    monkeypatch.setattr(nba_projections, "main", fail_before_publishing)
    here = os.getcwd()
    try:
        with pytest.raises(ConnectionError):
            nba_feed.projections(feed, memory=lambda: 4000)
    finally:
        os.chdir(here)
    assert not (feed / "published").exists()


def test_book_files_are_written_whole_and_empty_files_do_not_stop_the_job(tmp_path):
    from live import log_books

    path = tmp_path / "nba_latest.csv"
    path.write_bytes(b"")  # left by a crash mid-write before this change
    assert log_books.read_or_none(path) is None
    frame = pd.DataFrame({"event_id": ["e"], "line": [20.5]})
    log_books.write_atomic(frame, path)
    log_books.write_atomic(frame, tmp_path / "day.csv.gz")
    assert log_books.read_or_none(tmp_path / "day.csv.gz").line.tolist() == [20.5]
    assert log_books.merge_latest(None, frame).equals(frame)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["day.csv.gz", "nba_latest.csv"]


def test_off_sets_the_feed_data_aside_and_the_lock_is_released_before_runs():
    script = (ROOT / "deploy/setup_nba_feed.sh").read_text()
    off = script[script.index("  --off)") : script.index("  --status)")]
    assert 'mv "$FEED/published"' in off and "nba_latest.off-" in off
    assert script.index("exec 9>&-") < script.index('systemctl start "$BOOKS.service"')
