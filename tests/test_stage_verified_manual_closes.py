"""Source validation must fail before any staging writes or execution."""

import hashlib
import io
import sys

import pytest

from tools import stage_verified_manual_closes as stage


def test_download_checks_exact_payload_hash(monkeypatch):
    data = b"synthetic public source"
    monkeypatch.setattr(
        stage, "HASHES", {"tools/example.py": hashlib.sha256(data).hexdigest()}
    )
    seen = []

    def response(url, timeout):
        seen.append(url)
        return io.BytesIO(data)

    monkeypatch.setattr(stage.urllib.request, "urlopen", response)
    assert stage.download("tools/example.py") == data
    assert f"/{stage.SOURCE}/tools/example.py" in seen[0]
    monkeypatch.setattr(
        stage.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"changed")
    )
    with pytest.raises(ValueError, match="integrity"):
        stage.download("tools/example.py")


def test_wrong_production_revision_stops_before_network_or_writes(monkeypatch, capsys):
    monkeypatch.setattr(stage.os, "geteuid", lambda: 0)
    monkeypatch.setattr(stage, "git", lambda *args: b"unexpected-revision")
    monkeypatch.setattr(
        stage, "download", lambda *args: pytest.fail("must not download")
    )
    monkeypatch.setattr(
        stage.tempfile, "mkdtemp", lambda **kw: pytest.fail("must not write")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stage",
            "--expected-net",
            "1",
            "--expected-fees",
            "0",
            "--expected-count",
            "1",
        ],
    )
    with pytest.raises(SystemExit):
        stage.main()
    assert "Unexpected deployed revision" in capsys.readouterr().out


def test_existing_trader_needs_no_privilege_escalation(monkeypatch):
    monkeypatch.setattr(stage.os, "geteuid", lambda: 1000)
    assert stage.trader_command("git", "status") == ["git", "status"]
    monkeypatch.setattr(stage.os, "geteuid", lambda: 0)
    assert stage.trader_command("git", "status") == [
        "runuser",
        "-u",
        "trader",
        "--",
        "git",
        "status",
    ]
