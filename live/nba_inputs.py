"""Versioned NBA inputs: publish a checksummed pair; sync data without updating code.

Only public GET requests are used. Inputs come from two places, and each pass
takes the newer valid copy of each (2026-11-03, deploy/NBA_SERVER_FEED.md):

- this server's own feed (``live.nba_feed``, under NBA_FEED_DIR), which
  refreshes the sportsbook lines every 20 minutes and, if installed, the
  projections a few times a day, without GitHub's scheduler;
- the copy committed to GitHub by its scheduled workflows (the fallback;
  GitHub skipped most of those runs in early November).
"""

import argparse
import csv
import hashlib
import json
import os
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = 2
MODEL_VERSION = "nba-opening-v2"
REPOSITORY = "akilatrades/sports-market-maker"
MAX_BYTES = 20_000_000
# The server feed's folder (live/nba_feed.py); absent means GitHub only.
LOCAL_FEED = Path(os.environ.get("NBA_FEED_DIR", "/home/trader/nba-feed"))


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".nba-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def publish(frame, directory, now, **evidence):
    """A crash between renames produces a rejected hash, never mixed inputs."""
    numeric = frame.select_dtypes(include="number").columns
    clean = frame.copy()
    clean[numeric] = clean[numeric].round(6)
    data = clean.to_csv(index=False).encode()
    meta = {
        **evidence,
        "schema_version": SCHEMA,
        "model_version": MODEL_VERSION,
        "generated_utc": now.isoformat(),
        "rows": len(frame),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    directory = Path(directory)
    atomic_write(directory / "latest.csv", data)
    atomic_write(
        directory / "latest_meta.json", (json.dumps(meta, indent=2) + "\n").encode()
    )
    return meta


def validate(data, meta, now):
    if (
        meta.get("schema_version") != SCHEMA
        or meta.get("model_version") != MODEL_VERSION
    ):
        raise ValueError("projection_schema_or_model_version")
    if hashlib.sha256(data).hexdigest() != meta.get("sha256"):
        raise ValueError("projection_checksum")
    stamp = datetime.fromisoformat(meta["generated_utc"].replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("projection_timezone")
    age = (now - stamp).total_seconds() / 3600
    if not 0 <= age <= 9:
        raise ValueError("projection_age_outside_0_9_hours")
    return age


def read(directory, now):
    directory = Path(directory)
    data = (directory / "latest.csv").read_bytes()
    meta = json.loads((directory / "latest_meta.json").read_text())
    validate(data, meta, now)
    return data, meta


def download(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "sports-market-maker-nba-inputs"}
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("NBA input exceeds size bound")
    return data


def from_github(now):
    """(data, meta, book) pinned to one public commit; book is b"" if missing."""
    commit = json.loads(
        download(f"https://api.github.com/repos/{REPOSITORY}/commits/main")
    )
    sha = commit["sha"]
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Invalid source commit")
    root = f"https://raw.githubusercontent.com/{REPOSITORY}/{sha}"
    meta = json.loads(download(f"{root}/outputs/projections/latest_meta.json"))
    data = download(f"{root}/outputs/projections/latest.csv")
    validate(data, meta, now)
    try:
        book = download(f"{root}/outputs/books/nba_latest.csv")
    except Exception:
        book = b""
    return data, {**meta, "source_commit": sha}, book


def from_feed(feed, now):
    """(projection pair or None, book bytes or None) from this server's feed.

    An invalid, stale or missing projection pair is ignored, never repaired.
    """
    feed = Path(feed)
    try:
        data, meta = read(feed / "published", now)
        pair = (data, {**meta, "source_commit": "server_feed"})
    except (OSError, ValueError, KeyError, TypeError):
        pair = None
    try:
        book = (feed / "outputs" / "books" / "nba_latest.csv").read_bytes()
    except OSError:
        book = None
    if book is not None and len(book) > MAX_BYTES:
        book = None
    return pair, book


def newest_line(book):
    """Newest update time among a book file's lines (None if unreadable)."""
    if not book:
        return None
    try:
        rows = csv.DictReader(book.decode().splitlines())
        stamps = []
        for row in rows:
            for key in ("updated_utc", "snapshot_utc"):
                value = (row.get(key) or "").strip()
                if value:
                    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if stamp.tzinfo is not None:
                        stamps.append(stamp)
        return max(stamps) if stamps else None
    except (UnicodeDecodeError, ValueError, csv.Error):
        return None


def _better_pair(a, b):
    """The pair to use: a non-empty one first, then the newer generation."""
    candidates = [p for p in (a, b) if p is not None]
    if not candidates:
        return None

    def generated(pair):
        return datetime.fromisoformat(pair[1]["generated_utc"].replace("Z", "+00:00"))

    return max(candidates, key=lambda p: (p[1].get("rows", 0) > 0, generated(p)))


def sync(directory, now=None, feed=None):
    """Write the newer valid projection pair and the newer book file.

    GitHub reads are pinned to one public commit; this server's feed is read
    from disk. Never git-pull executable code. Raises only when neither
    source has a valid projection pair (the caller then checks its cache).
    """
    now = now or datetime.now(UTC)
    feed = LOCAL_FEED if feed is None else feed
    remote, remote_book, error = None, None, None
    try:
        data, meta, remote_book = from_github(now)
        remote = (data, meta)
    except Exception as exc:  # network, validation or format: try the feed
        error = exc
    local, local_book = from_feed(feed, now)
    chosen = _better_pair(remote, local)
    if chosen is None:
        raise error or ValueError("no_valid_projection_source")
    data, meta = chosen
    books = [b for b in (remote_book, local_book) if b]
    # Missing book data must remove a previously cached file, not preserve it.
    book = max(
        books,
        key=lambda b: newest_line(b) or datetime.min.replace(tzinfo=UTC),
        default=b"",
    )
    directory = Path(directory)
    atomic_write(directory / "nba_books.csv", book)
    atomic_write(directory / "latest.csv", data)
    atomic_write(
        directory / "latest_meta.json", (json.dumps(meta, indent=2) + "\n").encode()
    )
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync", type=Path, required=True)
    args = parser.parse_args()
    meta = sync(args.sync)
    print(
        json.dumps(
            {k: meta[k] for k in ("generated_utc", "rows", "source_commit")},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
