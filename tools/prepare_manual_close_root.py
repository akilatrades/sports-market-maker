"""Prepare a verified helper as data for explicit root-console execution.

This operation runs as trader, never calls sudo, and never executes the helper.
"""

import argparse
import hashlib
import json
import os
import pwd
import re
import urllib.request
from pathlib import Path

HOME = Path("/home/trader")


def private_new_or_same(path, data):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if path.is_symlink() or path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077 or path.read_bytes() != data:
            raise ValueError("Existing file is different; refusing overwrite") from None
        return
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    try:
        if pwd.getpwuid(os.geteuid()).pw_name != "trader":
            raise ValueError("Existing trader account required")
        stage = Path(args.stage)
        if stage.parent != HOME or stage.resolve() != stage or not re.fullmatch(r"recon-stage\.[A-Za-z0-9_]+", stage.name):
            raise ValueError("Invalid private stage")
        if stage.stat().st_mode & 0o077:
            raise ValueError("Stage must be private")
        results = list((stage / "evidence").glob("result-*.json"))
        if len(results) != 1 or json.loads(results[0].read_text()).get("positions_verified") is not True:
            raise ValueError("Verified dry-run result required")
        if not re.fullmatch("[0-9a-f]{40}", args.commit) or not re.fullmatch("[0-9a-f]{64}", args.sha256):
            raise ValueError("Exact source identities required")
        url = f"https://raw.githubusercontent.com/akilatrades/sports-market-maker/{args.commit}/deploy/apply_verified_manual_closes.py"
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read(200_001)
        if len(body) > 200_000 or hashlib.sha256(body).hexdigest() != args.sha256:
            raise ValueError("Root helper source integrity mismatch")
        private_new_or_same(HOME / "r", body)
        pointer = HOME / ("reconciliation-active-" + args.sha256[:12] + ".json")
        private_new_or_same(pointer, (json.dumps({"stage": str(stage), "helper_sha256": args.sha256}, sort_keys=True) + "\n").encode())
        print(json.dumps({"status": "ROOT_HELPER_PREPARED_NOT_EXECUTED", "helper_sha256": args.sha256,
                          "helper_path": str(HOME / "r"), "production_changes": 0, "journal_changes": 0}))
    except Exception as error:
        print(json.dumps({"status": "PREPARATION_HALTED", "reason_class": type(error).__name__,
                          "reason": str(error) if isinstance(error, ValueError) else None}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
