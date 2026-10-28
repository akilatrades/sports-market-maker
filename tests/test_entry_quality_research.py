import json
import sqlite3
import tempfile
import unittest
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from deploy.spread_entry_control import TAG, cron
from research import nba_entry_study as nba
from research.spread_entry_quality import entry_features, exposure, fill_report
from research.spread_entry_recorder import read_rows
from research.spread_forward_core import EvidenceError
from tools.export_private_fills import ExportError, entry_quality_file


AT = datetime(2026, 10, 28, 18, tzinfo=UTC)


def projection(**changes):
    row = {"snapshot_utc": AT.isoformat(), "tip_utc": (AT + timedelta(hours=3)).isoformat(),
           "p_model": "0.8", "yes_bid_dollars": "0.4", "yes_ask_dollars": "0.6",
           "game_id": "game", "player_id": "player", "stat": "points", "ticker": "KXNBAPTS-GAME-PLAYER-25",
           "injury_status": "", "book_updated_utc": AT.isoformat(), "book_n": "2",
           "p_book": "0.2", "book_commence_utc": (AT + timedelta(hours=3)).isoformat()}
    row.update(changes)
    return row


def opportunity(**changes):
    return nba.opportunity(projection(**changes),
                           {"orderbook_fp": {"yes_dollars": [["0.4", "10"]], "no_dollars": [["0.4", "10"]]}},
                           {"fee_type": "quadratic", "fee_multiplier": "1"}, AT)


class NBAStudyTest(unittest.TestCase):
    def test_common_price_but_independent_model_and_book_filters(self):
        r = opportunity()
        self.assertEqual(r["price"], .41)
        self.assertEqual(r["quantity"], 1)
        self.assertEqual(r["policies"], {"no_baseline": True, "model_veto": False, "fresh_books_veto": True})
        self.assertTrue(opportunity(p_model="0.1")["policies"]["model_veto"])

    def test_no_future_stale_or_post_tip_projections(self):
        for changes in ({"snapshot_utc": (AT + timedelta(seconds=1)).isoformat()},
                        {"snapshot_utc": (AT - timedelta(minutes=31)).isoformat()},
                        {"tip_utc": (AT + timedelta(hours=1)).isoformat()}, {"p_model": "NaN"}):
            self.assertEqual(nba.eligible([projection(**changes)], AT), [])

    def test_rung_selection_does_not_use_model_score(self):
        a = projection(ticker="A", p_model="0.01")
        b = projection(ticker="B", p_model="0.99")
        self.assertEqual(nba.eligible([b, a], AT)[0]["ticker"], "A")
        a["p_model"], b["p_model"] = "0.99", "0.01"
        self.assertEqual(nba.eligible([b, a], AT)[0]["ticker"], "A")

    def test_book_veto_never_falls_back_to_model(self):
        for changes in ({"book_n": "1"}, {"book_updated_utc": ""},
                        {"book_updated_utc": (AT + timedelta(seconds=1)).isoformat()},
                        {"book_updated_utc": (AT - timedelta(minutes=31)).isoformat()},
                        {"book_commence_utc": AT.isoformat()}):
            r = opportunity(p_model=".01", **changes)
            self.assertTrue(r["policies"]["model_veto"])
            self.assertFalse(r["policies"]["fresh_books_veto"])

    def test_fee_rounds_up_per_single_contract(self):
        self.assertEqual(nba.fee(.5), .02)
        self.assertEqual(nba.fee(.5, count=10), .18)

    def test_trade_pages_fail_closed_and_deduplicate(self):
        def responder(payload):
            return lambda path, params: {"trades_created_ts": AT.isoformat()} if path == "/historical/cutoff" else payload
        with self.assertRaises(EvidenceError):
            nba.complete_trades(lambda *args: None, "T", AT, AT + timedelta(hours=1))
        with self.assertRaises(EvidenceError):
            nba.complete_trades(responder({"trades": [], "cursor": "loop"}), "T", AT, AT)
        trade = {"trade_id": "one", "ticker": "T", "created_time": AT.isoformat()}
        trades = nba.complete_trades(responder({"trades": [trade]}), "T", AT, AT)
        self.assertEqual(len(trades), 1)

    def test_recent_history_does_not_require_archived_market(self):
        paths = []
        def get(path, params):
            paths.append(path)
            if path == "/historical/cutoff":
                return {"trades_created_ts": (AT - timedelta(days=1)).isoformat()}
            return {"trades": []}
        self.assertEqual(nba.complete_trades(get, "T", AT, AT + timedelta(hours=1)), [])
        self.assertNotIn("/historical/trades", paths)

    def test_fill_windows_volume_blocks_and_touch_sensitivity(self):
        r = opportunity()
        def trade(seconds, price=.59, count=.5, **kwargs):
            return {"created_time": (AT + timedelta(seconds=seconds)).isoformat(),
                    "taker_outcome_side": "yes", "yes_price_dollars": str(price),
                    "count_fp": str(count), **kwargs}
        prints = [trade(-1, .9, 100), trade(1), trade(2), trade(3, .9, 100, is_block_trade=True), trade(10800, .9, 100)]
        result = nba.execution(r, prints)
        self.assertTrue(result["touch"]["filled"])
        self.assertFalse(result["through"]["filled"])
        self.assertTrue(nba.execution(r, prints + [trade(4, .6, 1)])["through"]["filled"])

    def test_unknown_execution_and_unsettled_are_not_zero_return(self):
        r = opportunity(p_model=".1")
        r["execution_status"] = "unknown"
        a = nba.report([r])["comparisons"]["through/no_baseline"]
        self.assertEqual(a["settled"], 0)
        self.assertEqual(a["pending_or_unknown_execution"], 1)
        self.assertIsNone(a["actual_win_rate"])
        self.assertGreater(a["exposure_by_game"]["game"], 0)

    def test_implementation_identity_refuses_resume(self):
        from research.nba_entry_runner import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(json.dumps({"manifest": {"implementation_hash": "changed"}, "rows": []}))
            with self.assertRaises(EvidenceError):
                run(get=lambda *args: self.fail("network before identity check"), root=root)

    def test_shared_game_budget_and_immutable_slots(self):
        from research.nba_entry_runner import run
        candidates = [projection(player_id=str(i), ticker=f"KXNBAPTS-GAME-P{i}-25", p_model=".1") for i in range(30)]
        def get(path, params):
            if path.startswith("/series/"):
                return {"series": {"fee_type": "quadratic", "fee_multiplier": "1"}}
            return {"orderbook_fp": {"yes_dollars": [["0.4", "10"]], "no_dollars": [["0.4", "10"]]}}
        with tempfile.TemporaryDirectory() as directory, patch.object(nba, "utcnow", return_value=AT), patch.object(nba, "load_csv", return_value=candidates):
            root = Path(directory)
            run(get=get, root=root)
            first = json.loads((root / "state.json").read_text())["rows"]
            self.assertEqual(len(first), 11)
            self.assertLessEqual(sum(r["price"] + r["fee_upper_estimate"] for r in first), 5)
            run(get=get, root=root)
            self.assertEqual(json.loads((root / "state.json").read_text())["rows"], first)


