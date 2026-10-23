"""Polymarket US scanner: safe matching, no orders and no false arbitrage."""

import pytest

from live import compare_polymarket_us as p


def make_event(markets=None):
    return {
        "startTime": "2026-10-18T20:25:00Z",
        "markets": markets or [],
        "active": True,
        "closed": False,
    }


def poly_market(**kw):
    return {
        "slug": "mike-evans-80-receiving-yards",
        "active": True,
        "closed": False,
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
        "question": "Mike Evans: 80+ receiving yards",
        "gameStartTime": "2026-10-18T20:25:00Z",
        "subject": {"name": "Mike Evans"},
        **kw,
    }


def kalshi_market(**kw):
    return {
        "ticker": "KXNFLRECYDS-26OCT18CHIDAL-EVANS-80",
        "event_ticker": "KXNFLRECYDS-26OCT18CHIDAL",
        "yes_sub_title": "Mike Evans: 80+",
        "floor_strike": 79.5,
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.42",
        **kw,
    }


def test_strict_same_player_stat_line_and_eastern_game_date():
    k = p.kalshi_key(kalshi_market(), "nfl", "receiving_yards")
    m = poly_market()
    key = p.poly_key(m, "nfl", make_event([m]))
    assert k == key
    assert k == ("nfl", "2026-10-18", "mike evans", "receiving_yards", 79.5)
    under = poly_market(question="Mike Evans: UNDER 80 receiving yards")
    ml = poly_market(sportsMarketTypeV2="SPORTS_MARKET_TYPE_MONEYLINE")
    different = poly_market(question="Somebody: 90+ receiving yards")
    assert p.poly_key(under, "nfl", make_event()) is None
    assert p.poly_key(ml, "nfl", make_event()) is None
    assert p.poly_key(different, "nfl", make_event()) != k
    assert p.east_date("2026-10-19T01:30:00Z") == "2026-10-18"


def test_comparison_uses_bbo_not_headline_last_trade():
    k = p.kalshi_key(kalshi_market(), "nfl", "receiving_yards")
    pm = poly_market()
    calls = []

    def fake(path, params=None):
        calls.append(path)
        return {
            "marketData": {
                "bestBid": {"value": 0.56},
                "bestAsk": {"value": 0.60},
                "lastTradePx": {"value": 0.99},
            }
        }

    rows, strict_count, bbo_calls = p.compare(
        {k: [kalshi_market()]}, {k: [pm]}, get=fake
    )
    assert strict_count == 1
    assert bbo_calls == 1
    assert len(rows) == 1
    assert rows[0]["mid_gap_cents"] == 17
    assert rows[0]["manual_rules_review_required"] is True
    assert rows[0]["fee_adjusted_edge"] is None
    assert rows[0]["executable_arbitrage"] is False
    assert calls == ["/v1/markets/mike-evans-80-receiving-yards/bbo"]


def test_no_matching_when_ambiguous_or_quote_invalid():
    k = p.kalshi_key(kalshi_market(), "nfl", "receiving_yards")
    pm = poly_market()

    def should_not_call(*args, **kwargs):
        raise AssertionError("No BBO call for ambiguous mapping")

    rows, count, hits = p.compare(
        {k: [kalshi_market(), kalshi_market()]},
        {k: [pm]},
        get=should_not_call,
    )
    assert (rows, count, hits) == ([], 1, 0)
    rows, count, hits = p.compare(
        {k: [kalshi_market()]},
        {k: [pm]},
        get=lambda *_: {"marketData": {"bestBid": None, "bestAsk": None}},
    )
    assert (rows, count, hits) == ([], 1, 1)


def test_scan_fails_closed_on_demo_env(monkeypatch):
    monkeypatch.setenv("KALSHI_ENV", "demo")
    with pytest.raises(RuntimeError, match="public Kalshi PROD"):
        p.run(poly_get=lambda *_: {}, kalshi_fetch=lambda *_: [])


def test_pagination_uses_exact_public_get_and_reports_truncation(monkeypatch):
    monkeypatch.setattr(p, "MAX_EVENT_PAGES", 2)
    paths = []

    def fake(path, params):
        paths.append((path, params["offset"]))
        return {"events": [make_event()] * p.PAGE_LIMIT}

    events, complete = p.fetch_polymarket_events("nfl", get=fake)
    assert len(events) == 200
    assert complete is False
    assert paths == [
        ("/v2/leagues/nfl/events", 0),
        ("/v2/leagues/nfl/events", 100),
    ]


