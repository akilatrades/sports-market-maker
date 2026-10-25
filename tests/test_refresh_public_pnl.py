import signal

import pytest

from deploy.refresh_public_pnl import COMMAND, validate


def valid_state():
    return {
        "MainPID": "321",
        "User": "trader",
        "ActiveState": "active",
        "SubState": "running",
        "Restart": "on-failure",
        "SuccessExitStatus": "",
        "RestartPreventExitStatus": "",
    }


def test_only_expected_owned_reporting_process_is_eligible():
    validate(valid_state(), 321, 1000, 1000, COMMAND, 0)


@pytest.mark.parametrize(
    "key,value",
    [
        ("MainPID", "322"),
        ("User", "root"),
        ("ActiveState", "inactive"),
        ("SubState", "dead"),
        ("Restart", "no"),
        ("SuccessExitStatus", "10"),
        ("RestartPreventExitStatus", "10"),
    ],
)
def test_refuses_stopped_or_changed_unit(key, value):
    state = valid_state()
    state[key] = value
    with pytest.raises(RuntimeError):
        validate(state, 321, 1000, 1000, COMMAND, 0)


@pytest.mark.parametrize(
    "owner,command,handled",
    [
        (0, COMMAND, 0),
        (1000, ["python", "-m", "live.spread_auto"], 0),
        (1000, COMMAND + ["--once"], 0),
        (1000, COMMAND, 1 << (signal.SIGUSR1 - 1)),
    ],
)
def test_refuses_other_processes_and_signal_handlers(owner, command, handled):
    with pytest.raises(RuntimeError):
        validate(valid_state(), 321, owner, 1000, command, handled)
