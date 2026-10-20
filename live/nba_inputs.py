"""Versioned NBA inputs: publish a checksummed pair; sync data without updating code.

Only public GET requests are used. Training stays on CI, not the small worker.
"""

import argparse
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


def sync(directory, now=None):
    """Pin all reads to one public commit. Never git-pull executable code."""
    now = now or datetime.now(UTC)
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
    # Missing book data must remove a previously cached file, not preserve it.
    try:
        book = download(f"{root}/outputs/books/nba_latest.csv")
    except Exception:
        book = b""
    directory = Path(directory)
    atomic_write(directory / "nba_books.csv", book)
    meta["source_commit"] = sha
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
