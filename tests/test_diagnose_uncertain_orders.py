"""Regression tests for read-only uncertain-exchange-order audit."""

from tools.diagnose_uncertain_orders import collect, inspect


def intent():
    return {
        "event": "intent",
        "client_order_id": "smm-private",
        "ticker": "KXNBA-TEST",
        "utc": "2026-10-20T13:00:00+00:00",
        "cost": 1.0,
    }


def unknown():
    return {
        "event": "unknown_outcome",
        "client_order_id": "smm-private",
        "type": "TradingError",
    }


class Exchange:
    def __init__(self, orders=None, fills=None, positions=None):
        self.data = {
            "/portfolio/orders": {"orders": orders or []},
            "/portfolio/fills": {"fills": fills or []},
            "/portfolio/positions": {"market_positions": positions or []},
        }
        self.calls = []

    def pages(self, path, key, **params):
        self.calls.append((path, key, params))
        return self.data[path][key]


def test_exact_client_order_identity_finds_expired_order_without_identifiers():
    orders = [
        {
            "client_order_id": "smm-private",
            "order_id": "exchange-private",
            "ticker": "KXNBA-TEST",
            "status": "canceled",
        }
    ]
    exchange = Exchange(
        orders, [{"ticker": "KXNBA-TEST", "order_id": "exchange-private"}]
    )
    report = collect(exchange, {"nfl": [], "nba": [intent(), unknown()]})
    assert report["ready_to_trade"] is False
    assert report["cases"][0]["classification"] == (
        "EXACT_EXCHANGE_ORDER_FOUND_KEEP_HALTED_FOR_REPAIR"
    )
    assert report["cases"][0]["exact_order_fill_records"] == 1
    assert report["cases"][0]["exchange_status"] == "canceled"
    assert all("private" not in str(v) for v in report["cases"][0].values())
    assert {call[0] for call in exchange.calls} == {
        "/portfolio/orders",
        "/portfolio/fills",
        "/portfolio/positions",
    }
    assert (
        exchange.calls[0][2] == {}
    )  # includes filled/expired/canceled, not resting-only


def test_ticker_only_match_cannot_clear_an_ambiguous_submission():
    report = inspect(
        [intent(), unknown()],
        [
            {
                "client_order_id": "another-user",
                "order_id": "other",
                "ticker": "KXNBA-TEST",
            }
        ],
        [{"order_id": "other", "ticker": "KXNBA-TEST"}],
        [{"ticker": "KXNBA-TEST", "position_fp": "-2"}],
    )[0]
    assert report["classification"] == "NO_EXACT_MATCH_NOT_PROOF_OF_REJECTION"
    assert report["same_ticker_nonzero_position_records"] == 1
    assert report["same_ticker_fill_records"] == 1


def test_ticker_mismatch_is_a_hard_block():
    row = inspect(
        [intent(), unknown()],
        [{"client_order_id": "smm-private", "order_id": "one", "ticker": "DIFFERENT"}],
        [],
        [],
    )[0]
    assert row["classification"] == "EXACT_ID_BUT_TICKER_MISMATCH_HALT"


def test_no_unknown_events_is_not_approval_to_restart():
    result = collect(Exchange(), {"nfl": [], "nba": [intent()]})
    assert result["status"] == "NO_UNKNOWN_OUTCOME_EVENT"
    assert not result["ready_to_trade"]
