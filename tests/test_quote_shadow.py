"""Shadow price alternatives do not change production entry or quote rules."""

from types import SimpleNamespace

from live.quote_shadow import shadow_quotes


def row(price=0.60, edge=0.08, yes_bid=0.30, yes_ask=0.42):
    return SimpleNamespace(price=price, edge=edge, yes_bid=yes_bid, yes_ask=yes_ask)


def test_shadow_ladder_retains_post_only_and_net_edge_floor():
    result = shadow_quotes(row())
    assert result["status"] == "shadow_only"
    assert [r["no_bid_cents"] for r in result["alternatives"]] == [60, 61, 62]
    assert [r["estimated_edge_after_price_cents"] for r in result["alternatives"]] == [
        8,
        7,
        6,
    ]
    assert all(x["maker_only_on_snapshot"] for x in result["alternatives"])


def test_shadow_refuses_crossing_and_insufficient_remaining_edge():
    # At 60c NO, YES ask 40c, YES bid 39c: another tick crosses.
    result = shadow_quotes(row(edge=0.05, yes_bid=0.39, yes_ask=0.44))
    assert [x["no_bid_cents"] for x in result["alternatives"]] == [60]
    assert [
        x["no_bid_cents"] for x in shadow_quotes(row(edge=0.035))["alternatives"]
    ] == [60]


def test_invalid_market_is_never_given_a_trade_recommendation():
    assert shadow_quotes(row(yes_bid=0.60, yes_ask=0.55))["alternatives"] == []
    assert shadow_quotes(row(price=float("nan")))["status"] == "unknown_input"
    assert shadow_quotes(row(price=0.75, yes_bid=0.26))["alternatives"] == []
