"""Production NFL input sync must be immutable, checksummed and GET-only."""

import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from live import nfl_inputs

NOW = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
LADDER = "outputs/nfl/projections/ladders/2026_week07_2026-10-20T0000Z.csv.gz"


def sources(now=NOW):
    games = b"game_id,gameday\nG,2026-10-22\n"
    injuries = b"season,week,team,full_name\n2026,7,NYG,A\n"
    ladder = gzip.compress(b"made_utc,game_id,p_over\n2026-10-20T00:00Z,G,0.4\n")
    book = b"player_key,stat,line,p_book,book_n,snapshot_utc\n"
    retrieval = {
        "retrieved": now.date().isoformat(),
        "sha256": {
            "games.csv": hashlib.sha256(games).hexdigest(),
            "injuries.csv.gz": hashlib.sha256(injuries).hexdigest(),
        },
    }
    data = {
        "data/nfl/retrieval.json": json.dumps(retrieval).encode(),
        "data/nfl/games.csv": games,
        "data/nfl/injuries.csv.gz": injuries,
        LADDER: ladder,
        nfl_inputs.BOOK: book,
    }
    tree = {
        "tree": [
            {"path": p, "type": "blob", "sha": hashlib.sha1(blob).hexdigest()}
            for p, blob in data.items()
        ]
    }
    return data, tree


def test_source_selection_requires_recent_ladder():
    _, tree = sources()
    paths, _ = nfl_inputs.source_paths(tree, NOW)
    assert LADDER in paths
    with pytest.raises(ValueError, match="No recent"):
        nfl_inputs.source_paths(tree, NOW + timedelta(hours=50))


def test_synchronizes_pinned_data_and_avoids_repeat_download(monkeypatch, tmp_path):
    data, tree = sources()
    sha = "a" * 40
    urls = []

    def fetch(url):
        urls.append(url)
        if url.endswith("/commits/main"):
            return json.dumps({"sha": sha}).encode()
        if url.endswith(f"/git/trees/{sha}?recursive=1"):
            return json.dumps(tree).encode()
        path = url.split(f"/{sha}/")[-1]
        assert url.startswith("https://raw.githubusercontent.com/")
        return data[path]

    monkeypatch.setattr(nfl_inputs, "download", fetch)
    status = nfl_inputs.sync(tmp_path, NOW)
    assert status == {"status": "verified", "source_commit": sha}
    assert (tmp_path / "active" / LADDER).read_bytes() == data[LADDER]
    assert (tmp_path / "active" / "data/nfl/games.csv").read_bytes() == data[
        "data/nfl/games.csv"
    ]
    before = len(urls)
    cached = nfl_inputs.sync(tmp_path, NOW + timedelta(minutes=1))
    assert cached["status"] == "cached"
    assert len(urls) == before
    assert (tmp_path / "active").is_symlink()


def test_bad_digest_preserves_last_verified_bundle(monkeypatch, tmp_path):
    data, tree = sources()
    sha = "a" * 40

    def fetch(url):
        if url.endswith("/commits/main"):
            return json.dumps({"sha": sha}).encode()
        if "/git/trees/" in url:
            return json.dumps(tree).encode()
        return data[url.split(f"/{sha}/")[-1]]

    monkeypatch.setattr(nfl_inputs, "download", fetch)
    nfl_inputs.sync(tmp_path, NOW)
    before = (tmp_path / "active").resolve()
    other, other_tree = sources(NOW + timedelta(hours=1))
    other["data/nfl/games.csv"] = b"tampered"
    for entry in other_tree["tree"]:
        if entry["path"] == "data/nfl/games.csv":
            entry["sha"] = hashlib.sha1(b"tampered").hexdigest()
    changed = "b" * 40

    def bad_fetch(url):
        if url.endswith("/commits/main"):
            return json.dumps({"sha": changed}).encode()
        if "/git/trees/" in url:
            return json.dumps(other_tree).encode()
        return other[url.split(f"/{changed}/")[-1]]

    monkeypatch.setattr(nfl_inputs, "download", bad_fetch)
    with pytest.raises(ValueError, match="checksum"):
        nfl_inputs.sync(tmp_path, NOW + timedelta(hours=1))
    assert (tmp_path / "active").resolve() == before


def test_incomplete_tree_and_source_date_fail_closed():
    data, tree = sources()
    tree["truncated"] = True
    with pytest.raises(ValueError, match="Incomplete"):
        nfl_inputs.source_paths(tree, NOW)
    data["data/nfl/retrieval.json"] = json.dumps(
        {"retrieved": "2026-10-10", "sha256": {}}
    ).encode()
    with pytest.raises(ValueError, match="stale"):
        nfl_inputs.verify_bundle(data, LADDER, NOW)
