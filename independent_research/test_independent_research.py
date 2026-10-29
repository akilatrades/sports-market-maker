"""Guards for as-of features, price parsing, and pre-close screening."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd


def module(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(name + ".py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


analysis = module("analyze")
collect = module("collect")


class ResearchGuards(unittest.TestCase):
    def test_order_and_unknown_hosts_rejected_before_network(self):
        with patch(
            "urllib.request.urlopen", side_effect=AssertionError("network called")
        ):
            for url in [
                "https://external-api.kalshi.com/trade-api/v2/portfolio/orders",
                "https://example.com/private",
            ]:
                with self.assertRaises(ValueError):
                    collect.get(url)

    def test_dollar_schema_and_missing_prices(self):
        self.assertEqual(analysis.dollars({"close_dollars": "0.5600"}), 0.56)
        self.assertEqual(analysis.dollars({"close": "0.5600"}), 0.56)
        self.assertTrue(np.isnan(analysis.dollars({"close": 56})))
        self.assertTrue(np.isnan(analysis.dollars(None)))

    def test_future_snapshot_cannot_change_earlier_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            dates = pd.date_range("2023-01-01", "2026-07-03")
            for stamp, last in [
                ("2026-06-29T08:00:00Z", "2026-06-25"),
                ("2026-07-06T08:00:00Z", "2026-07-03"),
            ]:
                for d in dates[dates <= last]:
                    rows.append(
                        {
                            "snapshot": stamp,
                            "sha": stamp,
                            "date": str(d.date()),
                            "passengers": 2_000_000
                            + 20_000 * d.dayofweek
                            + int(100_000 * np.sin(d.dayofyear / 365.25 * 2 * np.pi)),
                        }
                    )
            data = pd.DataFrame(rows)
            with patch.object(analysis, "OUT", root):
                data.to_csv(root / "tsa_vintages.csv", index=False)
                analysis.tsa()
                before = (
                    pd.read_csv(root / "tsa_predictions.csv")
                    .set_index("date")
                    .loc["2026-07-01"]
                )
                data.loc[data.snapshot == "2026-07-06T08:00:00Z", "passengers"] *= 2
                data.to_csv(root / "tsa_vintages.csv", index=False)
                analysis.tsa()
                after = (
                    pd.read_csv(root / "tsa_predictions.csv")
                    .set_index("date")
                    .loc["2026-07-01"]
                )
                self.assertEqual(before.baseline, after.baseline)
                self.assertEqual(before.challenger, after.challenger)
                self.assertNotEqual(before.actual, after.actual)

    def test_structural_screen_rejects_crossed_and_after_close_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            (raw / "candles").mkdir(parents=True)
            end = pd.Timestamp("2026-10-27T18:00:00Z")
            markets = []
            for tick, strike, bid, ask in [
                ("TEST-A", 10, 0.40, 0.42),
                ("TEST-B", 20, 0.45, 0.47),
            ]:
                markets.append(
                    {
                        "ticker": tick,
                        "event_ticker": "TEST-E",
                        "close_time": end.isoformat(),
                        "strike_type": "greater",
                        "floor_strike": strike,
                    }
                )
                cs = []
                for t, b, a in [
                    (end - pd.Timedelta(hours=2), bid, ask),
                    (end - pd.Timedelta(hours=1), 0.8, 0.2),
                    (end, bid, ask),
                ]:
                    cs.append(
                        {
                            "end_period_ts": int(t.timestamp()),
                            "yes_bid": {"close_dollars": b},
                            "yes_ask": {"close_dollars": a},
                        }
                    )
                (raw / "candles" / f"{tick}.json").write_text(
                    json.dumps({"candlesticks": cs})
                )
            (root / "market_sample.json").write_text(json.dumps(markets))
            with (
                patch.object(analysis, "OUT", root),
                patch.object(analysis, "RAW", raw),
            ):
                r = analysis.structural()
            self.assertEqual(r["valid_bid_ask_rows"], 2)
            self.assertEqual(r["positive_raw_candidates"], 1)
            self.assertAlmostEqual(r["max_raw_margin"], 0.03)
            self.assertTrue(r["no_trading_pnl"])


if __name__ == "__main__":
    unittest.main()
