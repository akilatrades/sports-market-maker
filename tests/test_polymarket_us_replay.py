"""Historical US replay must not fabricate maker fills or look ahead."""
from datetime import UTC, datetime, timedelta

from research import polymarket_us_replay as r


def test_price_history_is_quote_not_trade_and_respects_pregame_window():
    now = 2_000_000_000
    points = [
        {"timestamp": now - 1, "longPrice": 0.51, "shortPrice": 0.54},
        {"timestamp": now + 10, "longPrice": 0.51, "shortPrice": 0.54},
        {"timestamp": now + 20, "longPrice": 0.52, "shortPrice": 0.52},
    ]
    quote = r.quote_candidate(points, now, now + 100)
    assert quote["timestamp"] == now + 10
    assert quote["rest_no_price"] == 0.50
    assert quote["spread_cents"] == 5.0
    assert r.quote_candidate(points, now + 30, now + 100) is None


def test_rejects_crossing_quotes_bad_prices_and_nonbinary_settlements():
    a = [{"timestamp": 100, "longPrice": 0.51, "shortPrice": 0.49}]
    assert r.quote_candidate(a, 90, 110) is None
    assert r.quote_candidate([{"timestamp": 100, "longPrice": 1.3,
                               "shortPrice": 0.1}], 90, 110) is None
    assert r.settle_yes({"settlement": "0"}) == 0
    assert r.settle_yes({"settlement": {"value": 1}}) == 1
    assert r.settle_yes({"settlement": 0.4}) is None
    assert r.settle_yes({"something_else": 1}) is None


def test_replay_reports_conditional_payoff_not_actual_profit(monkeypatch):
    now = datetime(2026, 10, 18, 20, 25, tzinfo=UTC)
    quote_ts = int((now - timedelta(hours=4)).timestamp())
    m = {
        "slug": "mike-evans-80-rec-yds",
        "closed": True,
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
        "question": "Mike Evans: 80+ receiving yards",
        "subject": {"name": "Mike Evans"},
        "gameStartTime": now.isoformat(),
    }
    calls = []

    def fake(path, params=None):
        calls.append(path)
        if path.startswith("/v2/leagues/"):
            return {"league": {"tagId": 5}}
        if path == "/v1/markets":
            if params.get("sportsMarketTypes"):
                return {"markets": [m]} if params["tagIds"] == 5 else {"markets": []}
            return {"markets": []}
        if path == "/v1/price-history":
            assert params["timestamp.startTimestamp"] < quote_ts
            assert params["timestamp.endTimestamp"] > quote_ts
            return {"history": [{"timestamp": quote_ts, "longPrice": 0.51,
                                 "shortPrice": 0.54}]}
        if path.endswith("/settlement"):
            return {"settlement": 0}
        raise AssertionError(path)

    result = r.replay(get=fake)
    assert result["coverage"]["nba"]["strict_archived_prop_contracts_found"] == 1
    assert result["scored_quote_opportunities"] == 1
    assert result["quote_opportunities"][0]["no_payoff_if_filled"] == 0.5
    assert result["quote_opportunities"][0]["filled"] is None
    assert result["quote_opportunities"][0]["order_submitted"] is False
    assert result["realized_profit"] is None
    assert result["real_fill_events"] is None
    assert result["model_tested"] is False
    assert result["all_fill_counterfactual"]["not_trading_profit"] is True
    assert "Insufficient" in result["interpretation"]
    assert all("/orders" not in call for call in calls)


def test_no_archived_props_is_inconclusive_not_zero_edge():
    def fake(path, params=None):
        if path.startswith("/v2/leagues/"):
            return {"league": {"tagId": 1}}
        return {"markets": []}

    result = r.replay(get=fake)
    assert result["coverage"]["nba"]["strict_archived_prop_contracts_found"] == 0
    assert result["all_fill_counterfactual"]["profit_per_contract_if_every_order_filled"] is None
    assert result["realized_profit"] is None
    assert result["model_tested"] is False


def test_only_read_only_market_endpoints_allowed():
    for path in ("/portfolio/orders", "/v1/orders", "/v1/markets/foo/bbo",
                 "https://clob.polymarket.com/book"):
        try:
            r.get_json(path)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unsafe path accepted: {path}")
