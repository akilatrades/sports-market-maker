"""Stage an immutable candidate and a signed-read preview; never arm a worker."""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from kalshi.trading import TradingClient
from live import prod_spread_v4 as worker
from live import production_lock, spread_policy
from research.spread_forward_recorder import ENVIRONMENT, environment


def main():
    os.umask(0o077)
    source = Path(__file__).resolve().parents[1]
    parent = Path("/home/trader/spread-v4/releases")
    revision = source.name
    if os.getuid() == 0 or Path.home() != Path("/home/trader") or source.parent != parent:
        raise ValueError("isolated_trader_release_required")
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("commit_revision_required")
    frozen = worker.STUDY.read_bytes()
    manifest = json.loads(frozen)
    if manifest.get("production_revision") != worker.FROZEN_REVISION:
        raise ValueError("unexpected_frozen_revision")
    if subprocess.check_output(["git", "-C", str(worker.PRODUCTION), "rev-parse", "HEAD"], text=True).strip() != worker.FROZEN_REVISION:
        raise ValueError("production_revision_changed")
    # A gate or an existing immutable receipt cannot be overwritten by staging.
    receipt = source / "candidate.json"
    if receipt.exists() or worker.GATE.exists():
        raise ValueError("candidate_or_live_gate_already_exists")
    env = environment(ENVIRONMENT)
    client = TradingClient(dry_run=True, env="prod", key_id=env["KALSHI_KEY_ID"], private_key_pem=env["KALSHI_PRIVATE_KEY"])
    del env
    preview = {"decision": "blocked"}
    try:
        with production_lock.account_lock():
            preview = worker.run_once(client, worker.STATE / "journal.jsonl", datetime.now(UTC), spread_policy.SERIES)
    except Exception as error:
        preview.update(error_class=type(error).__name__, error=str(error)[:240])
    if worker.STUDY.read_bytes() != frozen:
        raise ValueError("frozen_study_changed")
    result = {
        "revision": revision, "source_sha256": worker.source_digest(source),
        "at": datetime.now(UTC).isoformat(), "live_enabled": False,
        "preview": preview,
    }
    receipt.write_text(json.dumps(result, sort_keys=True, indent=2, default=str) + "\n")
    print("V4_CANDIDATE_STAGED=YES")
    print("V4_LIVE_ENABLED=NO")
    print("V4_PREVIEW=" + preview["decision"])
    print("FROZEN_STUDY_UNCHANGED=YES")


if __name__ == "__main__":
    main()
