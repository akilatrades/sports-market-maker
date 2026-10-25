"""Stage a hash-pinned manual-close repair and dry-run it; never alter production.

Runs as trader or the owner in the server console. Downloads are hash verified and are
executed only as trader. Output evidence is private and non-overwriting.
"""

import argparse
import hashlib
import io
import json
import os
import pwd
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

BASE = "0500b006d5d223bb2accef32ca265f931c98fcbe"
SOURCE = "b8c22efad885ce70280fe230be192331421e6615"
ROOT = Path("/home/trader/sports-market-maker-prod-auto")
PYTHON = ROOT / ".venv/bin/python"
HASHES = {
    "live/shared_account_risk.py": "d89f074a92f7d9266b70e4127acc8fa5f9f5a2423a7d4fce99e1566bddbbb07f",
    "live/external_spread_closes.py": "e5631858d653cc151b5c858856ef27e7978639a3e484f03845469b806be51318",
    "tools/account_reconciliation_snapshot.py": "211ac1f328c1629f7a31b4d2dd99010dfcb4740c54923df47b81f5f8713bc013",
    "tools/reconcile_external_spread_closes.py": "6497251472835d353d0293e7d7bd4a4cdee9f394d37eb4d099e537e1f4a23579",
}

CHILD = """
import json, sys
from pathlib import Path
from live import external_spread_closes as ext
from tools.account_reconciliation_snapshot import write_private
cfg=json.load(sys.stdin)
evidence=Path(cfg["evidence"])
snapshot=json.loads((evidence/"snapshot.json").read_text())
review=json.loads((evidence/"review.json").read_text())
assert review["snapshot_sha256"]==ext.fingerprint(snapshot)
assert not review["other_external_fills"] and not review["unowned_resting_orders"]
items=review["candidate_external_fills"]
assert len(items)==cfg["count"]
for item in items:
    assert item["fill_sha256"]==ext.fingerprint(item["raw_fill"])
confirmation={"normalized_fill_sha256":[ext.fingerprint(ext.normalize(i["raw_fill"])) for i in items],
              "expected_spread_net":cfg["net"],"manual_close_fees":cfg["fees"],
              "original_snapshot_sha256":ext.fingerprint(snapshot)}
write_private(Path(cfg["stage"])/"confirmation.json",confirmation)
"""


def trader_command(*args):
    prefix = ["runuser", "-u", "trader", "--"] if os.geteuid() == 0 else []
    return prefix + list(args)


def git(*args):
    return subprocess.run(
        trader_command("git", "-C", str(ROOT), *args),
        check=True,
        capture_output=True,
    ).stdout


def download(path):
    url = f"https://raw.githubusercontent.com/akilatrades/sports-market-maker/{SOURCE}/{path}"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(200_001)
    if len(data) > 200_000 or hashlib.sha256(data).hexdigest() != HASHES[path]:
        raise ValueError("Source integrity verification failed")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-net", required=True)
    parser.add_argument("--expected-fees", required=True)
    parser.add_argument("--expected-count", required=True, type=int)
    args = parser.parse_args()
    stage = None
    try:
        if os.geteuid() != 0 and pwd.getpwuid(os.geteuid()).pw_name != "trader":
            raise ValueError("Owner or existing trader account required")
        if git("rev-parse", "HEAD").decode().strip() != BASE:
            raise ValueError("Unexpected deployed revision")
        if git(
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "live",
            "kalshi",
            "markets",
            "tools",
        ).strip():
            raise ValueError("Production code must be unchanged")
        evidence = list(Path("/home/trader").glob("recon-readonly.*/review.json"))
        if len(evidence) != 1 or not evidence[0].with_name("snapshot.json").is_file():
            raise ValueError("Exactly one complete private capture required")
        os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
        payloads = {path: download(path) for path in HASHES}
        stage = Path(tempfile.mkdtemp(prefix="recon-stage.", dir="/home/trader"))
        os.chmod(stage, 0o700)
        archive = git("archive", BASE, "live", "kalshi", "markets", "tools")
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(stage, filter="data")
        for path, data in payloads.items():
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise ValueError("Unexpected source symlink")
            target.write_bytes(data)
        (stage / "evidence").mkdir(mode=0o700)
        if os.geteuid() == 0:
            identity = pwd.getpwnam("trader")
            for path in [stage, *stage.rglob("*")]:
                os.chown(path, identity.pw_uid, identity.pw_gid, follow_symlinks=False)
        config = {
            "stage": str(stage),
            "evidence": str(evidence[0].parent),
            "net": args.expected_net,
            "fees": args.expected_fees,
            "count": args.expected_count,
        }
        environment = {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "PYTHONPATH": str(stage),
            "PYTHONNOUSERSITE": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
        }
        log_fd = os.open(
            stage / "stage.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(log_fd, "wb") as log:
            subprocess.run(
                trader_command(str(PYTHON), "-c", CHILD),
                input=json.dumps(config).encode(),
                cwd=stage,
                env=environment,
                stdout=log,
                stderr=log,
                check=True,
            )
            subprocess.run(
                trader_command(
                    str(PYTHON),
                    "-m",
                    "tools.reconcile_external_spread_closes",
                    "plan",
                    "--snapshot",
                    str(evidence[0].with_name("snapshot.json")),
                    "--confirmation",
                    str(stage / "confirmation.json"),
                    "--evidence-dir",
                    str(stage / "evidence"),
                ),
                cwd=stage,
                env=environment,
                stdout=log,
                stderr=log,
                check=True,
            )
        print(
            json.dumps(
                {
                    "status": "STAGED_PLAN_VERIFIED",
                    "stage": str(stage),
                    "production_changes": 0,
                    "journal_changes": 0,
                    "trading_actions": 0,
                }
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "STAGING_HALTED",
                    "reason_class": type(error).__name__,
                    "stage": str(stage) if stage else None,
                    "production_changes": 0,
                    "reason": str(error) if isinstance(error, ValueError) else None,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
