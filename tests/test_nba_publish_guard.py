"""Regression tests for NBA publishing's false-positive success bug."""

import json
import subprocess

import pytest

from live.nba_publish_guard import decision


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.com")
    (root / "README.md").write_text("unrelated committed file\n")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "baseline")
    return root


def metadata(stamp):
    return {"generated_utc": stamp, "sha256": "fixture"}


def save_pair(root, stamp, commit=False, include_csv=True):
    folder = root / "outputs" / "projections"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "latest_meta.json").write_text(json.dumps(metadata(stamp)))
    if include_csv:
        (folder / "latest.csv").write_text("ticker,p_model\nA,0.5\n")
    if commit:
        git(root, "add", "outputs/projections")
        git(root, "commit", "-m", "published pair")


def test_untracked_fresh_pair_cannot_claim_it_was_published(repo):
    save_pair(repo, "2026-10-19T01:00:00+00:00", commit=False)
    # git reset --hard retains these untracked input files.
    git(repo, "reset", "--hard", "HEAD")
    assert (repo / "outputs/projections/latest_meta.json").exists()
    assert decision(repo, metadata("2026-10-19T01:00:00+00:00")) == (
        "publish_missing_committed_metadata"
    )


def test_same_committed_pair_can_be_safely_skipped(repo):
    save_pair(repo, "2026-10-19T01:00:00+00:00", commit=True)
    assert decision(repo, metadata("2026-10-19T01:00:00+00:00")) == (
        "skip_newer_or_equal_committed_bundle"
    )


def test_newer_generated_bundle_replaces_old_committed_pair(repo):
    save_pair(repo, "2026-10-19T01:00:00+00:00", commit=True)
    assert decision(repo, metadata("2026-10-19T02:00:00+00:00")) == (
        "publish_newer_bundle"
    )


def test_missing_committed_csv_never_counts_as_success(repo):
    save_pair(repo, "2026-10-19T01:00:00+00:00", commit=True, include_csv=False)
    assert decision(repo, metadata("2026-10-19T01:00:00+00:00")) == (
        "publish_missing_committed_csv"
    )


def test_unaware_timestamps_fail_closed(repo):
    save_pair(repo, "2026-10-19T01:00:00+00:00", commit=True)
    with pytest.raises(ValueError, match="timezone"):
        decision(repo, metadata("2026-10-19T02:00:00"))
