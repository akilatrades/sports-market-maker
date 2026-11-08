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
            if o.get("status") == status and ticker in (None, o.get("ticker"))
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
    # Every status of its own market was read, then its fills and positions.
    assert [c for c in client.calls if c[0] == "orders"] == [
        ("orders", s, TICKER) for s in ("resting", "executed", "canceled")
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
    placed = NOW - timedelta(hours=1)
    base = [
        intent(CID, TICKER, placed, NOW),
        {"event": "unknown_outcome", "client_order_id": CID},
    ]
    good = {
        "event": "reconciled_rejected",
        "utc": NOW.isoformat(),
        "client_order_id": CID,
        "evidence": ABSENT_EVIDENCE,
        "intent_age_seconds": 600,
        "after_expiry": True,
    }
    assert rejected_client_ids(base + [good]) == {CID}
    for bad in (
        {**good, "intent_age_seconds": 599},
        {**good, "intent_age_seconds": 600.0},
        {k: v for k, v in good.items() if k != "after_expiry"},
        {**good, "evidence": "owner_said_so"},
    ):
        with pytest.raises(TradingError, match="rejected-order resolution"):
            rejected_client_ids(base + [bad])
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
