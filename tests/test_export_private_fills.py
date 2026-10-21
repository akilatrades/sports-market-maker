"""The private fills export: what it reads, what it writes, where it pushes."""

import json
import re
from pathlib import Path

import pytest

from tools import export_private_fills as export

ROOT = Path(__file__).resolve().parents[1]
CLIENT, ORDER, FILL = (
    "client-secret-uuid-1",
    "exchange-order-id-1",
    "exchange-fill-id-1",
)
TICKER = "KXNBAPTS-26OCT21LALGSW-LALLJAMES23-25"
REPO = "akilatrades/smm-private-data"
TOKEN = "t" * 30


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must never reach GitHub")

    monkeypatch.setattr(export, "urlopen", refuse)


NBA_EVENTS = [
    {
        "event": "intent",
        "utc": "2026-10-21T19:00:00+00:00",
        "client_order_id": CLIENT,
        "ticker": TICKER,
        "price_cents": 56,
        "count": 1,
        "cost": 0.56,
        "game_id": "401",
        "team": "LAL",
        "tip_utc": "2026-10-22T02:00:00+00:00",
        "strategy_version": "nba-no-v5-one-contract-breadth",
        "probability_source": "sportsbook",
        "p_yes": 0.38,
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
        "ticker": TICKER,
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
        "event": "cancel_accepted",
        "utc": "2026-10-21T20:00:01+00:00",
        "order_id": "order-2",
    },
    # A submission that was never confirmed, later reconciled as rejected.
    {
        "event": "intent",
        "utc": "2026-10-21T19:06:00+00:00",
        "client_order_id": "client-3",
        "ticker": "KXNBAAST-X",
        "price_cents": 40,
        "count": 1,
    },
    {
        "event": "unknown_outcome",
        "utc": "2026-10-21T19:06:01+00:00",
        "client_order_id": "client-3",
    },
    {
        "event": "reconciled_rejected",
        "utc": "2026-10-21T22:00:00+00:00",
        "client_order_id": "client-3",
    },
    # An accepted record without an order id must not collect other events.
    {
        "event": "accepted",
        "utc": "2026-10-21T19:07:00+00:00",
        "client_order_id": "client-4",
    },
    {"event": "queue", "utc": "2026-10-21T19:08:00+00:00", "ahead": 99},
    {
        "event": "settlement",
        "ticker": TICKER,
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
        "ticker": TICKER,
        "utc": "2026-10-22T03:31:00+00:00",
        "revenue_dollars": 1.0,
        "yes_cost_dollars": 0.0,
        "no_cost_dollars": 0.56,
        "fee_dollars": 0.0,
        "net_profit_dollars": 0.44,
        "accounting_complete": True,
    },
]
NFL_EVENTS = [
    {
        "event": "intent",
        "utc": "2026-10-25T16:00:00+00:00",
        "client_order_id": "nfl-client-1",
        "ticker": "KXNFLREC-X",
        "player": "Some Receiver",
        "price_cents": 60,
        "count": 1,
        "tip_utc": "2026-10-25T17:00:00+00:00",
        "strategy_version": "nfl-v2",
        "probability_source": "model",
        "p_yes_used": 0.35,
        "p_model_yes": 0.35,
        "model_made_utc": "2026-10-25T13:00:00+00:00",
        "edge_after_fee_buffer": 0.04,
        "fee_buffer_dollars": 0.06,
    }
]


def write(path, events, tail=""):
    path.write_text("".join(json.dumps(e) + "\n" for e in events) + tail)
    return path


def files_for(tmp_path, nba_tail=""):
    nba = write(tmp_path / "nba.jsonl", NBA_EVENTS, nba_tail)
    nfl = write(tmp_path / "nfl.jsonl", NFL_EVENTS)
    return export.build_files({"nba": nba, "nfl": nfl})


def rows(text):
    lines = text.splitlines()
    header = lines[0].split(",")
    return [dict(zip(header, line.split(","))) for line in lines[1:]]


