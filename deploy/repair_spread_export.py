"""Replace only the private exporter after matching the deployed accounting ledger."""

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PRODUCTION = Path("/home/trader/sports-market-maker-prod-auto")
STUDY = Path("/home/trader/spread-forward-study")
REVISION = "fe7a5e7a8cfff8eeb5018d5d047f549f8a7f7cbd"
OLD_EXPORT = "cfa6c044bf63ec3cf9e752c3fe88500dbfcf8c75004cd0b28b03e1da0e5b1a2a"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install_candidate(source, target, backup, expected_old=OLD_EXPORT):
    if target.is_symlink() or backup.is_symlink():
        raise ValueError("unexpected_exporter_symlink")
    old, new = target.read_bytes(), source.read_bytes()
    if old == new:
        return False
    if digest(old) != expected_old:
        raise ValueError("unexpected_exporter_baseline")
    if backup.exists() and backup.read_bytes() != old:
        raise ValueError("unexpected_backup")
    if not backup.exists():
        backup.write_bytes(old)
        backup.chmod(0o600)
    temporary = target.with_name(".export_private_fills.repair.tmp")
    try:
        temporary.write_bytes(new)
        temporary.chmod(target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def verify_accounting(candidate, records):
    from live import shared_account_risk as accounting

    if not hasattr(accounting, "external_closes"):
        raise ValueError("deployed_manual_close_ledger_required")
    as_of = max(datetime.fromisoformat(e["utc"].replace("Z", "+00:00"))
                for e in records if e.get("utc"))
    direct = accounting.spread_ledger(records, [], [], as_of)
    stream = [
        (e["event"], {k: v for k, v in e.items()
                      if k in candidate.KEEP_SPREAD[e["event"]]})
        for e in records if e.get("event") in candidate.KEEP_SPREAD
    ]
    exported = candidate.spread_tables(stream, now=as_of)[4]
    if exported.get("unavailable"):
        raise ValueError("candidate_accounting_unavailable")
    for key in ("cumulative", "daily", "by_day", "open", "settled", "fills"):
        if direct[key] != exported[key]:
            raise ValueError("candidate_accounting_mismatch")
    approvals = accounting.external_closes.approved(records, [], as_of)
    if not approvals or len(exported.get("external_close_rows", [])) != len(approvals):
        raise ValueError("external_close_export_mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply"))
    args = parser.parse_args()
    os.umask(0o077)
    if os.getuid() == 0 or Path.home() != Path("/home/trader"):
        raise ValueError("existing_trader_user_required")
    manifest = STUDY / "manifest.json"
    frozen = manifest.read_bytes()
    if json.loads(frozen)["production_revision"] != REVISION:
        raise ValueError("study_revision_changed")
    revision = subprocess.check_output(
        ["git", "-C", str(PRODUCTION), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise ValueError("production_revision_changed")
    subprocess.run(
        ["git", "-C", str(PRODUCTION), "diff", "--quiet", "HEAD", "--", "live", "kalshi"],
        check=True,
    )
    source = Path(__file__).resolve().parents[1] / "tools/export_private_fills.py"
    target = PRODUCTION / "tools/export_private_fills.py"
    if target.read_bytes() != source.read_bytes() and digest(target.read_bytes()) != OLD_EXPORT:
        raise ValueError("unexpected_exporter_baseline")
    sys.path.insert(0, str(PRODUCTION))
    spec = importlib.util.spec_from_file_location("candidate_private_export", source)
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    raw = Path("/home/trader/prod-spread-auto/journal.jsonl").read_text()
    if raw and not raw.endswith("\n"):
        raise ValueError("journal_read_incomplete_retry_later")
    verify_accounting(candidate, [json.loads(line) for line in raw.splitlines()])
    if args.action == "apply":
        install_candidate(source, target, STUDY / "exporter-before-accounting-repair.py")
    if manifest.read_bytes() != frozen:
        raise ValueError("study_manifest_changed")
    print("EXPORT_ACCOUNTING_MATCH=PASS")
    print("STUDY_MANIFEST_UNCHANGED=PASS")
    print("EXPORTER_ACTION=" + args.action)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Public workflow logs must never contain private evidence or amounts.
        print("EXPORT_REPAIR_FAILED=" + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
