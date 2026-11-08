"""Owner-run NBA reconcile (2026-11-08): an NBA order with an unknown outcome
halted all three bots, and only the 20 October incident scripts could resolve
one. ``live.prod_nba_auto --reconcile`` does it with signed reads only."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kalshi.trading import TradingError
from live import prod_nba_auto as nba
from live import shared_account_risk as shared
from live.reconciled_attempts import (
    ABSENT_EVIDENCE,
    FOUND_MARK,
    reconciled_found_ids,
    rejected_client_ids,
)
from tools.production_status import journal_summary

NOW = datetime(2026, 11, 8, 14, 0, tzinfo=UTC)
TICKER = "KXNBAPTS-26NOV07LALSAC-LAL-25"
OTHER = "KXNBAREB-26NOV07LALSAC-SAC-10"
CID = "smm-unknown"


def intent(cid, ticker, placed, tip):
    return {
        "event": "intent",
        "utc": placed.isoformat(),
        "client_order_id": cid,
        "ticker": ticker,
        "cost": 0.8,
        "count": 1,
        "price_cents": 80,
        "tip_utc": tip.isoformat(),
        "expiration_ts": int(tip.timestamp()),
    }


def journal(tmp_path, tip=NOW - timedelta(hours=12)):
    placed = NOW - timedelta(hours=15)
    events = [
        intent("smm-earlier", OTHER, placed - timedelta(minutes=10), tip),
        {
            "event": "accepted",
            "utc": placed.isoformat(),
            "client_order_id": "smm-earlier",
            "order_id": "order-earlier",
        },
        intent(CID, TICKER, placed, tip),
        {"event": "unknown_outcome", "utc": placed.isoformat(), "client_order_id": CID},
    ]
    path = tmp_path / "journal.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


class Client:
    """Signed reads only: any write attribute is missing, so using one fails."""

    def __init__(self, orders=(), fills=(), positions=()):
        self.rows = list(orders)
        self.fill_rows = list(fills)
        self.position_rows = list(positions)
        self.calls = []

    def orders(self, status="resting", ticker=None):
        self.calls.append(("orders", status, ticker))
        return [
            o
            for o in self.rows
            if status in (None, o.get("status")) and ticker in (None, o.get("ticker"))
        ]

    def fills(self, min_ts=None, ticker=None):
        self.calls.append(("fills", min_ts, ticker))
        return [f for f in self.fill_rows if ticker in (None, f.get("ticker"))]

    def positions(self):
        self.calls.append(("positions",))
        return self.position_rows


@pytest.fixture(autouse=True)
def journals_only(monkeypatch):
    """The shared check with its journal logic, on this test's NBA journal."""
    state = {}

    def state_for(client, sport, now):
        events = {"nfl": [], "nba": nba.load_journal(state["path"]), "spread": None}
        shared.ownership(events)
        return {}, {}

    monkeypatch.setattr(shared, "dual_mode", lambda env: True)
    monkeypatch.setattr(shared, "state_for", state_for)
    return state


def run(path, client, journals_only, now=NOW):
    journals_only["path"] = path
    return nba.reconcile(client, path, now)


def test_found_order_is_recorded_as_placed_and_trading_resumes(tmp_path, journals_only):
    path = journal(tmp_path)
    found = {
        "status": "canceled",
        "ticker": TICKER,
        "client_order_id": CID,
        "order_id": "order-found",
    }
    client = Client(orders=[found])
    before = nba.load_journal(path)
    with pytest.raises(TradingError, match="Ambiguous production order"):
        shared.ownership({"nfl": [], "nba": before, "spread": None})

    summary = run(path, client, journals_only)

    assert summary == {"found_on_exchange": 1, "bots_can_trade": True}
    added = nba.load_journal(path)[len(before) :]
    assert added == [
        {
            "event": "accepted",
            "utc": NOW.isoformat(),
            "client_order_id": CID,
            "order_id": "order-found",
            "reconciled": FOUND_MARK,
        }
    ]
    attempts, accepted = nba.records(nba.load_journal(path))
    assert accepted[CID]["order_id"] == "order-found"
    # A second run finds nothing left to do and writes nothing.
    assert run(path, Client(orders=[found]), journals_only) == {"bots_can_trade": True}
    assert len(nba.load_journal(path)) == len(before) + 1