def test_orders_fills_and_settlements_join_correctly(tmp_path):
    files, summary, complete = files_for(tmp_path)
    assert complete == {"nba", "nfl"}
    orders = {r["ticker"]: r for r in rows(files["data/nba/orders/2026-10-21.csv"])}
    first = orders[TICKER]
    assert first["status"] == "accepted"
    assert first["first_queue_ahead"] == "12" and first["last_queue_ahead"] == "3"
    assert first["filled_contracts"] == "1.0" and first["avg_fill_no_price"] == "0.56"
    assert first["minutes_before_tip"] == "420.0" and first["p_yes"] == "0.38"
    assert first["market_settlement_net_profit_dollars"] == "0.44"  # the correction
    second = orders["KXNBAREB-26OCT21LALGSW-LALXX-5"]
    assert second["cancel_veto"] == "OFFICIAL_TEAM_INJURY_CHANGE"
    assert second["cancel_requested_utc"].startswith("2026-10-21T20:00:00")
    assert second["cancel_confirmed_utc"].startswith("2026-10-21T20:00:01")
    assert second["filled_contracts"] == "0" and second["avg_fill_no_price"] == ""
    assert orders["KXNBAAST-X"]["status"] == "reconciled_rejected"
    fill = rows(files["data/nba/fills/2026-10-21.csv"])[0]
    assert fill["order_ref"] == first["order_ref"]
    assert fill["markout_mid_15m"] == "0.02" and fill["markout_mid_5m"] == ""
    assert fill["minutes_before_tip"] == "300.0"
    settled = rows(files["data/nba/settlements/2026-10-21.csv"])  # 11:31 PM ET
    assert len(settled) == 1 and settled[0]["net_profit_dollars"] == "0.44"
    nba = summary["markets"]["nba"]
    assert nba["settled_net_profit_dollars"] == 0.44
    assert nba["data_through_utc"] == "2026-10-22T03:31:00+00:00"


def test_nfl_rows_keep_their_own_probability_fields(tmp_path):
    files, _, _ = files_for(tmp_path)
    order = rows(files["data/nfl/orders/2026-10-25.csv"])[0]
    assert order["p_yes_used"] == "0.35" and order["p_model_yes"] == "0.35"
    assert order["edge_after_fee_buffer"] == "0.04"
    assert order["model_made_utc"].startswith("2026-10-25T13:00")
    assert order["player"] == "Some Receiver"


def test_no_exchange_identifiers_or_unlisted_fields_leave_the_server(tmp_path):
    files, _, _ = files_for(tmp_path)
    text = "\n".join(files.values())
    for secret in (CLIENT, ORDER, FILL, "client-2", "order-2", "must not be exported"):
        assert secret not in text
    columns = set(
        export.ORDER_COLUMNS + export.FILL_COLUMNS + export.SETTLEMENT_COLUMNS
    )
    risky = re.compile(
        r"(^|_)(id|token|key|secret|balance|account|password|member)($|_)"
    )
    assert sorted(c for c in columns if risky.search(c)) == ["game_id"]


def test_bad_lines_are_skipped_and_a_line_being_written_waits(tmp_path):
    nba = tmp_path / "nba.jsonl"
    write(
        nba,
        NBA_EVENTS[:2],
        tail='not json\n[1, 2]\nnull\n   \n{"event": "intent", "utc',
    )
    files, summary, _ = export.build_files({"nba": nba})
    assert summary["markets"]["nba"]["orders"] == 1
    assert summary["markets"]["nba"]["skipped_lines"] == 3


def test_one_unreadable_journal_does_not_stop_the_other(tmp_path, monkeypatch):
    nba = write(tmp_path / "nba.jsonl", NBA_EVENTS)
    nfl = write(tmp_path / "nfl.jsonl", NFL_EVENTS)
    real = export.tables

    def flaky(market, stream):
        if market == "nfl":
            raise MemoryError
        return real(market, stream)

    monkeypatch.setattr(export, "tables", flaky)
    files, summary, complete = export.build_files(
        {"nba": nba, "nfl": nfl, "x": tmp_path / "missing"}
    )
    assert complete == {"nba"}
    assert summary["markets"]["nfl"] == {"status": "error_MemoryError"}
    assert summary["markets"]["x"] == {"status": "journal_missing"}
    assert not [p for p in files if p.startswith("data/nfl/")]


