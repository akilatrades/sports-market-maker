"""Dead-ticket rules and the read-only watcher (no network)."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from markets.nba import dead_ticket as D
from research import dead_ticket_watch as W

NOW = datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc)


def summary(period=4, clock=120.0, home=110, away=95, stats=None, state="in"):
    labels = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST"]
    stats = stats or {"Day'Ron Sharpe": ["20", "8", "4-9", "0-1", "0-0", "6", "1"]}

    def block(team, people):
        return {
            "team": {"abbreviation": team},
            "statistics": [
                {
                    "labels": labels,
                    "athletes": [
                        {"athlete": {"displayName": name}, "stats": row}
                        for name, row in people.items()
                    ],
                }
            ],
        }

    return {
        "header": {
            "competitions": [
                {
                    "status": {
                        "period": period,
                        "clock": clock,
                        "type": {"state": state},
                    },
                    "competitors": [
                        {
                            "homeAway": "home",
                            "score": str(home),
                            "team": {"abbreviation": "MEM"},
                        },
                        {
                            "homeAway": "away",
                            "score": str(away),
                            "team": {"abbreviation": "BKN"},
                        },
                    ],
                }
            ]
        },
        "boxscore": {
            "players": [
                block("BKN", stats),
                block(
                    "MEM", {"Ja Morant": ["30", "24", "9-17", "2-5", "4-4", "3", "9"]}
                ),
            ]
        },
    }


def market(ticker, bid="0.0200", ask="0.0300"):
    return {
        "ticker": ticker,
        "status": "active",
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
    }


def test_ticker_and_name_keys():
    parsed = D.parse_ticker("KXNBAPTS-26NOV14BKNMEM-BKNDSHARPE20-15")
    assert parsed == {
        "stat": "points",
        "series": "KXNBAPTS",
        "game": "26NOV14BKNMEM",
        "team": "BKN",
        "key": "DSHARPE",
        "line": 15,
    }
    assert D.parse_ticker("KXNBAPTS-26NOV14BKNMEM-LALDSHARPE20-15") is None
    assert D.parse_ticker("KXNFLTD-26NOV14BKNMEM-BKNX1-1") is None
    assert D.player_key("Shai Gilgeous-Alexander") == "SGILGEOUSALEXANDER"
    assert D.player_key("Day'Ron Sharpe") == "DSHARPE"
    assert D.player_key("Jaren Jackson Jr.") == "JJACKSON"
    assert D.kalshi_team("GS") == "GSW" and D.kalshi_team("BOS") == "BOS"


def test_minutes_left_and_clock():
    assert D.minutes_left(3, 720) == 24
    assert D.minutes_left(4, 90) == 1.5
    assert D.minutes_left(5, 150) == 2.5  # overtime: this period only
    assert D.clock_seconds({"displayClock": "5:32"}) == 332
    assert D.clock_seconds({"displayClock": "32.1"}) == 32.1
    with pytest.raises(ValueError):
        D.minutes_left(0, 10)


def test_out_of_reach_rules():
    # 2 minutes left: points ceiling 1.5*2+3 = 6 (loose), 1.5*7+3 = 13.5 (strict)
    assert D.out_of_reach("points", 7, 2, overtime=False)
    assert not D.out_of_reach("points", 6, 2, overtime=False)
    assert not D.out_of_reach("points", 13, 2)
    assert D.out_of_reach("points", 14, 2)
    assert D.out_of_reach("rebounds", 6, 2)  # 0.5*7+2 = 5.5
    assert not D.out_of_reach("rebounds", 5, 2)
    assert D.out_of_reach("threes", 5, 1)  # 6/3+2 = 4
    assert not D.out_of_reach("points", 40, 30)  # first half: never
    assert not D.out_of_reach("points", 0, 1)  # already there
    assert not D.out_of_reach("points", float("nan"), 1)


def test_summary_parsing():
    state = D.parse_summary(summary())
    assert state["minutes_left"] == 2 and state["margin"] == 15
    assert state["players"][("BKN", "DSHARPE")] == {
        "points": 8,
        "rebounds": 6,
        "assists": 1,
        "threes": 0,
    }
    assert state["players"][("MEM", "JMORANT")]["threes"] == 2
    assert D.parse_summary(summary(state="post")) is None
    assert D.parse_summary({"header": {}}) is None
    twins = {"Jalen Williams": ["1", "2", "1-1", "0-0", "0-0", "1", "1"]}
    twins["Jaylin Williams"] = ["1", "9", "1-1", "0-0", "0-0", "1", "1"]
    assert ("BKN", "JWILLIAMS") not in D.parse_summary(summary(stats=twins))["players"]
    bench = D.parse_summary(summary(stats={"Nic Claxton": []}))
    assert bench["players"][("BKN", "NCLAXTON")]["points"] == 0


def test_fee_rounds_up_per_order():
    assert D.taker_fee_cents(0.02) == pytest.approx(0.2)  # 1.372c -> 2c on 10
    assert D.taker_fee_cents(0.99) == pytest.approx(0.1)


def test_observe_flags_dead_and_reached_only():
    state = D.parse_summary(summary())
    game = "26NOV14BKNMEM"
    markets = [
        market(f"KXNBAPTS-{game}-BKNDSHARPE20-25"),  # needs 17 in 2 min: strict
        market(f"KXNBAPTS-{game}-BKNDSHARPE20-15"),  # needs 7: loose only
        market(f"KXNBAPTS-{game}-BKNDSHARPE20-10"),  # needs 2: alive
        market(f"KXNBAPTS-{game}-BKNDSHARPE20-30", bid="0.0100"),  # 1c bid
        market(f"KXNBAPTS-{game}-BKNDSHARPE20-35", bid="0.4000"),  # state doubt
        market(f"KXNBAPTS-{game}-MEMJMORANT12-20", "0.9800", "0.9900"),  # won
        market(f"KXNBAPTS-{game}-MEMJMORANT12-24", "0.9800", "0.9900"),  # no spare
        market(f"KXNBAPTS-{game}-MEMJMORANT12-15", "0.9900", "1.0000"),  # no offer
        market(f"KXNBAPTS-{game}-MEMNOBODY1-15"),  # unknown player
        market("KXNBAPTS-26NOV14LALBOS-BKNDSHARPE20-25"),  # another game
    ]
    book = {"yes_dollars": [["0.0100", "50"], ["0.0200", "120"]], "no_dollars": []}
    rows = W.observe(state, game, markets, NOW, lambda ticker: book)
    got = {(r["ticker"].rsplit("-", 2)[1][:4], r["line"]): r for r in rows}
    assert set(got) == {("BKND", 25), ("BKND", 15), ("MEMJ", 20)}
    assert got[("BKND", 25)]["strict"] and got[("BKND", 25)]["kind"] == "dead"
    assert not got[("BKND", 15)]["strict"]
    assert got[("BKND", 25)]["size"] == 120 and got[("BKND", 25)]["need"] == 17
    assert got[("MEMJ", 20)]["kind"] == "reached"
    assert got[("MEMJ", 20)]["size"] == 0  # no NO bids in this book


def test_one_pass_skips_first_half_and_survives_errors():
    board = {
        "events": [
            {
                "id": "1",
                "date": "2026-11-15T01:00Z",
                "competitions": [
                    {
                        "status": {"type": {"state": "in"}},
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": "MEM"}},
                            {"homeAway": "away", "team": {"abbreviation": "BKN"}},
                        ],
                    }
                ],
            },
            {"id": "2", "competitions": []},
        ]
    }
    game = "26NOV14BKNMEM"
    sources = {
        "scoreboards": lambda now: board,
        "summary": lambda game_id: summary(),
        "markets": lambda g: [market(f"KXNBAPTS-{g}-BKNDSHARPE20-25")],
        "book": lambda ticker: None,
    }
    rows, active = W.one_pass(NOW, sources)
    assert active and [r["game"] for r in rows] == [game]
    early = sources | {"summary": lambda game_id: summary(period=2)}
    assert W.one_pass(NOW, early) == ([], True)

    def broken(game_id):
        raise OSError("down")

    assert W.one_pass(NOW, sources | {"summary": broken}) == ([], True)
    assert W.one_pass(NOW, sources | {"scoreboards": lambda now: {}}) == ([], False)


def test_a_game_hours_away_does_not_keep_the_watcher_waiting():
    def pre(start):
        return {
            "id": "9",
            "date": start,
            "competitions": [{"status": {"type": {"state": "pre"}}}],
        }

    soon, later = pre("2026-11-15T04:30Z"), pre("2026-11-15T06:00Z")
    assert W.games_in_play({"events": [soon, later]}, NOW) == ([], 1)
    assert W.games_in_play({"events": [later]}, NOW) == ([], 0)
    assert W.games_in_play({"events": [later]}) == ([], 1)  # no clock: all count
    assert W.one_pass(NOW, {"scoreboards": lambda now: {"events": [later]}}) == (
        [],
        False,
    )
    assert W.one_pass(NOW, {"scoreboards": lambda now: {"events": [soon]}}) == (
        [],
        True,
    )


def test_probe_reads_a_finished_game_as_if_live():
    def event(state):
        return {
            "id": "7",
            "date": "2026-11-15T01:00Z",
            "competitions": [
                {
                    "status": {"type": {"state": state}},
                    "competitors": [
                        {"homeAway": "home", "team": {"abbreviation": "MEM"}},
                        {"homeAway": "away", "team": {"abbreviation": "BKN"}},
                    ],
                }
            ],
        }

    final = lambda game_id: summary(state="post", clock=0.0)  # noqa: E731
    sources = {"scoreboards": lambda now: {"events": [event("post")]}, "summary": final}
    out = W.probe(NOW, sources)
    assert out["box_score_parsed"] and out["players"] == 2 and out["period"] == 4
    assert out["box_score_game"] == "26NOV14BKNMEM"
    assert out["top_scorer"][:2] == ["MEM", "JMORANT"]
    broken = sources | {"summary": lambda game_id: {"header": {}}}
    assert W.probe(NOW, broken)["box_score_error"] == "KeyError"
    nothing = {"scoreboards": lambda now: {"events": [event("pre")]}}
    assert "box_score_parsed" not in W.probe(NOW, nothing)


def test_throttled_books_once_per_window():
    calls, clock = [], [0.0]
    read = W.throttled_books(
        lambda t: calls.append(t) or {"x": 1}, 300, lambda: clock[0]
    )
    assert read("A") == {"x": 1} and read("A") is None
    clock[0] = 301
    assert read("A") == {"x": 1} and calls == ["A", "A"]


def test_sightings_settle_and_report(tmp_path):
    def row(utc, ticker, kind, strict, bid, ask, game="G1"):
        return {
            "utc": utc,
            "kind": kind,
            "strict": strict,
            "ticker": ticker,
            "game": game,
            "stat": "points",
            "line": 25,
            "so_far": 8.0,
            "need": 17.0,
            "period": 4,
            "minutes_left": 2.0,
            "margin": 15.0,
            "yes_bid": bid,
            "yes_ask": ask,
            "size": 100.0,
        }

    rows = [
        row("2026-11-15T03:00:00+00:00", "A", "dead", True, 0.02, 0.03),
        row("2026-11-15T03:00:30+00:00", "A", "dead", True, 0.02, 0.03),
        row("2026-11-15T03:01:00+00:00", "A", "dead", True, 0.01, 0.03),  # gone
        row("2026-11-15T03:00:00+00:00", "B", "dead", True, 0.03, 0.05, "G2"),
        row("2026-11-15T03:00:00+00:00", "C", "reached", True, 0.98, 0.99),
        row("2026-11-15T03:00:00+00:00", "D", "dead", False, 0.02, 0.03),
    ]
    assert W.save(rows, tmp_path).name == "2026-11-15T0300Z.csv.gz"
    first = W.first_sightings(pd.DataFrame(rows))
    a = first[first.ticker == "A"].iloc[0]
    assert a.stayed_seconds == 30 and a.there_next_poll
    assert not first[first.ticker == "B"].iloc[0].there_next_poll
    results = {"A": "no", "B": "yes", "C": "yes"}  # D not settled yet
    summary_ = W.summarize(tmp_path, lambda tickers: results)
    assert summary_["unsettled_markets"] == 1
    strict = summary_["rules"]["dead_strict"]
    assert strict["markets"] == 2 and strict["lost"] == 1
    # A: +2c - 0.2c fee; B: 3c - 100c - 0.3c fee
    assert strict["cents_per_contract_after_fee"] == pytest.approx((1.8 - 97.3) / 2)
    reached = summary_["rules"]["reached"]
    assert reached["lost"] == 0
    assert reached["cents_per_contract_after_fee"] == pytest.approx(0.9)
    assert summary_["rules"]["dead_loose_only"] == {"markets": 0}
    assert (tmp_path / "first_sightings.csv").exists()


def test_watch_stops_when_nothing_is_on(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "one_pass", lambda now, sources: ([], False))
    ticks = iter(pd.date_range("2026-11-15T03:00Z", periods=500, freq="30s"))
    slept = []
    files = W.watch(5, 30, tmp_path, slept.append, lambda: next(ticks).to_pydatetime())
    assert files == [] and len(slept) < 25


def test_watcher_never_touches_trading_code():
    import inspect

    for module in (W, D):
        source = inspect.getsource(module)
        for word in (
            "kalshi.trading",
            "TradingClient",
            "create_order",
            "from live",
        ):
            assert word not in source