def test_absent_order_after_tip_off_is_recorded_as_never_placed(
    tmp_path, journals_only
):
    path = journal(tmp_path)
    client = Client()

    summary = run(path, client, journals_only)

    assert summary == {"never_placed": 1, "bots_can_trade": True}
    events = nba.load_journal(path)
    assert events[-1]["event"] == "reconciled_rejected"
    assert events[-1]["evidence"] == ABSENT_EVIDENCE
    assert events[-1]["intent_age_seconds"] == 15 * 3600
    assert rejected_client_ids(events) == {CID}
    # Its own market in every status (one unfiltered list first), then its
    # fills and positions.
    assert [c for c in client.calls if c[0] == "orders"] == [
        ("orders", s, TICKER) for s in (None, "resting", "executed", "canceled")
    ]
    assert ("fills", (NOW - timedelta(hours=15)).timestamp() - 60, TICKER) in (
        client.calls
    )
    # The attempt still counts: it stays in the journal's intents.
    attempts, _ = nba.records(events)
    assert CID in {a["client_order_id"] for a in attempts}


def test_absent_order_before_tip_off_waits(tmp_path, journals_only):
    path = journal(tmp_path, tip=NOW + timedelta(hours=1))
    before = path.read_text()

    summary = run(path, Client(), journals_only)

    assert summary["too_recent_try_again_after_tip_off"] == 1
    assert summary["bots_can_trade"] is False
    assert "reconcile" in summary["still_blocked_by"]
    assert path.read_text() == before


def test_unexplained_fill_or_open_position_writes_nothing(tmp_path, journals_only):
    path = journal(tmp_path)
    before = path.read_text()
    mystery = {"ticker": TICKER, "order_id": "order-mystery", "count": 1}
    summary = run(path, Client(fills=[mystery]), journals_only)
    assert summary["unexplained_fill_check_by_hand"] == 1
    held = {"market_ticker": TICKER, "position_fp": "-1.00"}
    summary = run(path, Client(positions=[held]), journals_only)
    assert summary["position_open_try_again_after_settlement"] == 1
    assert summary["bots_can_trade"] is False
    assert path.read_text() == before
    # A fill from an order the journal already owns is explained.
    known = {"ticker": TICKER, "order_id": "order-earlier", "count": 1}
    assert run(path, Client(fills=[known]), journals_only)["never_placed"] == 1


def test_found_order_with_an_id_already_in_the_journal_is_left_alone(
    tmp_path, journals_only
):
    path = journal(tmp_path)
    before = path.read_text()
    clash = {
        "status": "executed",
        "ticker": TICKER,
        "client_order_id": CID,
        "order_id": "order-earlier",
    }
    summary = run(path, Client(orders=[clash]), journals_only)
    assert summary["found_but_unclear_check_by_hand"] == 1
    assert summary["bots_can_trade"] is False
    assert path.read_text() == before


