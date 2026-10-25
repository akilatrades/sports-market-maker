"""Private confirmation and append safeguards; all data are synthetic."""

from copy import deepcopy
from datetime import timedelta

import pytest

from kalshi.trading import TradingError
from live import external_spread_closes as external
from tools import reconcile_external_spread_closes as repair
from tests.test_external_spread_closes import fixture
from tests.test_shared_account_spread import NOW, cohorts, _write


def snapshot():
    events, entry, close = fixture()
    journals = cohorts(spread=events[:-1])
    evidence = {
        "source": "signed_exchange_gets",
        "stable_capture": True,
        "complete_pagination": True,
        "journals": journals,
        "journal_sha256": {},
        "fills": [entry, close],
        "positions": [],
        "resting_orders": [],
        "settlements": [],
    }
    consent = {
        "normalized_fill_sha256": [external.fingerprint(external.normalize(close))],
        "manual_close_fees": ".0867",
        "expected_spread_net": "1.8633",
    }
    return evidence, consent


def test_plan_does_not_modify_snapshot_or_adopt_future_activity():
    evidence, consent = snapshot()
    original = deepcopy(evidence)
    plan = repair.build_plan(evidence, NOW, consent)
    assert evidence == original and plan["candidate_count"] == 1
    assert plan["positions_verified"] is True and plan["safe_to_resume"] is False
    modified = deepcopy(evidence)
    modified["fills"][-1]["fill_id"] = "different-exchange-id"
    with pytest.raises(TradingError, match="confirmation"):
        repair.build_plan(modified, NOW, consent)


def test_replay_after_append_is_idempotent():
    evidence, consent = snapshot()
    plan = repair.build_plan(evidence, NOW, consent)
    evidence["journals"]["spread"] += plan["events_to_append"]
    assert (
        repair.build_plan(evidence, NOW + timedelta(seconds=1), consent)[
            "events_to_append"
        ]
        == []
    )


def test_wrong_fee_or_net_profit_blocks_plan():
    evidence, consent = snapshot()
    for key in ("manual_close_fees", "expected_spread_net"):
        invalid = {**consent, key: "0"}
        with pytest.raises(TradingError):
            repair.build_plan(evidence, NOW, invalid)


def test_ambiguous_confirmation_and_partial_snapshot_rejected():
    evidence, consent = snapshot()
    with pytest.raises(TradingError):
        repair.build_plan(evidence, NOW, {**consent, "normalized_fill_sha256": []})
    with pytest.raises(TradingError):
        repair.build_plan({**evidence, "complete_pagination": False}, NOW, consent)


def test_verified_append_preserves_original_and_rejects_changed_journal(tmp_path):
    evidence, consent = snapshot()
    for sport, events in evidence["journals"].items():
        _write(tmp_path, sport, events)
    evidence["journal_sha256"] = repair.read_journals(tmp_path)[1]
    plan = repair.build_plan(evidence, NOW, consent)
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    path = tmp_path / "prod-spread-auto/journal.jsonl"
    original = path.read_bytes()
    backup = repair.append_verified(tmp_path, plan, folder)
    assert backup.read_bytes() == original
    assert backup.stat().st_mode & 0o777 == 0o600
    assert len(path.read_bytes().splitlines()) == len(original.splitlines()) + 1
    with pytest.raises(TradingError, match="changed"):
        repair.append_verified(tmp_path, plan, folder)


def test_reconciliation_client_rejects_all_writes_without_network():
    client = repair.ReadOnlyClient(dry_run=True, env="prod")
    with pytest.raises(TradingError, match="GETs only"):
        client._request("POST", "/portfolio/orders", body={})
    with pytest.raises(TradingError, match="GETs only"):
        client._request("GET", "/unapproved")
