"""Preflight entrypoint must use the real signed GET-only client's API."""

import contextlib
import inspect
import json

import pytest

from live.account_dashboard import ReadOnlyClient
from tools import dual_account_preflight as preflight


@pytest.fixture(autouse=True)
def no_server_lock(monkeypatch):
    held = []

    @contextlib.contextmanager
    def lock():
        held.append(True)
        yield

    monkeypatch.setattr(preflight, "account_lock", lock)
    return held


def test_preflight_reads_under_the_account_lock(monkeypatch, capsys, no_server_lock):
    class FakeClient:
        env = "prod"
        can_sign = True

    def fake_report(client, now):
        assert no_server_lock == [True]  # taken before any read
        return {"status": "SHARED_ACCOUNT_RECONCILED"}

    monkeypatch.setattr(preflight, "ReadOnlyClient", FakeClient)
    monkeypatch.setattr(preflight, "report", fake_report)
    preflight.main()
    assert no_server_lock == [True]


def test_signed_readonly_client_constructor_accepts_no_keyword_arguments():
    # Regression: the deployed check previously passed TradingClient's
    # (dry_run, env) kwargs to ReadOnlyClient, causing a TypeError.
    assert not inspect.signature(ReadOnlyClient).parameters


def test_preflight_main_uses_no_argument_readonly_client(monkeypatch, capsys):
    class FakeClient:
        env = "prod"
        can_sign = True

    calls = []

    def get_client():
        calls.append("signed_get_client")
        return FakeClient()

    def fake_report(client, now):
        assert isinstance(client, FakeClient)
        assert now.tzinfo is not None
        return {"status": "SHARED_ACCOUNT_RECONCILED"}

    monkeypatch.setattr(preflight, "ReadOnlyClient", get_client)
    monkeypatch.setattr(preflight, "report", fake_report)
    preflight.main()
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SHARED_ACCOUNT_RECONCILED"
    assert calls == ["signed_get_client"]


def test_preflight_failure_redacts_raw_client_errors(monkeypatch, capsys):
    def fail_client():
        raise TypeError("NEVER_PRINT_PRIVATE_SECRET")

    monkeypatch.setattr(preflight, "ReadOnlyClient", fail_client)
    with pytest.raises(SystemExit) as result:
        preflight.main()
    assert result.value.code == 2
    output = capsys.readouterr().out
    assert "NEVER_PRINT_PRIVATE_SECRET" not in output
    assert json.loads(output)["reason_type"] == "TypeError"
