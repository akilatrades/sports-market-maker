from research.nfl_live_fill_audit import summarize_trades


def test_compare_yes_taker_trade_prices_against_no_bid():
    # NO bid 66c is resting YES ask at 34c. Only YES taking prints
    # can hit a YES ask. At-price trades can be ahead in the queue.
    trades = [
        {"taker_outcome_side": "yes", "yes_price": 0.34, "count": 2},
        {"taker_outcome_side": "yes", "yes_price": 0.35, "count": 3},
        {"taker_outcome_side": "yes", "yes_price": 0.33, "count": 4},
        {"taker_outcome_side": "no", "yes_price": 0.40, "count": 10},
        {"taker_outcome_side": "yes", "yes_price": 0.36,
         "count": 50, "is_block_trade": True},
    ]
    result = summarize_trades(66, trades)
    assert result["yes_ask_cents"] == 34
    assert result["at_price"] == 2
    assert result["through_price"] == 3
    assert result["one_cent_away"] == 4
    assert result["yes_taker_volume"] == 9


def test_missing_quotes_and_wrong_taker_side_cannot_claim_fill():
    trades = [{"taker_outcome_side": "no", "yes_price": 0.36, "count": 5},
              {"taker_outcome_side": "yes", "yes_price": None, "count": 2}]
    result = summarize_trades(66, trades)
    assert result["at_price"] == 0
    assert result["through_price"] == 0
    assert result["yes_taker_volume"] == 0