def test_no_api_keys_or_trading_calls_in_scanner():
    from pathlib import Path

    content = Path(p.__file__).read_text()
    assert "orders.create" not in content
    assert "orders.cancel" not in content
    assert "POST" not in content
    assert "https://gamma-api.polymarket.com" not in content
    assert "https://clob.polymarket.com" not in content


def test_prop_catalog_uses_explicit_league_tag_and_type():
    calls = []

    def api(path, params=None):
        calls.append((path, params))
        if path == "/v2/leagues/nfl":
            return {"league": {"tagId": 1}}
        if path == "/v1/markets":
            return {"markets": [poly_market()]}
        raise AssertionError(path)

    markets, complete = p.fetch_polymarket_props("nfl", get=api)
    assert len(markets) == 1
    assert complete
    assert calls[1][0] == "/v1/markets"
    assert calls[1][1]["tagIds"] == 1
    assert calls[1][1]["sportsMarketTypes"] == "SPORTS_MARKET_TYPE_PROP"


def test_full_scan_mocked_public_requests_and_no_external_actions(monkeypatch):
    monkeypatch.delenv("KALSHI_ENV", raising=False)
    counter = {"poly": 0, "kalshi": 0}

    def poly(path, params=None):
        counter["poly"] += 1
        if path.startswith("/v2/leagues/"):
            return {"league": {"tagId": 1 if "/nfl" in path else 5}}
        if path == "/v1/markets":
            return (
                {"markets": [poly_market()]}
                if params["tagIds"] == 1
                else {"markets": []}
            )
        return {"marketData": {"bestBid": {"value": 0.56}, "bestAsk": {"value": 0.60}}}

    def kalshi(series, status="open", historical=False):
        counter["kalshi"] += 1
        return [kalshi_market()] if series == "KXNFLRECYDS" else []

    snapshot = p.run(poly_get=poly, kalshi_fetch=kalshi)
    assert snapshot["status"] == "research_only_no_order_access"
    assert snapshot["venue"] == "polymarket_us"
    assert snapshot["manual_contract_equivalence_verified"] is False
    assert snapshot["coverage"]["nfl"]["strict_candidate_keys"] == 1
    assert snapshot["coverage"]["nfl"]["priced_pairs_needing_rules_review"] == 1
    assert snapshot["coverage"]["nba"]["strict_candidate_keys"] == 0
    assert snapshot["candidates"][0]["mid_gap_cents"] == 17.0
    assert counter["poly"] == 7  # filtered reads, NBA diagnostic, and BBO
    assert counter["kalshi"] == 6  # NBA 4 series and NFL 2


def test_only_unambiguous_integer_over_thresholds_are_normalized():
    assert (
        p.threshold_from_question(
            "Mike Evans: over 79.5 receiving yards", "receiving_yards"
        )
        == 79.5
    )
    assert (
        p.threshold_from_question(
            "Mike Evans: over 80 receiving yards", "receiving_yards"
        )
        == 80.5
    )
    assert (
        p.threshold_from_question("Mike Evans: 80+ receiving yards", "receiving_yards")
        == 79.5
    )


def test_player_prop_metadata_classification():
    m = poly_market(sportsMarketTypeV2="SPORTS_MARKET_TYPE_UNSPECIFIED")
    m["metadata"] = {"market_sport_type": "football_player_receiving_yards"}
    assert p.poly_key(m, "nfl", make_event()) is not None


def test_unfiltered_empty_filter_diagnostic_does_not_become_trading_signal():
    calls = []

    def api(path, params=None):
        calls.append((path, params))
        if path == "/v2/leagues/nba":
            return {"league": {"tagId": 5}}
        if path == "/v1/markets":
            assert "sportsMarketTypes" not in params
            return {
                "markets": [
                    poly_market(sportsMarketTypeV2="SPORTS_MARKET_TYPE_PROP"),
                    {"sportsMarketTypeV2": "SPORTS_MARKET_TYPE_FUTURE"},
                ]
            }
        raise AssertionError(path)

    d = p.sample_unfiltered_catalog("nba", get=api)
    assert d["sampled_rows"] == 2
    assert d["typed_prop_rows_seen"] == 1
    assert d["sample_complete"] is True
    assert d["scope"].endswith("diagnostic only")
    assert len(calls) == 2
