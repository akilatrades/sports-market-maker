"""Decide NBA input publication using *committed* metadata, never untracked files.

Git reset --hard does not remove untracked files. The original publication
workflow compared its newly generated untracked latest_meta.json with itself
after reset, then exited successfully without committing any inputs.

This guard only trusts `git show HEAD:<path>`, and requires BOTH committed
input blobs before returning SKIP (exit 10). Exit 0 means publish, and
other nonzero exit codes block the workflow. No orders or API calls.
"""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

CSV_PATH = "outputs/projections/latest.csv"
META_PATH = "outputs/projections/latest_meta.json"
SKIP_PUBLISHED = 10


def committed(repo, path):
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"HEAD:{path}"],
        capture_output=True,
        check=False,
    )


def decision(repo, fresh_meta):
    current = committed(repo, META_PATH)
    if current.returncode != 0:
        return "publish_missing_committed_metadata"
    csv = committed(repo, CSV_PATH)
    if csv.returncode != 0:
        return "publish_missing_committed_csv"
    if not csv.stdout.strip():
        return "publish_empty_committed_csv"
    old = json.loads(current.stdout)
    new_time = datetime.fromisoformat(
        fresh_meta["generated_utc"].replace("Z", "+00:00")
    )
    old_time = datetime.fromisoformat(old["generated_utc"].replace("Z", "+00:00"))
    if new_time.tzinfo is None or old_time.tzinfo is None:
        raise ValueError("Projection timestamps must include timezone")
    if old_time >= new_time:
        return "skip_newer_or_equal_committed_bundle"
    return "publish_newer_bundle"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-meta", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    fresh = json.loads(args.fresh_meta.read_text())
    result = decision(args.repo, fresh)
    print(result, flush=True)
    return SKIP_PUBLISHED if result.startswith("skip_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
