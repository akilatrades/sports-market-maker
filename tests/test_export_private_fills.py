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
    """Enough of GitHub's Git Data API, with state, to commit repeatedly."""

    def __init__(self, info=None, remote=None, branch="main", truncated=False):
        self.info = {
            "full_name": REPO,
            "private": True,
            "visibility": "private",
            "default_branch": branch,
            **(info or {}),
        }
        self.text = dict(remote or {})  # path -> content
        self.branch, self.truncated = branch, truncated
        self.calls, self.head, self.trees, self.n = [], "c0", {}, 0

    @property
    def remote(self):
        return self.text

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH")]

    def commits(self):
        return [c for c in self.calls if c[1].endswith("/git/commits")]

    def __call__(self, method, path, token, payload=None):
        import base64

        self.calls.append((method, path, payload))
        if path == f"/repos/{REPO}":
            return self.info
        if path.endswith(f"/git/ref/heads/{self.branch}"):
            return {"object": {"sha": self.head}}
        if "/git/commits/" in path:
            return {"tree": {"sha": "t-" + self.head}}
        if "/git/trees/" in path:
            tree = [
                {"path": p, "type": "blob", "sha": export.blob_sha(s)}
                for p, s in self.text.items()
            ]
            return {"tree": tree, "truncated": self.truncated}
        if "/git/blobs/" in path:
            sha = path.rsplit("/", 1)[1]
            text = next(s for s in self.text.values() if export.blob_sha(s) == sha)
            return {"content": base64.b64encode(text.encode()).decode()}
        self.n += 1
        if path.endswith("/git/trees"):
            new = dict(self.trees.get(payload["base_tree"], self.text))
            for entry in payload["tree"]:
                if entry.get("sha", "x") is None:
                    new.pop(entry["path"], None)
                else:
                    new[entry["path"]] = entry["content"]
            self.trees[f"tree{self.n}"] = new
            return {"sha": f"tree{self.n}"}
        if path.endswith("/git/commits"):
            assert payload["parents"] == [self.head]
            self.trees[f"commit{self.n}"] = self.trees[payload["tree"]]
            return {"sha": f"commit{self.n}"}
        if method == "PATCH":
            assert path.endswith(f"/git/refs/heads/{self.branch}")
            assert payload["force"] is False
            self.head, self.text = payload["sha"], self.trees[payload["sha"]]
            self.trees["t-" + self.head] = self.text
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
    known = dict(files)
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
    monkeypatch.setattr(
        export,
        "JOURNALS",
        {
            "nba": tmp_path / "nba.jsonl",
            "nfl": tmp_path / "x",
            "spread": tmp_path / "y",
        },
    )
    monkeypatch.setattr(export, "SPREAD_SHADOW", tmp_path / "z")
    args = ["--push"]

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


def test_a_journal_that_went_backwards_pushes_nothing(tmp_path):
    files, _, complete = files_for(tmp_path)
    fake = FakeGitHub()
    export.push(files, REPO, TOKEN, complete, call=fake)
    shorter = write(tmp_path / "nba.jsonl", NBA_EVENTS[:2])  # a restored journal
    files, _, complete = export.build_files(
        {"nba": shorter, "nfl": tmp_path / "nfl.jsonl"}
    )
    fake.calls.clear()
    with pytest.raises(export.ExportError, match="went_backwards_nba"):
        export.push(files, REPO, TOKEN, complete, call=fake)
    assert fake.writes() == []


def test_a_huge_upload_is_split_into_saved_commits(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "BATCH_BYTES", 600)
    files = {f"data/nba/orders/2026-10-{d:02d}.csv": "x" * 400 for d in range(1, 6)}
    fake = FakeGitHub()
    assert export.push(files, REPO, TOKEN, {"nba"}, call=fake) == (5, 0)
    assert len(fake.commits()) == 5  # each saved before the next
    assert fake.remote == files


def test_small_markets_can_lose_up_to_two_stale_files():
    fake = FakeGitHub(remote={"data/nba/a.csv": "1", "data/nba/b.csv": "2"})
    assert export.push({"data/nba/c.csv": "3"}, REPO, TOKEN, {"nba"}, call=fake) == (
        1,
        2,
    )
    assert sorted(fake.remote) == ["data/nba/c.csv"]


