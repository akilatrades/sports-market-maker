"""Offline tests for sportsbook fair prices on spread-maker markets. No network."""

from datetime import UTC, datetime

import pytest

from kalshi import spread_books as sb

START = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)


def book(key, home_price, away_price):
    return {
        "key": key,
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": "Manitoba Moose", "price": home_price},
                    {"name": "Iowa Wild", "price": away_price},
                ],
            }
        ],
    }


def event(*books, commence="2026-10-24T23:05:00Z"):
    return {
        "id": "e1",
        "commence_time": commence,
        "home_team": "Manitoba Moose",
        "away_team": "Iowa Wild",
        "bookmakers": list(books),
    }


def test_only_checked_leagues_are_mapped_and_no_esports():
    assert sb.SPORT_FOR_SERIES["KXAHLGAME"] == "icehockey_ahl"
    assert not {"KXCS2GAME", "KXDOTA2GAME", "KXNWSLSPREAD"} & set(sb.SPORT_FOR_SERIES)


def test_h2h_consensus_removes_the_vig_per_book_then_averages():
    # -150 / +130: raw 0.600 and 0.4348; fair 0.5798 / 0.4202.
    prices = sb.h2h_consensus(event(book("a", -150, 130), book("b", -150, 130)))
    p, n = prices["Manitoba Moose"]
    assert n == 2 and p == pytest.approx(0.6 / (0.6 + 100 / 230), abs=1e-6)
    assert p + prices["Iowa Wild"][0] == pytest.approx(1.0)


def test_fair_yes_matches_team_and_start_and_needs_two_books():
    market = {"ticker": "KXAHLGAME-26OCT241900MANIOW-MAN", "yes_sub_title": "Manitoba"}
    got, why = sb.fair_yes(
        market, START, [event(book("a", -150, 130), book("b", -140, 120))]
    )
    assert why == "ok" and got["book_team"] == "Manitoba Moose" and got["books"] == 2
    assert 0.55 < got["p"] < 0.6
    one, why = sb.fair_yes(market, START, [event(book("a", -150, 130))])
    assert one is None and why == "too_few_books"


def test_fair_yes_refuses_wrong_time_or_unknown_team():
    market = {"yes_sub_title": "Manitoba"}
    late = event(
        book("a", -150, 130), book("b", -150, 130), commence="2026-10-25T05:00:00Z"
    )
    assert sb.fair_yes(market, START, [late]) == (None, "no_match")
    other = {"yes_sub_title": "Rockford IceHogs"}
    assert sb.fair_yes(
        other, START, [event(book("a", -150, 130), book("b", -150, 130))]
    ) == (
        None,
        "no_match",
    )


def test_ambiguous_names_are_not_guessed():
    a = event(book("a", -150, 130), book("b", -150, 130))
    b = dict(a, id="e2")
    assert sb.match("Manitoba", START, [a, b]) == (None, "ambiguous")


def test_shadow_rows_record_fair_price_and_edges_without_trading():
    from research.spread_book_shadow import rows_for

    now = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)
    market = {
        "ticker": "KXAHLGAME-26OCT241900MANIOW-MAN",
        "event_ticker": "KXAHLGAME-26OCT241900MANIOW",
        "yes_sub_title": "Manitoba",
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.52",
    }
    rows = rows_for(
        "KXAHLGAME", [market], [event(book("a", -150, 130), book("b", -150, 130))], now
    )
    assert len(rows) == 1 and rows[0]["reason"] == "ok"
    r = rows[0]
    assert (r["our_yes"], r["our_no"]) == (41, 49)
    assert r["edge_yes"] == pytest.approx(r["fair_yes"] - 0.41, abs=1e-4)
    assert r["edge_no"] == pytest.approx(1 - r["fair_yes"] - 0.49, abs=1e-4)
