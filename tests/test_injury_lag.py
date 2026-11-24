"""research/injury_lag.py on made-up reports and trades (no network)."""

from datetime import date

import pandas as pd

from research import injury_lag as L


def test_names_meet_kalshi_tickers():
    assert L.ticker_code("New York Knicks", "Brunson, Jalen") == "NYKJBRUNSON"
    assert (
        L.ticker_code("Oklahoma City Thunder", "Gilgeous-Alexander, Shai")
        == "OKCSGILGEOUSALEXANDER"
    )
    assert L.ticker_code("Miami Heat", "Butler III, Jimmy") == "MIAJBUTLER"
    assert L.ticker_code("Nowhere", "A, B") is None
    assert L.split_ticker("KXNBAPTS-26JUN13NYKSAS-SASVWEMBANYAMA1-40") == (
        "KXNBAPTS",
        date(2026, 6, 13),
        "SASVWEMBANYAMA",
    )


def report(slot, status, player="Brunson, Jalen"):
    return {
        "slot_et": slot,
        "team": "New York Knicks",
        "player": player,
        "status": status,
        "game_date": "01/10/2026",
        "game_time": "07:30 (ET)",
    }


def test_events_are_new_outs_with_a_recent_previous_report():
    rows = pd.DataFrame(
        [
            report("2026-01-10T17:00:00-05:00", "Questionable"),
            report("2026-01-10T17:15:00-05:00", "Out"),  # event
            report("2026-01-10T17:30:00-05:00", "Out"),  # already out
            report("2026-01-10T17:00:00-05:00", "Out", "Hart, Josh"),  # out all day
            report("2026-01-10T17:15:00-05:00", "Out", "Hart, Josh"),
            report(
                "2026-01-10T19:30:00-05:00", "Out", "Towns, Karl-Anthony"
            ),  # gap too long
            report("2026-01-10T17:30:00-05:00", "Probable", "Towns, Karl-Anthony"),
        ]
    )
    e = L.out_events(rows)
    assert e.player.tolist() == ["Brunson, Jalen"] and e.was.tolist() == [
        "Questionable"
    ]
    assert e.code.tolist() == ["NYKJBRUNSON"]


def trades(rows):
    t = pd.DataFrame(
        rows,
        columns=["ticker", "created_time", "yes_price", "count", "taker_outcome_side"],
    )
    t["is_block_trade"] = False
    return t


def test_the_rule_sells_stale_trades_after_the_reaction_delay():
    tk = "KXNBAPTS-26JAN10NYKBOS-NYKJBRUNSON11-25"
    t = trades(
        [
            (tk, "2026-01-10T21:50:00Z", 0.60, 5, "yes"),  # p0 = 60c, before the report
            (tk, "2026-01-10T22:16:00Z", 0.55, 3, "yes"),  # 1 minute after: too soon
            (tk, "2026-01-10T22:20:00Z", 0.50, 4, "yes"),  # stale, taken
            (tk, "2026-01-10T22:40:00Z", 0.45, 2, "no"),  # stale, within 30
            (tk, "2026-01-10T22:41:00Z", 0.05, 9, "no"),  # repriced: not stale
            (
                tk,
                "2026-01-10T23:10:00Z",
                0.40,
                1,
                "yes",
            ),  # stale, only in the 60-min window
        ]
    )
    L_tr = t.assign(time=pd.to_datetime(t.created_time, utc=True), yes=t.yes_price)
    parsed = L_tr.ticker.map(L.split_ticker)
    L_tr["game_day"] = [p[1] for p in parsed]
    L_tr["code"] = [p[2] for p in parsed]
    L_tr["game"] = L_tr.ticker.str.split("-").str[1]
    events = pd.DataFrame(
        [
            {
                **report("x", "Out"),
                "slot_utc": pd.Timestamp("2026-01-10T22:15:00Z"),
                "previous_slot_utc": pd.Timestamp("2026-01-10T22:00:00Z"),
                "was": "Questionable",
                "code": "NYKJBRUNSON",
            }
        ]
    )
    matched = L.match(events, L_tr)
    assert matched.tickers.iloc[0] == [tk]
    m = L.measure(matched, L_tr, {tk: "no"})
    r = m.iloc[0]
    assert r.p0 == 0.60 and r.stale_trades == 4 and r.first_stale_minutes == 1.0
    assert (
        r.rule_15_contracts == 1
        and r.rule_30_contracts == 2
        and r.rule_60_contracts == 3
    )
    # Sold YES at 50c and 45c: bought NO at 50c and 55c, both paid $1, less fees.
    assert abs(r.rule_30_pnl - ((1 - 0.50 - 0.02) + (1 - 0.55 - 0.02))) < 1e-9
    s = L.score(m)
    assert (
        s["rule"][30]["contracts"] == 2 and s["verdict"]["passes"] is False
    )  # far too few
    assert s["settlement_of_out_players"] == {"no": 1}


def test_reports_are_resumable_and_missing_slots_are_skipped(tmp_path):
    calls = []

    def read(slot):
        calls.append(slot)
        return (
            None
            if slot.minute == 15
            else pd.DataFrame([report(slot.isoformat(), "Out")])
        )

    out = L.collect_reports([date(2026, 1, 10)], state=tmp_path, read=read)
    assert out["days_done"] == 1 and len(calls) == len(L.slots(date(2026, 1, 10))) == 52
    saved = pd.read_csv(tmp_path / "reports" / "2026-01-10.csv")
    assert len(saved) == 39  # 52 slots less the 13 at :15
    again = L.collect_reports([date(2026, 1, 10)], state=tmp_path, read=read)
    assert again["days_already"] == 1 and len(calls) == 52
