"""End-to-end checks of deploy/smm-prod-control.sh against stand-in system tools.

The real helper runs as root on the Droplet. Here a copy runs with its fixed
paths pointed at a temporary directory, and `systemctl`, `systemd-run`,
`runuser`, `install` and `chown` replaced by small shims, so the go-live,
rollback, stop and cancel flows run for real without touching any system.
GitHub Actions logs are public, so every flow also checks that nothing from
the settings files or account checks reaches the printed output.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "deploy" / "smm-prod-control.sh"
SECRET = "TOPSECRET-KEY-VALUE-123"
ACCOUNT_DETAIL = "cash_dollars 987.65"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("bash", "git", "flock", "python3")),
    reason="needs bash, git, flock and python3",
)

SYSTEMCTL = r"""#!/usr/bin/env bash
S="$SHIM_STATE"
cmd="$1"; shift
case "$cmd" in
  enable|disable|stop|start)
    now=0; if [[ "${1:-}" == --now ]]; then now=1; shift; fi
    for u in "$@"; do
      case "$cmd" in
        enable) touch "$S/$u.enabled"; if (( now )); then touch "$S/$u.active"; fi ;;
        disable) rm -f "$S/$u.enabled"; if (( now )); then rm -f "$S/$u.active"; fi ;;
        stop) rm -f "$S/$u.active" ;;
        start)
          if [[ "$u" == *.service ]]; then
            echo "$u" >> "$S/started"
            if [[ -n "${SHIM_FAIL_START:-}" && "$u" == *"$SHIM_FAIL_START"* ]]; then
              echo exit-code > "$S/$u.result"; exit 1
            fi
            echo success > "$S/$u.result"
          else
            touch "$S/$u.active"
          fi ;;
      esac
    done ;;
  is-active)
    q=0; if [[ "$1" == --quiet ]]; then q=1; shift; fi
    if [[ -e "$S/$1.active" ]]; then (( q )) || echo active; exit 0; fi
    (( q )) || echo inactive; exit 3 ;;
  is-enabled)
    if [[ -e "$S/$1.enabled" ]]; then echo enabled; exit 0; fi
    echo disabled; exit 1 ;;
  show)
    u="$1"; shift; prop=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --property=*) prop="${1#--property=}" ;;
        -p) prop="$2"; shift ;;
      esac
      shift
    done
    case "$prop" in
      ActiveState) echo inactive ;;
      Result) cat "$S/$u.result" 2>/dev/null || echo success ;;
    esac ;;
esac
"""

SYSTEMD_RUN = r"""#!/usr/bin/env bash
# Find the python module being checked; print account-like detail.
module=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == -m ]]; then module="$2"; break; fi
  shift
