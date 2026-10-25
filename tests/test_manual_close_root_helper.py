"""The prepared root entry point is bounded and cannot start trading."""

import importlib.util
import json
from pathlib import Path

import pytest

from tools import prepare_manual_close_root as prepare

SPEC = importlib.util.spec_from_file_location(
    "root_apply", Path(__file__).parents[1] / "deploy/apply_verified_manual_closes.py"
)
root_apply = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(root_apply)


def test_helper_rejects_service_starts_without_calling_systemctl(monkeypatch):
    monkeypatch.setattr(
        root_apply.subprocess, "run", lambda *a, **k: pytest.fail("must not execute")
    )
    for action in ("start", "restart", "enable", "stop"):
        with pytest.raises(ValueError):
            root_apply.systemctl(action, "anything")


def test_code_update_rejects_service_and_strategy_changes():
    root_apply.allowed_diff(["live/shared_account_risk.py"])
    for path in (
        "live/spread_policy.py", "requirements.txt", "deploy/example.service"
    ):
        with pytest.raises(ValueError):
            root_apply.allowed_diff([path])


def test_helper_cannot_operate_as_trader(monkeypatch, capsys):
    monkeypatch.setattr(root_apply.os, "geteuid", lambda: 1000)
    with pytest.raises(SystemExit):
        root_apply.main()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "HALTED_NO_RESTART"
    assert result["timers_paused"] is False and result["workers_restarted"] == 0


def test_preparation_never_overwrites_existing_files(tmp_path):
    path = tmp_path / "helper"
    prepare.private_new_or_same(path, b"approved")
    assert path.stat().st_mode & 0o777 == 0o600
    prepare.private_new_or_same(path, b"approved")
    with pytest.raises(ValueError, match="overwrite"):
        prepare.private_new_or_same(path, b"changed")
    assert path.read_bytes() == b"approved"


def test_preparation_rejects_symlinks(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"private")
    path = tmp_path / "link"
    path.symlink_to(target)
    with pytest.raises(ValueError):
        prepare.private_new_or_same(path, b"private")


def test_stage_path_must_not_escape_home():
    with pytest.raises(ValueError):
        root_apply.validate_stage("/root/recon-stage.invalid")
