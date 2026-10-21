"""The private fills export: what it reads, what it writes, where it pushes."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools import export_private_fills as export

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 4, 0, tzinfo=UTC)
CLIENT, ORDER, FILL = (
    "client-secret-uuid-1",
    "exchange-order-id-1",
    "exchange-fill-id-1",
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must never reach GitHub")

    monkeypatch.setattr(export, "urlopen", refuse)


def nba_journal(path, partial_tail=False):
    events = [
        {
            "event": "intent",
            "utc": "2026-10-21T19:00:00+00:00",
            "client_order_id": CLIENT,
            "ticker": "KXNBAPTS-26OCT21LALGSW-LALLJAMES23-25",
            "price_cents": 56,
            "count": 1,
            "cost": 0.56,
            "game_id": "401",
            "team": "LAL",
            "tip_utc": "2026-10-22T02:00:00+00:00",
            "strategy_version": "nba-no-v5-one-contract-breadth",
            "probability_source": "sportsbook",
            "edge": 0.055,
            "sportsbook_probability_yes_at_entry": 0.38,
            "kalshi_yes_bid_at_entry": 0.42,
            "kalshi_yes_ask_at_entry": 0.45,
            "unlisted_private_field": "must not be exported",
        },
        {
            "event": "accepted",
            "utc": "2026-10-21T19:00:01+00:00",
            "client_order_id": CLIENT,
            "order_id": ORDER,
        },
        {
            "event": "queue",
            "utc": "2026-10-21T19:00:02+00:00",
            "order_id": ORDER,
            "ahead": 12,
        },
        {
            "event": "queue",
            "utc": "2026-10-21T19:10:02+00:00",
            "order_id": ORDER,
            "ahead": 3,
        },
        {
            "event": "fill",
            "fill_id": FILL,
            "utc": "2026-10-21T21:00:00+00:00",
            "ticker": "KXNBAPTS-26OCT21LALGSW-LALLJAMES23-25",
            "order_id": ORDER,
            "count": "1.00",
            "yes_price": "0.4400",
            "no_price": "0.5600",
            "fee": "0.0000",
            "is_taker": False,
        },
        {
            "event": "markout",
            "fill_id": FILL,
            "horizon_minutes": 15,
            "mid_move_dollars": 0.02,
            "bid_move_dollars": 0.01,
        },
        {
            "event": "intent",
            "utc": "2026-10-21T19:05:00+00:00",
            "client_order_id": "client-2",
            "ticker": "KXNBAREB-26OCT21LALGSW-LALXX-5",
            "price_cents": 44,
            "count": 1,
            "tip_utc": "2026-10-22T02:00:00+00:00",
            "strategy_version": "nba-no-v5-one-contract-breadth",
        },
        {
            "event": "accepted",
            "utc": "2026-10-21T19:05:01+00:00",
            "client_order_id": "client-2",
            "order_id": "order-2",
        },
        {
            "event": "cancel_intent",
            "utc": "2026-10-21T20:00:00+00:00",
            "order_id": "order-2",
            "reason": "unverified_roster_injury_or_model",
            "veto": "OFFICIAL_TEAM_INJURY_CHANGE",
        },
        {
            "event": "settlement",
            "ticker": "KXNBAPTS-26OCT21LALGSW-LALLJAMES23-25",
            "utc": "2026-10-22T03:30:00+00:00",
            "revenue_dollars": 0.0,
            "yes_cost_dollars": 0.0,
            "no_cost_dollars": 0.56,
            "fee_dollars": 0.0,
            "net_profit_dollars": -0.56,
            "accounting_complete": True,
        },
        {
            "event": "settlement",
            "ticker": "KXNBAPTS-26OCT21LALGSW-LALLJAMES23-25",
            "utc": "2026-10-22T03:31:00+00:00",
            "revenue_dollars": 1.0,
            "yes_cost_dollars": 0.0,
            "no_cost_dollars": 0.56,
            "fee_dollars": 0.0,
            "net_profit_dollars": 0.44,
            "accounting_complete": True,
        },
    ]
    text = "".join(json.dumps(e) + "\n" for e in events)
    if partial_tail:
        text += '{"event": "intent", "utc": "2026-10'  # writer mid-line
    path.write_text(text)


def files_for(tmp_path, **kw):
    nba = tmp_path / "nba.jsonl"
    nba_journal(nba, **kw)
    return export.build_files({"nba": nba, "nfl": tmp_path / "missing.jsonl"}, NOW)


def test_orders_fills_and_settlements_join_correctly(tmp_path):
    files, summary = files_for(tmp_path)
    assert sorted(files) == [
        "README.md",
        "data/nba/fills/2026-10-21.csv",
        "data/nba/orders/2026-10-21.csv",
        "data/nba/settlements/2026-10-21.csv",  # 03:31 UTC = 11:31 PM Eastern
        "data/summary.json",
    ]
    orders = files["data/nba/orders/2026-10-21.csv"].splitlines()
    header = orders[0].split(",")
    first = dict(zip(header, orders[1].split(",")))
    assert first["status"] == "accepted"
    assert first["first_queue_ahead"] == "12" and first["last_queue_ahead"] == "3"
    assert first["filled_contracts"] == "1.0" and first["avg_fill_no_price"] == "0.56"
    assert first["minutes_before_tip"] == "420.0"
    assert first["settlement_net_profit_dollars"] == "0.44"  # the later correction
    second = dict(zip(header, orders[2].split(",")))
    assert second["cancel_veto"] == "OFFICIAL_TEAM_INJURY_CHANGE"
    assert second["filled_contracts"] == "0"
    fills = files["data/nba/fills/2026-10-21.csv"].splitlines()
    fill = dict(zip(fills[0].split(","), fills[1].split(",")))
    assert fill["order_ref"] == first["order_ref"]
    assert fill["markout_mid_15m"] == "0.02" and fill["markout_mid_5m"] == ""
    assert fill["minutes_before_tip"] == "300.0"
    assert summary["markets"]["nba"]["settled_net_profit_dollars"] == 0.44
    assert summary["markets"]["nfl"] == {"status": "journal_missing"}


def test_no_exchange_identifiers_or_unlisted_fields_leave_the_server(tmp_path):
    files, _ = files_for(tmp_path)
    text = "\n".join(files.values())
    for secret in (CLIENT, ORDER, FILL, "client-2", "order-2", "must not be exported"):
        assert secret not in text
    for name in ("order_id", "client_order_id", "fill_id", "balance"):
        assert not re.search(rf"(^|,){name}(,|$)", text, re.M)


def test_a_line_being_written_is_skipped_not_fatal(tmp_path):
    files, summary = files_for(tmp_path, partial_tail=True)
    assert summary["markets"]["nba"]["orders"] == 2


class FakeGitHub:
    def __init__(self, private=True, remote=None):
        self.private, self.remote, self.calls = private, remote or {}, []

    def __call__(self, method, path, token, payload=None):
        self.calls.append((method, path, payload))
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "head"}}
        if "/git/commits/" in path and method == "GET":
            return {"tree": {"sha": "tree0"}}
        if "/git/trees/" in path:
            return {
                "tree": [
                    {"path": p, "type": "blob", "sha": s}
                    for p, s in self.remote.items()
                ]
            }
        if path.endswith("/git/blobs"):
            return {"sha": f"blob{len(self.calls)}"}
        if path.endswith("/git/trees"):
            return {"sha": "tree1"}
        if path.endswith("/git/commits"):
            return {"sha": "commit1"}
        if method == "PATCH":
            return {}
        return {"private": self.private, "default_branch": "main"}


def test_push_sends_only_changed_files_in_one_commit():
    files = {"a.csv": "x\n", "b.csv": "y\n"}
    fake = FakeGitHub(remote={"a.csv": export.blob_sha("x\n")})
    assert export.push(files, "akilatrades/smm-private-data", "t" * 30, call=fake) == 1
    blobs = [c for c in fake.calls if c[1].endswith("/git/blobs")]
    assert len(blobs) == 1
    patch = [c for c in fake.calls if c[0] == "PATCH"]
    assert patch == [
        (
            "PATCH",
            "/repos/akilatrades/smm-private-data/git/refs/heads/main",
            {"sha": "commit1", "force": False},
        )
    ]
    unchanged = FakeGitHub(remote={p: export.blob_sha(t) for p, t in files.items()})
    assert (
        export.push(files, "akilatrades/smm-private-data", "t" * 30, call=unchanged)
        == 0
    )
    assert not [c for c in unchanged.calls if c[0] in ("POST", "PATCH")]


def test_blob_hash_matches_git():
    assert export.blob_sha("hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


@pytest.mark.parametrize(
    "repo, private, reason",
    [
        ("akilatrades/sports-market-maker", False, "refuse_public_project_repository"),
        ("AKILATRADES/Sports-Market-Maker", True, "refuse_public_project_repository"),
        ("akilatrades/smm-private-data", False, "refuse_repository_not_private"),
        ("not a repo", True, "private_export_repo_invalid"),
    ],
)
def test_push_refuses_anything_but_a_private_repo(repo, private, reason):
    fake = FakeGitHub(private=private)
    with pytest.raises(export.ExportError, match=reason):
        export.push({"a": "b"}, repo, "t" * 30, call=fake)
    assert not [c for c in fake.calls if c[0] in ("POST", "PATCH")]
    with pytest.raises(export.ExportError, match="token_not_configured"):
        export.push({"a": "b"}, "akilatrades/smm-private-data", "", call=fake)


def test_failures_print_a_reason_never_the_token(tmp_path, monkeypatch, capsys):
    nba_journal(tmp_path / "nba.jsonl")
    monkeypatch.setenv("PRIVATE_EXPORT_REPO", "akilatrades/smm-private-data")
    monkeypatch.setenv("PRIVATE_EXPORT_TOKEN", "ghp_" + "s" * 36)

    def unreachable(*args, **kwargs):
        raise export.ExportError("github_get_unreachable")

    monkeypatch.setattr(export, "github", unreachable)
    with pytest.raises(SystemExit):
        export.main(
            [
                "--push",
                "--nba-journal",
                str(tmp_path / "nba.jsonl"),
                "--nfl-journal",
                str(tmp_path / "x"),
            ]
        )
    out = capsys.readouterr()
    assert "github_get_unreachable" in out.err
    assert "ghp_" not in out.err + out.out


def test_counts_only_without_push(tmp_path, capsys):
    nba_journal(tmp_path / "nba.jsonl")
    export.main(
        [
            "--nba-journal",
            str(tmp_path / "nba.jsonl"),
            "--nfl-journal",
            str(tmp_path / "x"),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["counts"]["nba"]["orders"] == 2 and printed["files_changed"] is None
    assert (tmp_path / "out/data/nba/orders/2026-10-21.csv").exists()
    assert "LAL" not in json.dumps(printed)  # the log line carries counts only


def test_service_is_isolated_from_trading_and_kalshi():
    unit = (ROOT / "deploy/market-maker-private-export.service").read_text()
    assert "User=trader" in unit and "ProtectHome=read-only" in unit
    assert "EnvironmentFile=/etc/market-maker-private-export.env" in unit
    assert "prod-auto.env" not in unit and "nba-auto.env" not in unit  # no Kalshi key
    assert "tools.export_private_fills --push" in unit
    setup = (ROOT / "deploy/setup_private_export.sh").read_text()
    for funded in (
        "prod-nba-auto.timer",
        "prod-nfl-auto.timer",
        "prod-nba-auto.service",
    ):
        assert funded not in setup