def test_resolutions_are_strict():
    """Checked from the events' own times, never from what the resolution
    says about itself (independent review, 2026-11-08)."""
    placed = NOW - timedelta(hours=1)
    base = [
        intent(CID, TICKER, placed, NOW - timedelta(minutes=5)),
        {"event": "unknown_outcome", "client_order_id": CID},
    ]
    good = {
        "event": "reconciled_rejected",
        "utc": NOW.isoformat(),
        "client_order_id": CID,
        "evidence": ABSENT_EVIDENCE,
        "intent_age_seconds": 3600,
        "after_expiry": True,
    }
    assert rejected_client_ids(base + [good]) == {CID}
    no_expiry = [{**base[0], "expiration_ts": None}, base[1]]
    naive = [{**base[0], "utc": placed.replace(tzinfo=None).isoformat()}, base[1]]
    for events in (
        # Written before tip-off, or under 10 minutes after the intent, even
        # if it claims otherwise.
        base + [{**good, "utc": (NOW - timedelta(minutes=6)).isoformat()}],
        base + [{**good, "utc": (placed + timedelta(minutes=9)).isoformat()}],
        # Over 7 days after the intent.
        base + [{**good, "utc": (placed + timedelta(days=7, seconds=1)).isoformat()}],
        base + [{k: v for k, v in good.items() if k != "after_expiry"}],
        base + [{**good, "evidence": "owner_said_so"}],
        base + [{**good, "utc": "not a time"}],
        no_expiry + [good],
        naive + [good],
    ):
        with pytest.raises(TradingError, match="rejected-order resolution"):
            rejected_client_ids(events)
    marked = {
        "event": "accepted",
        "client_order_id": CID,
        "order_id": "o",
        "reconciled": FOUND_MARK,
    }
    assert reconciled_found_ids(base + [marked]) == {CID}
    # An unmarked acceptance, or one before the unknown outcome, resolves nothing.
    assert reconciled_found_ids(base + [{**marked, "reconciled": None}]) == set()
    assert reconciled_found_ids([base[0], marked, base[1]]) == set()
    with pytest.raises(TradingError, match="Ambiguous production order"):
        shared.ownership({"nfl": [], "nba": [base[0], marked, base[1]], "spread": None})
    shared.ownership({"nfl": [], "nba": base + [marked], "spread": None})


def test_status_counts_only_unresolved_unknowns(tmp_path):
    path = journal(tmp_path)
    assert journal_summary(path)["unknown_submissions"] == 1
    with path.open("a") as f:
        f.write(
            json.dumps(
                {
                    "event": "accepted",
                    "utc": NOW.isoformat(),
                    "client_order_id": CID,
                    "order_id": "order-found",
                    "reconciled": FOUND_MARK,
                }
            )
            + "\n"
        )
    assert journal_summary(path)["unknown_submissions"] == 0


def test_owner_script_only_reads_and_never_arms():
    script = (
        Path(__file__).resolve().parents[1] / "deploy" / "reconcile_nba.sh"
    ).read_text()
    assert "-m live.prod_nba_auto --reconcile" in script
    assert "EnvironmentFile=/etc/market-maker-prod-nba-auto.env" in script
    assert "--uid=trader" in script
    for word in ("systemctl start", "systemctl enable", "--live", "ARM"):
        assert word not in script


def test_order_in_an_unlisted_status_is_found(tmp_path, journals_only):
    path = journal(tmp_path)
    odd = {
        "status": "expired",
        "ticker": TICKER,
        "client_order_id": CID,
        "order_id": "o-x",
    }
    summary = run(path, Client(orders=[odd]), journals_only)
    assert summary == {"found_on_exchange": 1, "bots_can_trade": True}


