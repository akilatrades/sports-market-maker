"""Private reporting must never invent balances, fees or realized profits."""

import json
import shutil
import subprocess
import threading
import unittest
from datetime import UTC, datetime
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from kalshi.trading import TradingClient, TradingError
from live.account_dashboard import ReadOnlyClient, Snapshot, handler_for, summarize


class AccountAccounting(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.events = [
            {
                "event": "intent",
                "client_order_id": "c1",
                "ticker": "NFL-EXAMPLE",
                "cost": 2.64,
                "count": 4,
                "price_cents": 66,
            },
            {"event": "accepted", "client_order_id": "c1", "order_id": "o1"},
        ]
        self.fills = [
            {
                "fill_id": f"f{i}",
                "order_id": "o1",
                "count_fp": "1.00",
                "no_price_dollars": "0.6600",
                "fee_cost": "0.0000",
                "side": "no",
                "action": "buy",
            }
            for i in range(4)
        ]

    def report(self, **updates):
        args = dict(
            balance={"balance": 10000, "portfolio_value": 264},
            positions=[
                {
                    "ticker": "NFL-EXAMPLE",
                    "position_fp": "-4.00",
                    "market_exposure_dollars": "2.6400",
                }
            ],
            resting=[],
            fills=self.fills,
            settlements=[],
            events=self.events,
            scan=None,
            now=self.now,
        )
        args.update(updates)
        return summarize(**args)

    def test_four_fills_are_one_filled_order_and_cost_is_not_a_loss(self):
        report = self.report()
        self.assertEqual(report["account"]["cash_dollars"], 100)
        self.assertEqual(report["account"]["equity_dollars"], 102.64)
        s = report["strategy"]
        self.assertEqual(
            (
                s["accepted_orders"],
                s["filled_orders"],
                s["fill_records"],
                s["contracts_filled"],
            ),
            (1, 1, 4, 4),
        )
        self.assertEqual(s["fill_cost_dollars"], 2.64)
        self.assertEqual(s["fill_fees_dollars"], 0)
        self.assertIsNone(s["settled_profit_dollars"])
        self.assertEqual(report["positions"][0]["cost_dollars"], 2.64)

    def test_v2_sell_yes_is_reported_as_no_position_fill(self):
        for fill in self.fills:
            fill.update({
                "action": "sell",
                "side": "yes",
                "outcome_side": "no",
                "book_side": "ask",
            })
        report = self.report()
        self.assertEqual(report["strategy"]["contracts_filled"], 4)
        self.assertEqual(report["strategy"]["fill_cost_dollars"], 2.64)

    def test_actual_v2_with_legacy_mismatch_uses_canonical_no(self):
        for fill in self.fills:
            fill.update({
                "action": "sell", "side": "no",
                "outcome_side": "no", "book_side": "ask",
            })
        report = self.report()
        self.assertEqual(report["strategy"]["contracts_filled"], 4)
        self.assertEqual(report["strategy"]["filled_orders"], 1)

    def test_conflicting_v2_fill_direction_fails_closed(self):
        self.fills[0].update({
            "action": "sell", "side": "yes",
            "outcome_side": "yes", "book_side": "ask",
        })
        with self.assertRaises(TradingError):
            self.report()

    def test_missing_balance_is_not_zero(self):
        with self.assertRaises(TradingError):
            self.report(balance={"portfolio_value": 264})
        with self.assertRaises(TradingError):
            self.report(balance={"balance": 10000})

    def test_dollar_fields_take_precedence_over_deprecated_cent_fields(self):
        report = self.report(
            balance={"balance_dollars": "100.25", "balance": 1, "portfolio_value": 264}
        )
        self.assertEqual(report["account"]["equity_dollars"], 102.89)

    def test_missing_fee_stays_unknown(self):
        del self.fills[0]["fee_cost"]
        self.assertIsNone(self.report()["strategy"]["fill_fees_dollars"])

    def test_real_settlement_profit_deducts_cost_and_fee_once(self):
        result = {
            "ticker": "NFL-EXAMPLE",
            "revenue": 400,
            "yes_total_cost_dollars": "0",
            "no_total_cost_dollars": "2.64",
            "fee_cost": ".02",
        }
        s = self.report(settlements=[result])["strategy"]
        self.assertEqual(s["settled_profit_dollars"], 1.34)
        self.assertEqual(s["settled_markets"], 1)
        del result["fee_cost"]
        self.assertIsNone(
            self.report(settlements=[result])["strategy"]["settled_profit_dollars"]
        )

    def test_duplicate_fills_are_counted_once(self):
        report = self.report(fills=self.fills + self.fills)
        self.assertEqual(report["strategy"]["contracts_filled"], 4)

    def test_foreign_orders_do_not_count_as_strategy_fills(self):
        self.fills.append({"order_id": "foreign"})
        self.assertEqual(self.report()["strategy"]["contracts_filled"], 4)

    def test_dropped_exchange_connection_retains_stale_data(self):
        snapshot = Snapshot()
        snapshot.value = self.report()
        with patch(
            "live.account_dashboard.collect", side_effect=TradingError("private detail")
        ):
            snapshot.refresh(None, None)
        self.assertEqual(snapshot.read()["status"], "error")
        self.assertEqual(snapshot.read()["account"]["cash_dollars"], 100)
        self.assertNotIn("private detail", str(snapshot.read()))

    def test_positions_pagination_does_not_drop_exposure(self):
        client = TradingClient.__new__(TradingClient)
        client._request = Mock(
            side_effect=[
                {"market_positions": [{"position": 1}], "cursor": "next"},
                {"market_positions": [{"position": 2}]},
            ]
        )
        self.assertEqual(len(client.positions()), 2)
        self.assertEqual(client._request.call_count, 2)

    def test_readonly_transport_blocks_all_writes(self):
        client = ReadOnlyClient.__new__(ReadOnlyClient)
        client.env = "prod"
        for method in ("POST", "DELETE", "PATCH", "PUT"):
            with self.assertRaises(TradingError):
                client._request(method, "/portfolio/orders")
        with self.assertRaises(TradingError):
            client.place(None)
        with self.assertRaises(TradingError):
            client.cancel("o1")

    def test_local_api_denies_foreign_hosts_and_web_origins(self):
        snapshot = Snapshot()
        snapshot.value = self.report()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Mock())
        server.RequestHandlerClass = handler_for(snapshot, server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for headers, status in (
                ({}, 200),
                ({"Host": "evil.example"}, 403),
                ({"Origin": "https://evil.example"}, 403),
                ({"Sec-Fetch-Site": "cross-site"}, 403),
            ):
                with self.subTest(headers=headers):
                    connection = HTTPConnection("127.0.0.1", server.server_port)
                    connection.request("GET", "/api/account", headers=headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, status)
                    if status == 200:
                        self.assertEqual(
                            json.loads(response.read())["account"]["cash_dollars"], 100
                        )
                        self.assertEqual(
                            response.getheader("Cache-Control"), "no-store"
                        )
                    connection.close()
        finally:
            server.shutdown()
            server.server_close()

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_browser_rendering_missing_stale_and_unsafe_text(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", str(root / "tests/account_dashboard.cjs")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