done
echo "$module" >> "$SHIM_STATE/checks"
echo "ACCOUNT DETAIL: cash_dollars 987.65 for $module"
if [[ -n "${SHIM_FAIL_MODULE:-}" && "$module" == "$SHIM_FAIL_MODULE" ]]; then exit 2; fi
exit 0
"""

RUNUSER = r"""#!/usr/bin/env bash
# runuser -u trader -- cmd ...
shift 3
exec "$@"
"""

INSTALL = r"""#!/usr/bin/env bash
for last; do :; done
: > "$last"
"""

NOOP = "#!/usr/bin/env bash\nexit 0\n"


def git(cwd, *args):
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


def head(cwd):
    return subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def box(tmp_path):
    t = tmp_path
    shims = t / "shims"
    shims.mkdir()
    for name, body in {
        "systemctl": SYSTEMCTL,
        "systemd-run": SYSTEMD_RUN,
        "runuser": RUNUSER,
        "install": INSTALL,
        "chown": NOOP,
    }.items():
        path = shims / name
        path.write_text(body)
        path.chmod(0o755)
    state = t / "state"
    state.mkdir()

    # A production checkout that tracks a local "origin".
    work = t / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    (work / "live").mkdir()
    (work / "live" / "worker.py").write_text("VERSION = 1\n")
    (work / "outputs").mkdir()
    (work / "outputs" / "data.csv").write_text("a\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "code")
    origin = t / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(origin)], check=True)
    prod = t / "prod"
    subprocess.run(["git", "clone", "-q", str(origin), str(prod)], check=True)
    (prod / ".venv" / "bin").mkdir(parents=True)
    (prod / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    (prod / ".venv" / "bin" / "python").chmod(0o755)
    git(work, "remote", "add", "origin", str(origin))

    etc = t / "etc"
    etc.mkdir()
    (etc / "nfl.env").write_text(
        "KALSHI_ENV=prod\nTRADE_MODE=live\nALLOW_PRODUCTION_TRADING=YES\n"
        f"PROD_AUTO_ARM=YES\nKALSHI_PRIVATE_KEY={SECRET}\n"
    )
    (etc / "nba.env").write_text(
        "KALSHI_ENV=prod\nTRADE_MODE=live\nALLOW_PRODUCTION_TRADING=YES\n"
        f"TRADE_MARKET=nba\nKALSHI_PRIVATE_KEY={SECRET}\n"
    )
    for sport in ("nfl", "nba"):
        (t / sport).mkdir()
        (t / sport / "journal.jsonl").write_text("")

    text = HELPER.read_text()
    replacements = {
        '[[ "$EUID" == 0 ]] || { echo "ERROR: root required" >&2; exit 2; }': "",
        "/home/trader/sports-market-maker-prod-auto": str(prod),
        "/etc/market-maker-prod-auto.env": str(etc / "nfl.env"),
        "/etc/market-maker-prod-nba-auto.env": str(etc / "nba.env"),
        "/etc/market-maker-shared-account.enabled": str(etc / "marker"),
        "/home/trader/prod-nfl-auto": str(t / "nfl"),
        "/home/trader/prod-nba-auto": str(t / "nba"),
        "/root/smm-control-logs": str(t / "logs"),
        "/run/lock/smm-production-release.lock": str(t / "lock"),
        "/root/smm-control-backup.XXXXXXXX": str(t / "backup.XXXXXXXX"),
    }
    for old, new in replacements.items():
        assert old in text, old
        text = text.replace(old, new)
    script = t / "smm-prod-control"
    script.write_text(text)
    script.chmod(0o755)

    def run(*args, **extra_env):
        env = {
            **os.environ,
            "PATH": f"{shims}:{os.environ['PATH']}",
            "SHIM_STATE": str(state),
            **extra_env,
        }
        result = subprocess.run(
            ["bash", str(script), *args], capture_output=True, text=True, env=env
        )
        output = result.stdout + result.stderr
        # Public-log rule: nothing from settings files or account checks.
        assert SECRET not in output
        assert ACCOUNT_DETAIL not in output
        assert str(etc) not in output
        return result.returncode, output

    return {
        "run": run,
        "state": state,
        "etc": etc,
        "t": t,
        "work": work,
        "prod": prod,
        "sha": head(prod),
    }


def active(box, unit):
    return (box["state"] / f"{unit}.active").exists()


NBA_TIMER = "market-maker-prod-nba-auto.timer"
NFL_TIMER = "market-maker-prod-nfl-auto.timer"


def test_status_prints_only_states(box):
    code, out = box["run"]("status")
    assert code == 0
    assert "NBA_TIMER=inactive" in out and "NFL_TIMER=inactive" in out
    assert "NBA_ARM_FLAG=no" in out and "NFL_ARM_FLAG=yes" in out


def test_go_live_arms_both_and_keeps_other_settings(box):
    code, out = box["run"]("go-live", box["sha"])
    assert code == 0, out
    assert "LIVE: NBA_TIMER=active NFL_TIMER=active" in out
    assert active(box, NBA_TIMER) and active(box, NFL_TIMER)
    assert (box["state"] / f"{NBA_TIMER}.enabled").exists()
    nba = (box["etc"] / "nba.env").read_text()
    nfl = (box["etc"] / "nfl.env").read_text()
    assert "PROD_NBA_AUTO_ARM=YES" in nba and "SMM_DUAL_MARKET=YES" in nba
    assert "SMM_DUAL_MARKET=YES" in nfl
    assert (
        f"KALSHI_PRIVATE_KEY={SECRET}" in nba and f"KALSHI_PRIVATE_KEY={SECRET}" in nfl
    )
    assert (box["etc"] / "marker").exists()
    checks = (box["state"] / "checks").read_text().split()
    assert checks == [
        "tools.dual_account_preflight",
        "tools.dual_account_preflight",
        "live.prod_nba_auto",
    ]
    # Full check output stays in root-only files, not the public log.
    logs = list((box["t"] / "logs").iterdir())
    assert logs and all(oct(p.stat().st_mode)[-3:] == "600" for p in logs)


def test_failed_check_after_arming_restores_settings_and_stays_off(box):
    before = {name: (box["etc"] / name).read_bytes() for name in ("nba.env", "nfl.env")}
    code, out = box["run"]("go-live", box["sha"], SHIM_FAIL_MODULE="live.prod_nba_auto")
    assert code != 0
    assert "CHECK nba-readiness: FAIL" in out and "GO_LIVE FAILED" in out
    for name, content in before.items():
        assert (box["etc"] / name).read_bytes() == content
    assert not (box["etc"] / "marker").exists()
    assert not active(box, NBA_TIMER) and not active(box, NFL_TIMER)


def test_failed_check_before_arming_changes_nothing(box):
    before = (box["etc"] / "nba.env").read_bytes()
    code, out = box["run"](
        "go-live", box["sha"], SHIM_FAIL_MODULE="tools.dual_account_preflight"
    )
    assert code != 0
    assert "CHECK account-before: FAIL" in out
    assert (box["etc"] / "nba.env").read_bytes() == before
    assert not active(box, NBA_TIMER)


def test_go_live_refuses_undeployed_code(box):
    (box["work"] / "live" / "worker.py").write_text("VERSION = 2\n")
    git(box["work"], "commit", "-q", "-am", "new code")
    git(box["work"], "push", "-q", "origin", "main")
    code, out = box["run"]("go-live", head(box["work"]))
    assert code != 0
    assert "differs from the requested commit" in out
    assert not active(box, NBA_TIMER)


def test_go_live_accepts_newer_data_only_commit(box):
    (box["work"] / "outputs" / "data.csv").write_text("b\n")
    git(box["work"], "commit", "-q", "-am", "data only")
    git(box["work"], "push", "-q", "origin", "main")
    code, out = box["run"]("go-live", head(box["work"]))
    assert code == 0, out


def test_go_live_refuses_when_kill_switch_present(box):
    (box["t"] / "nba" / "KILL").write_text("owner\n")
    code, out = box["run"]("go-live", box["sha"])
    assert code != 0 and "KILL switch is present" in out
    assert not active(box, NBA_TIMER)


def test_go_live_rejects_bad_sha(box):
    code, _ = box["run"]("go-live", "main; rm -rf /")
    assert code == 2


def test_stop_disables_both_timers(box):
    assert box["run"]("go-live", box["sha"])[0] == 0
    code, out = box["run"]("stop")
    assert code == 0 and "STOPPED" in out
    assert not active(box, NBA_TIMER) and not active(box, NFL_TIMER)
    assert not (box["state"] / f"{NBA_TIMER}.enabled").exists()


def test_stop_and_cancel_runs_kill_pass_and_removes_only_its_own_switch(box):
    assert box["run"]("go-live", box["sha"])[0] == 0
    (box["t"] / "nfl" / "KILL").write_text("owner placed this\n")
    code, out = box["run"]("stop-and-cancel")
    assert code == 0, out
    assert "CANCEL NBA: PASS" in out and "CANCEL NFL: PASS" in out
    started = (box["state"] / "started").read_text().split()
    assert started == [
        "market-maker-prod-nba-auto.service",
        "market-maker-prod-nfl-auto.service",
    ]
    assert not (box["t"] / "nba" / "KILL").exists()
    assert (box["t"] / "nfl" / "KILL").read_text() == "owner placed this\n"
    assert not active(box, NBA_TIMER) and not active(box, NFL_TIMER)


def test_failed_cancel_leaves_kill_switches(box):
    code, out = box["run"]("stop-and-cancel", SHIM_FAIL_START="nba")
    assert code != 0 and "CANCEL NBA: FAIL" in out
    assert (box["t"] / "nba" / "KILL").exists()


def test_control_workflow_is_owner_only_confirmed_and_manual():
    text = (ROOT / ".github/workflows/droplet-control.yml").read_text()
    assert "workflow_dispatch:" in text
    for trigger in ("\n  push:", "\n  pull_request", "\n  schedule:"):
        assert trigger not in text
    assert text.count("github.actor == 'akilatrades'") == 2
    assert '[[ "$CONFIRM" == "$ACTION" ]]' in text
    assert "sudo -n /usr/local/sbin/smm-prod-control" in text
    assert "secrets.KALSHI" not in text
    # GO_LIVE must wait for the full test suite.
    assert "needs.tests.result == 'success'" in text
    assert "inputs.action != 'GO_LIVE'" in text


def test_helper_keeps_check_output_off_the_public_log():
    text = HELPER.read_text()
    assert '>"$log" 2>&1' in text  # account checks go to root-only files
    assert 'cat "$NFL_ENV"' not in text and 'cat "$NBA_ENV"' not in text
    assert "systemctl disable --now" in text  # stopped bots stay off after reboot