def test_unclear_cases_write_nothing(tmp_path, journals_only):
    tip = NOW - timedelta(hours=12)
    cases = {
        # Over 7 days old: its order may be on the historical endpoints.
        "older_than_7_days_check_by_hand": dict(placed=NOW - timedelta(days=8)),
        # After tip-off but under 10 minutes after the intent.
        "too_recent_try_again_after_tip_off": dict(placed=NOW - timedelta(minutes=5)),
    }
    for reason, change in cases.items():
        path = tmp_path / f"{reason}.jsonl"
        events = [
            intent(CID, TICKER, change["placed"], tip),
            {"event": "unknown_outcome", "client_order_id": CID},
        ]
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        summary = run(path, Client(), journals_only)
        assert summary[reason] == 1 and summary["bots_can_trade"] is False
        assert len(nba.load_journal(path)) == 2
    found = {"status": "executed", "ticker": TICKER, "client_order_id": CID}
    for orders, reason in (
        ([found], "found_but_unclear_check_by_hand"),  # no order id
        (
            [{**found, "order_id": "o", "ticker": OTHER}],
            "found_but_unclear_check_by_hand",
        ),
    ):
        path = journal(tmp_path)
        before = path.read_text()
        client = Client(orders=orders)
        client.orders = lambda status="resting", ticker=None, rows=orders: rows
        assert run(path, client, journals_only)[reason] == 1
        assert path.read_text() == before
    # A missing intent, a missing expiry, or an unknown after a normal
    # acceptance: left to a check by hand.
    path = tmp_path / "odd.jsonl"
    for events in (
        [{"event": "unknown_outcome", "client_order_id": CID}],
        [
            {
                **intent(CID, TICKER, NOW - timedelta(hours=2), tip),
                "expiration_ts": None,
            },
            {"event": "unknown_outcome", "client_order_id": CID},
        ],
        [
            intent(CID, TICKER, NOW - timedelta(hours=2), tip),
            {"event": "accepted", "client_order_id": CID, "order_id": "o-1"},
            {"event": "unknown_outcome", "client_order_id": CID},
        ],
    ):
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        summary = run(path, Client(), journals_only)
        assert summary["unclear_journal_check_by_hand"] == 1
        assert summary["bots_can_trade"] is False
        assert nba.load_journal(path) == events


def test_failed_read_stops_early_and_prints_no_response_body(tmp_path, journals_only):
    path = journal(tmp_path)
    before = path.read_text()

    class Failing(Client):
        def orders(self, status="resting", ticker=None):
            raise TradingError(
                "GET /portfolio/orders -> HTTP 503: <html>balance 123.45</html>"
            )

    summary = run(path, Failing(), journals_only)
    assert summary["stopped_early_by"] == "GET /portfolio/orders -> HTTP 503"
    assert summary["bots_can_trade"] is False
    assert path.read_text() == before

    class Broken(Client):
        def orders(self, status="resting", ticker=None):
            raise OSError("connection reset")

    assert run(path, Broken(), journals_only)["stopped_early_by"] == "OSError"


def test_reconcile_mode_is_read_only_under_the_account_lock(
    tmp_path, monkeypatch, capsys
):
    from contextlib import contextmanager

    import live.production_lock as production_lock

    seen = {}

    @contextmanager
    def lock():
        seen["locked"] = True
        yield

    class ReadOnly:
        def __init__(self, dry_run, env):
            seen["client"] = (type(self).__name__, dry_run, env)

    def fake_reconcile(client, journal, now):
        assert seen.get("locked")
        seen["journal"] = journal
        return {"bots_can_trade": True}

    def forbidden(*args, **kwargs):
        raise AssertionError("no trading path may run in --reconcile")

    monkeypatch.setattr(production_lock, "account_lock", lock)
    monkeypatch.setattr(nba, "STATE", tmp_path)
    monkeypatch.setattr(nba, "ReadOnlyClient", ReadOnly)
    monkeypatch.setattr(nba, "TradingClient", forbidden)
    monkeypatch.setattr(nba, "reconcile", fake_reconcile)
    monkeypatch.setattr(nba, "pass_once", forbidden)
    monkeypatch.setattr(nba, "guard", forbidden)
    monkeypatch.setenv("KALSHI_ENV", "prod")
    monkeypatch.setattr("sys.argv", ["prod_nba_auto", "--reconcile"])

    nba.main()

    assert seen["client"] == ("ReadOnly", True, "prod")
    assert seen["journal"] == tmp_path / "journal.jsonl"
    assert 'NBA RECONCILE {"bots_can_trade": true}' in capsys.readouterr().out
