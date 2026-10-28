"""Bounded GET-only sidecar. The original study DB is opened mode=ro."""

import fcntl
import hashlib
import json
import os
import sqlite3
import time
import zlib
from datetime import timedelta
from pathlib import Path

from research.spread_forward_core import EvidenceError, external_book, instant, normalized_orders
from research.spread_forward_recorder import ENVIRONMENT, HOME as ORIGINAL, ReadOnlyAPI, Store, now, policy, write_json
from research.spread_forward_recorder import environment
from research.spread_entry_quality import PROTOCOL, entry_features, exposure, fill_report

HOME = Path("/home/trader/spread-entry-quality")


def read_rows(db, kind, since=None, limit=None):
    sql, params = "SELECT body FROM records WHERE kind=?", [kind]
    if since is not None:
        sql += " AND at>=?"
        params.append(since)
    sql += " ORDER BY at DESC,id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [json.loads(zlib.decompress(row[0])) for row in db.execute(sql, params)]


def code_hash():
    names = ("spread_entry_recorder.py", "spread_entry_quality.py", "spread_forward_core.py",
             "spread_forward_recorder.py", "spread_forward_candidates.py")
    return hashlib.sha256(b"".join((Path(__file__).parent / f).read_bytes() for f in names)).hexdigest()


def cycle(home=HOME):
    os.umask(0o077)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (home / "observer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        health = {"at": now().isoformat(), "state": "recording", "protocol": PROTOCOL}
        if (home / "health.json").exists():
            health["last_success"] = json.loads((home / "health.json").read_text()).get("last_success")
        try:
            if (home / "STOP").exists():
                return
            os.nice(10)
            policy()
            original_bytes = (ORIGINAL / "manifest.json").read_bytes()
            original = json.loads(original_bytes)
            original_health = json.loads((ORIGINAL / "health.json").read_text())
            if original_health.get("state") == "error" or (now() - instant(original_health["last_success"])).total_seconds() > 120:
                raise EvidenceError("original_observer_unhealthy")
            if sum(p.stat().st_size for p in home.glob("evidence.sqlite3*")) > 500_000_000:
                raise EvidenceError("research_disk_budget")
            store = Store(home / "evidence.sqlite3")
            source = sqlite3.connect(f"file:{ORIGINAL / 'evidence.sqlite3'}?mode=ro", uri=True, timeout=20)
            try:
                orders = read_rows(source, "cohort_order")
                fills = read_rows(source, "fill")
                manifest = store.meta("manifest")
                if not manifest:
                    manifest = {"protocol": PROTOCOL, "start": now().isoformat(), "end": original["end"],
                                "drain_end": original["drain_end"], "implementation_hash": code_hash(),
                                "original_manifest_hash": hashlib.sha256(original_bytes).hexdigest(),
                                "baseline_events": sorted({o["event_ticker"] for o in orders} | set(original["baseline_events"])),
                                "pre_pass_max_age_seconds": 120, "exit_gap_limit": "0.05",
                                "pass_age_upper_limit_seconds": 900, "maximum_books_per_cycle": 18}
                    store.meta("manifest", manifest)
                    write_json(home / "manifest.json", manifest)
                if manifest["implementation_hash"] != code_hash() or manifest["original_manifest_hash"] != hashlib.sha256(original_bytes).hexdigest():
                    raise EvidenceError("study_identity_changed")
                if now() >= instant(manifest["drain_end"]):
                    health["state"] = "complete"
                    write_json(home / "health.json", health)
                    return
                api = ReadOnlyAPI(environment(ENVIRONMENT))
                raw_before = api.pages("/portfolio/orders", "orders", {"status": "resting"})
                before = normalized_orders(raw_before)
                positions = api.pages("/portfolio/positions", "market_positions")
                if now() < instant(manifest["end"]):
                    candidates = read_rows(source, "candidate", (now() - timedelta(minutes=15)).isoformat(), 6000)
                    latest = {}
                    for c in candidates:
                        latest.setdefault(c["ticker"], c)
                    pool = sorted({c["ticker"] for c in latest.values() if c.get("eligible")} | {o["ticker"] for o in before})
                    rotation = int(store.meta("rotation") or 0)
                    chosen = (pool[rotation % len(pool):] + pool[:rotation % len(pool)])[:18] if pool else []
                    store.meta("rotation", rotation + len(chosen))
                    fee_cache, books = {}, []
                    for ticker in chosen:
                        began = now()
                        try:
                            series = ticker.split("-")[0]
                            if series not in fee_cache:
                                fee_cache[series] = api.get("/series/" + series)["series"]
                            fees = fee_cache[series]
                            if fees.get("fee_type") not in ("quadratic", "quadratic_with_maker_fees"):
                                raise EvidenceError("unsupported_fee_type")
                            book = api.get("/markets/" + ticker + "/orderbook", {"depth": 0})
                            books.append({"ticker": ticker, "at": now().isoformat(), "requested_at": began.isoformat(),
                                          "raw_book": book, "fee_multiplier": fees["fee_multiplier"], "valid": True})
                        except (OSError, ValueError, KeyError, TypeError) as error:
                            books.append({"ticker": ticker, "at": now().isoformat(), "valid": False,
                                          "reason": type(error).__name__})
                    after = normalized_orders(api.pages("/portfolio/orders", "orders", {"status": "resting"}))
                    for b in books:
                        b["completed_at"] = now().isoformat()
                        selected_before = [o for o in before if o["ticker"] == b["ticker"]]
                        selected_after = [o for o in after if o["ticker"] == b["ticker"]]
                        try:
                            if selected_before != selected_after:
                                raise EvidenceError("own_orders_changed")
                            if b["valid"]:
                                b["external_book"] = external_book(b["raw_book"], b["ticker"], before)
                        except (ValueError, KeyError, TypeError) as error:
                            b.update(valid=False, reason=type(error).__name__)
                        b.update(own_before=selected_before, own_after=selected_after)
                        store.put("book:" + b["ticker"], str(time.time_ns()), b)
                    health.update(candidate_tickers=len(pool), sampled_tickers=len(chosen),
                                  valid_books=sum(b["valid"] for b in books))
                    store.put("cycle", str(time.time_ns()), dict(health))
                else:
                    health["state"] = "settlement_followup"
                selected = [o for o in orders if instant(manifest["start"]) <= instant(o["utc"]) < instant(manifest["end"])
                            and o["event_ticker"] not in manifest["baseline_events"]]
                known = store.ids("entry")
                for o in selected:
                    if o["order_id"] in known:
                        continue
                    # Snapshot lookup is bounded and excludes every future book.
                    samples = read_rows(store.db, "book:" + o["ticker"],
                                        (instant(o["utc"]) - timedelta(seconds=120)).isoformat())
                    features = entry_features(o, samples)
                    store.put("entry", o["order_id"], {"oid": o["order_id"], "utc": o["utc"], "features": features})
                entries = {e["oid"]: e for e in store.values("entry")}
                checkpoints = read_rows(source, "checkpoint")
                accounts = read_rows(source, "account_snapshot", limit=1)
                outcomes = {s.get("ticker") or s.get("market_ticker"): s.get("market_result")
                            for a in accounts for s in a["settlements"]}
                result = fill_report(fills, entries, checkpoints, outcomes)
                observed = sum(e["features"]["status"] == "observed" for e in entries.values())
                result.update(orders=len(entries), pre_pass_books=observed,
                              pre_pass_coverage=observed / len(entries) if entries else None,
                              exposure=exposure(positions, before))
                health["last_success"] = now().isoformat()
                public_manifest = {k: v for k, v in manifest.items() if k != "baseline_events"}
                write_json(home / "export.json", {"protocol": PROTOCOL, "generated_at": now().isoformat(),
                                                  "manifest": public_manifest, "report": result})
            finally:
                source.close()
                store.db.close()
        except Exception as error:
            health.update(state="error", error_class=type(error).__name__,
                          error_code=str(error) if type(error) is EvidenceError else None)
        write_json(home / "health.json", health)


if __name__ == "__main__":
    cycle()