def test_a_stray_carriage_return_does_not_hide_the_rest(tmp_path):
    nba = tmp_path / "nba.jsonl"
    nba.write_text(
        json.dumps(NBA_EVENTS[0])
        + "\n"
        + '{"event": "queue", "x": "a\rb"}\n'
        + "".join(json.dumps(e) + "\n" for e in NBA_EVENTS[1:])
    )
    _, summary, _ = export.build_files({"nba": nba})
    assert summary["markets"]["nba"]["orders"] == 3


def test_odd_event_values_are_skipped_not_fatal(tmp_path):
    nba = write(tmp_path / "nba.jsonl", [{"event": ["intent"]}, *NBA_EVENTS])
    _, summary, complete = export.build_files({"nba": nba})
    assert complete == {"nba"} and summary["markets"]["nba"]["orders"] == 3


def test_push_refuses_other_journals(tmp_path, capsys):
    write(tmp_path / "nba.jsonl", NBA_EVENTS)
    with pytest.raises(SystemExit):
        export.main(["--push", "--nba-journal", str(tmp_path / "nba.jsonl")])
    assert "refuse_push_with_other_journals" in capsys.readouterr().err


def test_the_real_opener_refuses_a_redirect():
    """A local HTTP server answers 301 to another host; nothing follows it."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(301)
            self.send_header("Location", "http://127.0.0.1:9/steal")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.handle_request, daemon=True).start()
    request = export.Request(
        f"http://127.0.0.1:{server.server_port}/repo",
        headers={"Authorization": "Bearer t"},
    )
    with pytest.raises(export.ExportError, match="redirect_refused_301"):
        export._OPENER.open(request, timeout=5)
    server.server_close()
    assert seen == ["Bearer t"]  # one request, to the original host only


# --- the spread maker ---------------------------------------------------------

SPREAD_TICKER = "KXDOTA2GAME-26OCT22AB-A"


def _spread_order(key, side, cents, utc, accepted=True):
    events = [
        {
            "event": "intent",
            "utc": utc,
            "client_order_id": f"smm-spread-{key}",
            "ticker": SPREAD_TICKER,
            "series": "KXDOTA2GAME",
            "event_ticker": "KXDOTA2GAME-26OCT22AB",
            "side": side,
            "price_cents": cents,
            "count": 5,
            "cost": round(5 * cents / 100, 2),
            "spread": 12,
            "market_expiration_utc": "2026-10-22T23:00:00+00:00",
            "event_start_utc": "2026-10-22T20:00:00+00:00",
            "strategy_version": "spread-maker-v2-pregame",
        }
    ]
    if accepted:
        events.append(
            {
                "event": "accepted",
                "utc": utc,
                "client_order_id": f"smm-spread-{key}",
                "order_id": f"exchange-spread-{key}",
            }
        )
    return events


def _spread_fill(key, side, cents, utc, count="5.00"):
    yes = cents if side == "yes" else 100 - cents
    return {
        "event": "fill",
        "fill_id": f"exchange-fill-{key}",
        "order_id": f"exchange-spread-{key}",
        "utc": utc,
        "created_time": utc,
        "ticker": SPREAD_TICKER,
        "outcome_side": side,
        "book_side": "bid" if side == "yes" else "ask",
        "count_fp": count,
        "yes_price_dollars": f"{yes / 100:.4f}",
        "no_price_dollars": f"{(100 - yes) / 100:.4f}",
        "fee_cost": "0.00",
        "is_taker": False,
    }


SPREAD_EVENTS = [
    *_spread_order("a", "yes", 41, "2026-10-22T18:00:00+00:00"),
    *_spread_order("b", "no", 49, "2026-10-22T18:00:01+00:00"),
    *_spread_order("c", "yes", 42, "2026-10-22T18:10:00+00:00", accepted=False),
    {
        "event": "rejected_4xx",
        "utc": "2026-10-22T18:10:01+00:00",
        "client_order_id": "smm-spread-c",
        "http_status": 400,
        "evidence": "http_4xx_and_signed_get_absent",
    },
    _spread_fill("a", "yes", 41, "2026-10-22T18:20:00+00:00"),
    _spread_fill("b", "no", 49, "2026-10-22T18:30:00+00:00"),
    {
        "event": "cancel_intent",
        "utc": "2026-10-22T18:40:00+00:00",
        "order_id": "exchange-spread-b",
        "ticker": SPREAD_TICKER,
        "reason": "requote",
    },
    {
        "event": "cancel_moot",
        "utc": "2026-10-22T18:40:01+00:00",
        "order_id": "exchange-spread-b",
    },
    {
        "event": "settlement",
        "ticker": SPREAD_TICKER,
        "utc": "2026-10-23T01:00:00+00:00",
        "market_result": "yes",
        "revenue_dollars": 0.0,
    },
]
SHADOW_EVENTS = [
    {"event": "shadow_quote", "id": "q1", "ticker": SPREAD_TICKER, "side": "yes",
     "price_cents": 41, "contracts": 5},
    {"event": "shadow_quote", "id": "q2", "ticker": SPREAD_TICKER, "side": "no",
     "price_cents": 49, "contracts": 5},
    {"event": "shadow_fill", "id": "q1", "through": 8.0},
    {"event": "shadow_fill", "id": "q2", "through": 0.0},
    {"event": "shadow_result", "ticker": SPREAD_TICKER, "result": "yes"},
]  # fmt: skip


def spread_files(tmp_path):
    journals = {
        "nba": write(tmp_path / "nba.jsonl", NBA_EVENTS),
        "nfl": write(tmp_path / "nfl.jsonl", NFL_EVENTS),
        "spread": write(tmp_path / "spread.jsonl", SPREAD_EVENTS),
    }
    shadow = write(tmp_path / "shadow.jsonl", SHADOW_EVENTS)
    return export.build_files(journals, shadow=shadow)


def test_spread_orders_fills_and_realized_pnl(tmp_path):
    files, summary, complete = spread_files(tmp_path)
    assert "spread" in complete
    orders = rows(files["data/spread/orders/2026-10-22.csv"])
    by_side = {(o["side"], o["status"]) for o in orders}
    assert by_side == {("yes", "accepted"), ("no", "accepted"), ("yes", "refused_4xx")}
    no = next(o for o in orders if o["side"] == "no")
    assert no["cancel_result"] == "already_filled_or_expired"
    assert no["filled_contracts"] == "5.0" and no["avg_fill_price"] == "0.49"
    # v2 records the start each order respected.
    assert {o["event_start_utc"] for o in orders} == {"2026-10-22T20:00:00+00:00"}
    assert all(float(o["minutes_before_start"]) > 0 for o in orders)
    fills = rows(files["data/spread/fills/2026-10-22.csv"])
    assert {(f["side"], f["price"]) for f in fills} == {
        ("yes", "0.4100"),
        ("no", "0.4900"),
    }
    pnl = rows(files["data/spread/pnl_by_day.csv"])
    # Five YES at 41c and five NO at 49c: five pairs, each $1 - 90c.
    assert pnl == [
        {"market": "spread", "day": "2026-10-22", "realized_pnl_dollars": "0.5",
         "cumulative_dollars": "0.5"}
    ]  # fmt: skip
    s = summary["markets"]["spread"]
    assert s["realized_pnl_dollars"] == 0.5 and s["filled_contracts"] == 10
    assert s["never_placed_orders"] == 1 and s["markets_still_held"] == 0
    assert (
        rows(files["data/spread/settlements/2026-10-22.csv"])[0]["market_result"]
        == "yes"
    )


def test_spread_shadow_is_reported_apart_and_labelled_simulated(tmp_path):
    files, summary, _ = spread_files(tmp_path)
    shadow = summary["spread_shadow_simulated"]
    assert shadow["note"].startswith("SIMULATED")
    assert shadow["first_in_line"] == {
        "contracts": 5,
        "dollars": 2.95,
        "cents_per_contract": 59.0,
    }
    assert shadow["flow_share_0.25"]["contracts"] < 5
    # Live realized P&L is not changed by the simulated ledger.
    assert summary["markets"]["spread"]["realized_pnl_dollars"] == 0.5
    assert "spread_shadow_simulated" in json.loads(files["data/summary.json"])


def test_spread_export_never_contains_exchange_ids(tmp_path):
    files, _, _ = spread_files(tmp_path)
    text = "".join(files.values())
    for raw in ("exchange-spread-a", "exchange-fill-a", "smm-spread-a"):
        assert raw not in text


def test_a_missing_spread_journal_leaves_other_bots_alone(tmp_path):
    journals = {
        "nba": write(tmp_path / "nba.jsonl", NBA_EVENTS),
        "nfl": write(tmp_path / "nfl.jsonl", NFL_EVENTS),
        "spread": tmp_path / "absent.jsonl",
    }
    files, summary, complete = export.build_files(journals, shadow=tmp_path / "none")
    assert summary["markets"]["spread"] == {"status": "journal_missing"}
    assert "spread" not in complete and "spread_shadow_simulated" not in summary
    assert summary["markets"]["nba"]["status"] == "ok"


def test_live_fill_share_joins_scored_windows_with_live_fills(tmp_path):
    journals = {
        "nba": write(tmp_path / "nba.jsonl", NBA_EVENTS),
        "nfl": write(tmp_path / "nfl.jsonl", NFL_EVENTS),
        "spread": write(tmp_path / "spread.jsonl", SPREAD_EVENTS),
    }
    windows = [
        # YES order: 8 traded through, all 5 of ours filled -> 5 of 5.
        {
            "event": "live_window",
            "client_order_id": "smm-spread-a",
            "size": 5,
            "through": 8,
        },
        # NO order: 20 traded through, all 5 of ours filled -> 5 of 5.
        {
            "event": "live_window",
            "client_order_id": "smm-spread-b",
            "size": 5,
            "through": 20,
        },
    ]
    shadow = write(tmp_path / "shadow.jsonl", SHADOW_EVENTS + windows)
    _, summary, _ = export.build_files(journals, shadow=shadow)
    share = summary["markets"]["spread"]["live_fill_share"]
    assert share["fill_share"] == 1.0 and share["first_in_line_contracts"] == 10
    assert share["orders_filled_when_traded_through"] == 2
    # The cautious replay (flow share 0.25) on the same windows, scored with
    # the bot's own rule.
    from live.prod_spread_auto import expected_fill

    cautious = expected_fill(8, 0.25, 5) + expected_fill(20, 0.25, 5)
    assert share["cautious_replay_share"] == round(cautious / 10, 3)
    windows[1]["through"] = 0  # nothing reached the NO price: no capacity there
    shadow = write(tmp_path / "shadow.jsonl", SHADOW_EVENTS + windows)
    _, summary, _ = export.build_files(journals, shadow=shadow)
    assert (
        summary["markets"]["spread"]["live_fill_share"]["first_in_line_contracts"] == 5
    )


def test_spread_queue_and_markouts_are_exported_by_reference(tmp_path):
    journals = {
        "nba": write(tmp_path / "nba.jsonl", NBA_EVENTS),
        "nfl": write(tmp_path / "nfl.jsonl", NFL_EVENTS),
        "spread": write(tmp_path / "spread.jsonl", SPREAD_EVENTS),
    }
    shadow = write(tmp_path / "shadow.jsonl", SHADOW_EVENTS)
    measured = [
        {"event": "queue", "client_order_id": "smm-spread-a", "ahead": 0.0,
         "outbid": False, "utc": "2026-10-22T20:10:00+00:00"},
        {"event": "queue", "client_order_id": "smm-spread-a", "ahead": 4.0,
         "outbid": True, "utc": "2026-10-22T20:20:00+00:00"},
        {"event": "markout", "fill_id": "exchange-fill-a", "client_order_id": "smm-spread-a",
         "horizon_minutes": 10, "adverse_move_cents": -2.5, "realized_spread_cents": 2.5},
        {"event": "markout", "fill_id": "exchange-fill-a", "client_order_id": "smm-spread-a",
         "horizon_minutes": 30, "adverse_move_cents": None, "issue": "quote_unavailable"},
    ]  # fmt: skip
    path = write(tmp_path / "measurements.jsonl", measured, tail='{"eve')  # torn line
    assert path.name == "measurements.jsonl"
    bot_summary = {"rules": "spread-maker-v2-pregame", "orders_with_queue_reading": 1}
    (tmp_path / "measurements_summary.json").write_text(json.dumps(bot_summary))
    files, summary, _ = export.build_files(journals, shadow=shadow)
    orders = rows(files["data/spread/orders/2026-10-22.csv"])
    a = next(o for o in orders if o["order_ref"] == export.ref("smm-spread-a"))
    assert (a["first_queue_ahead"], a["last_queue_ahead"]) == ("0.0", "4.0")
    assert a["outbid_at_first_reading"] == "False"
    fills = rows(files["data/spread/fills/2026-10-22.csv"])
    f = next(x for x in fills if x["fill_ref"] == export.ref("exchange-fill-a"))
    assert f["markout_10m_cents"] == "-2.5" and f["markout_30m_cents"] == ""
    # The summary is the bot's own, copied as written.
    assert summary["markets"]["spread"]["queue_and_markouts"] == bot_summary
    # Exchange ids never reach the export.
    assert "exchange-spread-a" not in "".join(files.values())