class SpreadStudyTest(unittest.TestCase):
    def order(self):
        return {"ticker": "T", "utc": AT.isoformat(), "side": "yes", "count": 5, "price_cents": 50}

    def sample(self, **changes):
        s = {"ticker": "T", "at": (AT - timedelta(seconds=20)).isoformat(),
             "completed_at": (AT - timedelta(seconds=10)).isoformat(), "valid": True,
             "external_book": {"yes": [[".49", "5"]], "no": [[".49", "5"]]}, "fee_multiplier": "1"}
        s.update(changes)
        return s

    def test_post_pass_stale_and_failed_books_are_missing(self):
        for s in (self.sample(completed_at=(AT + timedelta(seconds=1)).isoformat()),
                  self.sample(at=(AT - timedelta(seconds=121)).isoformat()), self.sample(valid=False)):
            self.assertIsNone(entry_features(self.order(), [s])["depth_filter"])

    def test_whole_order_depth_and_fees_required(self):
        self.assertTrue(entry_features(self.order(), [self.sample()])["depth_filter"])
        thin = self.sample(external_book={"yes": [[".49", "4"]], "no": []})
        self.assertFalse(entry_features(self.order(), [thin])["depth_filter"])
        wide = self.sample(external_book={"yes": [[".40", "50"]], "no": []})
        self.assertFalse(entry_features(self.order(), [wide])["depth_filter"])

    def test_same_game_across_prop_series_aggregates(self):
        positions = [{"ticker": "KXNBAPTS-GAME-PLAYER-25", "market_exposure_dollars": "3"}]
        orders = [{"ticker": "KXNBAREB-GAME-OTHER-10", "price": ".5", "quantity": "2"}]
        r = exposure(positions, orders)
        self.assertEqual(r["by_game"]["GAME"]["total_cost"], "4.0")
        self.assertEqual(exposure([{"ticker": "X"}], [])["unknown_position_rows"], 1)

    def test_fill_privacy_and_unknown_settlement(self):
        f = {"fid": "raw-fill", "oid": "raw-order", "ticker": "T", "event_ticker": "S-GAME",
             "at": (AT + timedelta(seconds=300)).isoformat(), "side": "yes", "quantity": "1", "price": ".5", "fee": "0"}
        entries = {"raw-order": {"utc": AT.isoformat(), "features": {"status": "missing_pre_pass_book", "depth_filter": None}}}
        r = fill_report([f], entries, [], {})
        self.assertNotIn("raw-fill", json.dumps(r))
        self.assertNotIn("raw-order", json.dumps(r))
        self.assertEqual(r["groups"]["all_observed_fills"]["settled_quantity"], "0")
        self.assertEqual(fill_report([], {}, [], {})["fills"], [])

    def test_old_study_database_read_only_and_no_schema_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.sqlite3"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE records(kind TEXT,id TEXT,at TEXT,body BLOB)")
            db.execute("INSERT INTO records VALUES(?,?,?,?)", ("candidate", "1", AT.isoformat(), zlib.compress(b'{"eligible":true}')))
            db.commit()
            db.close()
            original = path.read_bytes()
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            self.assertEqual(read_rows(db, "candidate"), [{"eligible": True}])
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM records")
            db.close()
            self.assertEqual(path.read_bytes(), original)

    def test_cron_preserves_trading_and_original_observer(self):
        existing = "3 * * * * trading\n* * * * * observer # spread-forward-readonly-v1\n"
        changed = cron(existing, "* * * * * entry")
        self.assertTrue(changed.startswith(existing))
        self.assertEqual(cron(changed, "* * * * * entry"), changed)
        self.assertEqual(changed.count(TAG), 1)

    def test_export_only_known_schema_and_health(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text(json.dumps({"protocol": "spread-entry-quality-v1", "generated_at": AT.isoformat(),
                                        "manifest": {}, "report": {}, "raw": "must not export"}))
            self.assertNotIn("must not export", entry_quality_file(path))
            path.write_text('{"protocol":"wrong"}')
            with self.assertRaises(ExportError):
                entry_quality_file(path)


if __name__ == "__main__":
    unittest.main()
