"""Consistency scanner and longshot study (fake data, no network)."""

import json
from datetime import UTC, datetime, timedelta

import pandas as pd

from research import consistency_scan as C
from research import longshot as L

NOW = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)


def m(ticker, bid, ask, **kw):
    return {"ticker": ticker, "yes_bid_dollars": str(bid), "yes_ask_dollars": str(ask),
            "status": "active", **kw}  # fmt: skip


def test_bids_summing_above_one_are_riskless_only_after_fees():
    rich = {"event_ticker": "E", "mutually_exclusive": True,
            "markets": [m("A", 0.40, 0.42), m("B", 0.38, 0.40), m("C", 0.30, 0.33)]}  # fmt: skip
    ((kind, tickers, edge, n, _),) = C.sum_findings(rich)
    assert (
        kind == "sum_bids_above_1"
        and n == 3
        and round(edge, 3)
        == round(0.08 - sum(C.fee(1 - b) for b in (0.4, 0.38, 0.3)), 3)
    )
    thin = {
        **rich,
        "markets": [m("A", 0.40, 0.42), m("B", 0.31, 0.33), m("C", 0.30, 0.33)],
    }
    assert C.sum_findings(thin) == []  # 1.01 before fees, below 1 after
    assert C.sum_findings({**rich, "mutually_exclusive": False}) == []


def test_threshold_and_calendar_need_the_harder_yes_bid_above_the_easier_ask():
    ladder = {"markets": [m("X4", 0.50, 0.52, floor_strike=4, strike_type="greater", yes_sub_title="Rate above 4%"),
                          m("X5", 0.58, 0.60, floor_strike=5, strike_type="greater", yes_sub_title="Rate above 5%")]}  # fmt: skip
    ((kind, tickers, edge, _, _),) = C.threshold_findings(ladder)
    assert kind == "threshold" and tickers == ["X4", "X5"] and round(edge, 3) == 0.025
    close = lambda d: (NOW + timedelta(days=d)).isoformat()  # noqa: E731
    cal = {"markets": [m("JUN", 0.45, 0.47, title="Will X happen before Jun 30, 2027?", close_time=close(200)),
                       m("DEC", 0.40, 0.41, title="Will X happen before Dec 31, 2027?", close_time=close(380))]}  # fmt: skip
    ((kind, tickers, edge, _, _),) = C.calendar_findings(cal)
    assert kind == "calendar" and tickers == ["DEC", "JUN"] and edge > 0
    cal["markets"][0]["yes_bid_dollars"] = "0.39"
    assert C.calendar_findings(cal) == []


def test_runs_build_a_record_and_count_lasting_edges(tmp_path):
    rich = {"event_ticker": "E", "mutually_exclusive": True,
            "markets": [m("A", 0.45, 0.47), m("B", 0.40, 0.42), m("C", 0.30, 0.33)]}  # fmt: skip
    get = lambda path, params: {"events": [rich]}  # noqa: E731
    C.main([], out=tmp_path, get_json=get, now=NOW)
    assert C.due(NOW + timedelta(minutes=10), tmp_path) == "not due"
    C.main([], out=tmp_path, get_json=get, now=NOW + timedelta(hours=1))
    s = json.loads((tmp_path / "summary.json").read_text())
    assert s["runs"] == 2 and s["events_2c_in_consecutive_runs"] == {
        "sum_bids_above_1": 1
    }
    assert C.due(NOW + timedelta(days=7, hours=1), tmp_path) == "done"


def test_taker_longshot_pays_one_minus_the_bid_plus_fee():
    q = pd.DataFrame({"ticker": ["T1", "T2"], "end_ts": [1, 1], "yes_bid": [0.05, 0.50],
                      "yes_ask": [0.07, 0.52], "result": ["no", "yes"], "event_ticker": ["E1", "E2"],
                      "day": pd.to_datetime(["2025-11-01", "2026-04-01"]), "family": "other"})  # fmt: skip
    f, exact, _ = L.taker(L.first_quotes(q), "no")
    assert f.ticker.tolist() == ["T1"]
    assert round(float(exact.iloc[0]), 4) == round(1 - 0.95 - 0.07 * 0.95 * 0.05, 4)


def test_the_scan_runs_in_the_hourly_job_and_needs_no_install_to_check_due():
    from pathlib import Path

    flow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/paper-mentions.yml"
    ).read_text()
    assert (
        "python -m research.consistency_scan --due" in flow
        and "outputs/consistency" in flow
    )
    head = (
        Path(__file__).resolve().parents[1] / "research/consistency_scan.py"
    ).read_text()
    assert "import pandas" not in head and "import numpy" not in head  # stdlib only


def test_thresholds_on_different_players_or_teams_are_never_paired():
    """26 Nov: one event holds many players' yards and both teams' spreads."""
    event = {"markets": [
        m("WR1-50", 0.01, 0.02, floor_strike=49.5, strike_type="greater", yes_sub_title="Amon-Ra St. Brown: 50+"),
        m("WR2-40", 0.99, 1.00, floor_strike=39.5, strike_type="greater", yes_sub_title="Jameson Williams: 40+"),
        m("DUKE3", 0.01, 0.02, floor_strike=3.5, strike_type="greater", yes_sub_title="Duke wins by over 3.5"),
        m("WAKE4", 0.99, 1.00, floor_strike=4.5, strike_type="greater", yes_sub_title="Wake Forest wins by over 4.5"),
    ]}  # fmt: skip
    assert C.threshold_findings(event) == []
    assert C.subject(event["markets"][0]) == "amon-ra st. brown: #"
