"""Read-only arbitrage probe tests: prices, fee rounding, and safety labels."""

from decimal import Decimal

from research import arb_ladder_probe as probe


def market(ticker, strike, yes_bid, no_bid, *, event="GAME", person="Alex Lee"):
    return {
        "ticker": ticker,
        "event_ticker": event,
        "yes_sub_title": person + ": 20+ points",
        "floor_strike": strike,
        "status": "active",
        "yes_bid_dollars": yes_bid,
        "no_bid_dollars": no_bid,
    }


def sample_pair():
    return [
        market("LOW", 19.5, "0.20", "0.72"),
        market("HIGH", 24.5, "0.33", "0.45"),
    ]


def test_adjacent_strikes_and_same_player_event_only():
    candidates, coverage = probe.ladder_candidates(sample_pair(), "KXNBAPTS")
    assert coverage == {"eligible_markets": 2, "ordered_pairs_checked": 1}
    assert len(candidates) == 1
    assert candidates[0]["gross_cents_per_pair_at_list_quotes"] == 5.0
    assert candidates[0]["buy_yes_ticker"] == "LOW"
    assert candidates[0]["buy_no_ticker"] == "HIGH"
    other = market("HIGH", 24.5, "0.33", "0.45", person="Other Player")
    assert not probe.ladder_candidates([sample_pair()[0], other], "KXNBAPTS")[0]
    other["event_ticker"] = "OTHER"
    assert not probe.ladder_candidates([sample_pair()[0], other], "KXNBAPTS")[0]


def test_nonadjacent_ladder_mispricing_is_not_missed():
    markets = [
        market("LOW", 9.5, "0.20", "0.60"),
        market("MID", 19.5, "0.35", "0.50"),
        market("HIGH", 29.5, "0.45", "0.30"),
    ]
    candidates, coverage = probe.ladder_candidates(markets, "KXNBAPTS")
    assert coverage["ordered_pairs_checked"] == 3
    assert [(r["buy_yes_ticker"], r["buy_no_ticker"]) for r in candidates] == [
        ("LOW", "HIGH")
    ]


def test_book_depth_taker_fees_and_no_claim_of_executable_arbitrage():
    candidate = probe.ladder_candidates(sample_pair(), "KXNBAPTS")[0][0]
    result = probe.check_depth(
        candidate,
        {"no_dollars": [["0.72", "10.00"]]},
        {"yes_dollars": [["0.33", "10.00"]]},
    )
    assert result["hypothetical_pairs"] == 10
    assert result["gross_dollars"] == 0.50
    assert result["general_taker_fees_dollars"] == 0.31
    assert result["indicative_net_dollars"] == 0.19
    assert result["executable_arbitrage_verified"] is False
    assert probe.fee(Decimal("0.50"), 1) == Decimal("0.02")


def test_rejects_duplicate_strikes_empty_book_and_fractional_depth():
    rows = sample_pair()
    duplicate = market("DUP", 19.5, "0.20", "0.72")
    assert not probe.ladder_candidates(rows + [duplicate], "KXNBAPTS")[0]
    candidate = probe.ladder_candidates(rows, "KXNBAPTS")[0][0]
    assert probe.check_depth(candidate, {}, {}) is None
    assert (
        probe.check_depth(
            candidate,
            {"no_dollars": [["0.72", "0.50"]]},
            {"yes_dollars": [["0.33", "10.00"]]},
        )
        is None
    )


def test_run_uses_only_injected_public_data_readers():
    calls = []

    def market_get(name, status, historical):
        calls.append(("market", name, status, historical))
        return sample_pair()

    def book_get(ticker):
        calls.append(("book", ticker))
        if ticker == "LOW":
            return {"no_dollars": [["0.72", "10.00"]]}
        return {"yes_dollars": [["0.33", "10.00"]]}

    result = probe.run(market_get, book_get, series=("KXNBAPTS",))
    assert result["gross_positive_list_quote_pairs"] == 1
    assert result["potential_fee_positive_quotes"] == 1
    assert result["verified_arbitrages"] == 0
    assert calls == [
        ("market", "KXNBAPTS", "open", False),
        ("book", "LOW"),
        ("book", "HIGH"),
    ]