class FakeGitHub:
    """Enough of GitHub's Git Data API, with state, to commit twice."""

    def __init__(self, info=None, remote=None, branch="main", truncated=False):
        self.info = {
            "full_name": REPO,
            "private": True,
            "visibility": "private",
            "default_branch": branch,
            **(info or {}),
        }
        self.remote, self.branch, self.truncated = dict(remote or {}), branch, truncated
        self.calls, self.pending = [], None

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH")]

    def __call__(self, method, path, token, payload=None):
        self.calls.append((method, path, payload))
        if path == f"/repos/{REPO}":
            return self.info
        if path.endswith(f"/git/ref/heads/{self.branch}"):
            return {"object": {"sha": "head"}}
        if "/git/commits/" in path:
            return {"tree": {"sha": "tree0"}}
        if "/git/trees/" in path:
            tree = [
                {"path": p, "type": "blob", "sha": s} for p, s in self.remote.items()
            ]
            return {"tree": tree, "truncated": self.truncated}
        if path.endswith("/git/trees"):
            new = dict(self.remote)
            for entry in payload["tree"]:
                if entry.get("sha", "x") is None:
                    new.pop(entry["path"], None)
                else:
                    new[entry["path"]] = export.blob_sha(entry["content"])
            self.pending = new
            return {"sha": "tree1"}
        if path.endswith("/git/commits"):
            return {"sha": "commit1"}
        if method == "PATCH":
            assert path.endswith(f"/git/refs/heads/{self.branch}")
            assert payload == {"sha": "commit1", "force": False}
            self.remote = self.pending
            return {}
        raise AssertionError(path)


def test_build_then_push_twice_commits_once(tmp_path):
    files, _, complete = files_for(tmp_path)
    fake = FakeGitHub(branch="trunk")
    changed, removed = export.push(files, REPO, TOKEN, complete, call=fake)
    assert changed == len(files) and removed == 0
    assert (
        len([c for c in fake.calls if c[1].endswith("/git/trees")]) == 1
    )  # one request
    fake.calls.clear()
    again, _, complete = files_for(tmp_path)  # same journals, later clock
    assert export.push(again, REPO, TOKEN, complete, call=fake) == (0, 0)
    assert fake.writes() == []


def test_files_no_longer_produced_are_removed_carefully(tmp_path):
    files, _, complete = files_for(tmp_path)
    known = {p: export.blob_sha(t) for p, t in files.items()}
    stale = {
        "data/nba/settlements/undated.csv": "x",
        "data/nfl/orders/2026-01-01.csv": "y",
        "notes.md": "z",
    }
    fake = FakeGitHub(remote={**known, **stale})
    assert export.push(files, REPO, TOKEN, {"nba"}, call=fake) == (0, 1)
    assert "data/nba/settlements/undated.csv" not in fake.remote
    assert "data/nfl/orders/2026-01-01.csv" in fake.remote  # NFL not read this run
    assert "notes.md" in fake.remote
    # A run that would remove most of a market's files removes nothing.
    many = {f"data/nba/fills/2025-01-{d:02d}.csv": "x" for d in range(1, 29)}
    fake = FakeGitHub(remote={**known, **many})
    assert export.push(files, REPO, TOKEN, {"nba"}, call=fake) == (0, 0)


