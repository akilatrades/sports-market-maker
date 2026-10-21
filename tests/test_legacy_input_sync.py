"""The legacy minute timer must refresh only data, not executable source."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from live import legacy_input_sync as loader


def test_legacy_refresh_pins_books_to_one_verified_commit(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    stamp = tmp_path / "private_cache" / "last"
    now = datetime(2026, 10, 20, 20, tzinfo=UTC)
    calls = []

    def signed_projection_sync(directory, stamp_time):
        calls.append(("projection", stamp_time))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "nba_books.csv").write_bytes(b"nba-book")
        return {"source_commit": "a" * 40}

    def fixed_commit_data(url):
        calls.append(("book", url))
        return b"nfl-book"

    monkeypatch.setattr(loader, "sync", signed_projection_sync)
    monkeypatch.setattr(loader, "download", fixed_commit_data)
    assert loader.refresh(now, root, stamp)
    assert (root / "outputs/books/nba_latest.csv").read_bytes() == b"nba-book"
    assert (root / "outputs/books/nfl_latest.csv").read_bytes() == b"nfl-book"
    assert len(calls) == 2
    assert (
        "/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/outputs/books/nfl_latest.csv"
        in (calls[1][1])
    )

    assert not loader.refresh(now + timedelta(minutes=5), root, stamp)
    assert len(calls) == 2
    assert loader.refresh(now + timedelta(minutes=11), root, stamp)
    assert len(calls) == 4


def test_legacy_refresh_clears_missing_books_instead_of_reusing_them(
    tmp_path, monkeypatch
):
    root = tmp_path / "checkout"
    stamp = tmp_path / "cache" / "last"
    book_dir = root / "outputs/books"
    book_dir.mkdir(parents=True)
    for sport in ("nfl", "nba"):
        (book_dir / f"{sport}_latest.csv").write_bytes(b"old")

    def sync_without_nba_book(directory, now):
        directory.mkdir(parents=True)
        (directory / "nba_books.csv").write_bytes(b"")
        return {"source_commit": "b" * 40}

    monkeypatch.setattr(loader, "sync", sync_without_nba_book)
    monkeypatch.setattr(
        loader, "download", lambda url: (_ for _ in ()).throw(OSError("missing"))
    )
    assert loader.refresh(datetime.now(UTC), root, stamp)
    assert not (book_dir / "nba_latest.csv").exists()
    assert not (book_dir / "nfl_latest.csv").exists()


def test_failed_projection_sync_does_not_mark_refresh_as_success(tmp_path, monkeypatch):
    import pytest

    stamp = tmp_path / "cache" / "last"

    def fail_sync(directory, now):
        raise ValueError("unverified projection checksum")

    monkeypatch.setattr(loader, "sync", fail_sync)
    with pytest.raises(ValueError, match="checksum"):
        loader.refresh(datetime.now(UTC), tmp_path, stamp)
    assert not stamp.exists()


def test_fresh_install_runner_does_not_git_pull_before_each_trade():
    source = Path("deploy/install.sh").read_text()
    runner = source.split("cat > /home/trader/run.sh <<'RUN'", 1)[1].split(
        "\nRUN\n", 1
    )[0]
    assert not any(
        line.lstrip().startswith("git pull ") for line in runner.splitlines()
    )
    assert ".venv/bin/python -m live.legacy_input_sync" in runner