def test_blob_hash_matches_git():
    assert export.blob_sha("hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


@pytest.mark.parametrize(
    "repo, info, reason",
    [
        ("akilatrades/sports-market-maker", {}, "refuse_public_project_repository"),
        ("AKILATRADES/Sports-Market-Maker", {}, "refuse_public_project_repository"),
        (REPO, {"private": False}, "refuse_repository_not_private"),
        (REPO, {"visibility": "internal"}, "refuse_repository_not_private"),
        (REPO, {"full_name": "someone/else"}, "refuse_repository_name_mismatch"),
        (REPO, {"has_pages": True}, "refuse_repository_has_pages"),
        (REPO, {"archived": True}, "refuse_repository_archived"),
        ("not a repo", {}, "private_export_repo_invalid"),
    ],
)
def test_push_refuses_anything_but_a_private_repo(repo, info, reason):
    fake = FakeGitHub(info=info)
    with pytest.raises(export.ExportError, match=reason):
        export.push({"a": "b"}, repo, TOKEN, call=fake)
    assert fake.writes() == []


def test_push_refuses_without_token_or_with_a_truncated_listing():
    with pytest.raises(export.ExportError, match="token_not_configured"):
        export.push({"a": "b"}, REPO, "", call=FakeGitHub())
    fake = FakeGitHub(truncated=True)
    with pytest.raises(export.ExportError, match="truncated"):
        export.push({"a": "b"}, REPO, TOKEN, call=fake)
    assert fake.writes() == []


def test_redirects_are_refused_so_the_token_cannot_follow_them():
    handler = export._NoRedirect()
    with pytest.raises(export.ExportError, match="redirect_refused_301"):
        handler.redirect_request(None, None, 301, "Moved", {}, "https://evil.example/")


def test_failures_print_a_reason_never_the_token(tmp_path, monkeypatch, capsys):
    write(tmp_path / "nba.jsonl", NBA_EVENTS)
    secret = "ghp_" + "s" * 36
    monkeypatch.setenv("PRIVATE_EXPORT_REPO", REPO)
    monkeypatch.setenv("PRIVATE_EXPORT_TOKEN", secret)
    args = [
        "--push",
        "--nba-journal",
        str(tmp_path / "nba.jsonl"),
        "--nfl-journal",
        "x",
    ]

    def unreachable(*a, **k):
        raise export.ExportError("github_get_unreachable")

    monkeypatch.setattr(export, "github", unreachable)
    with pytest.raises(SystemExit):
        export.main(args)
    out = capsys.readouterr()
    assert "github_get_unreachable" in out.err and secret not in out.err + out.out

    def leaky(*a, **k):
        raise ValueError(f"something with {secret} inside")

    monkeypatch.setattr(export, "github", leaky)
    with pytest.raises(SystemExit):
        export.main(args)
    out = capsys.readouterr()
    assert "ValueError" in out.err and secret not in out.err + out.out


def test_counts_only_without_push_and_never_into_a_git_checkout(tmp_path, capsys):
    write(tmp_path / "nba.jsonl", NBA_EVENTS)
    base = ["--nba-journal", str(tmp_path / "nba.jsonl"), "--nfl-journal", "x"]
    export.main([*base, "--out", str(tmp_path / "out")])
    printed = json.loads(capsys.readouterr().out)
    assert (
        printed["counts"]["nba"]["orders"] == 3 and printed["changed_removed"] is None
    )
    assert (tmp_path / "out/data/nba/orders/2026-10-21.csv").exists()
    assert "LAL" not in json.dumps(printed)  # the log line carries counts only
    (tmp_path / "repo/.git").mkdir(parents=True)
    with pytest.raises(SystemExit):
        export.main([*base, "--out", str(tmp_path / "repo/sub")])
    assert "refuse_out_inside_git_checkout" in capsys.readouterr().err


def test_service_is_isolated_from_trading_and_kalshi():
    unit = (ROOT / "deploy/market-maker-private-export.service").read_text()
    for line in (
        "User=trader",
        "ProtectHome=read-only",
        "EnvironmentFile=/etc/market-maker-private-export.env",
        "MemoryMax=192M",
        "OOMScoreAdjust=1000",
        "IOSchedulingClass=idle",
    ):
        assert line in unit
    assert "prod-auto.env" not in unit and "nba-auto.env" not in unit  # no Kalshi key
    assert "tools.export_private_fills --push" in unit
    setup = (ROOT / "deploy/setup_private_export.sh").read_text()
    assert "FETCH_HEAD:deploy/" in setup  # units come from GitHub main
    for funded in (
        "prod-nba-auto.timer",
        "prod-nfl-auto.timer",
        "prod-nba-auto.service",
    ):
        assert funded not in setup
