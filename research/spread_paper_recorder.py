"""Isolated paper observer and cash reconciliation; GET-only account access."""

import fcntl
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

from research import spread_paper_study as study
from research.nba_entry_runner import public_get
from research.nba_entry_study import complete_trades
from research.spread_cash_reconciliation import reconciliation
from research.spread_entry_recorder import read_rows
from research.spread_forward_core import EvidenceError, amount, external_book, instant, normalized_orders, orders_from_journal
from research.spread_forward_recorder import (
    HOME as ORIGINAL, ENVIRONMENT, STATE, ReadOnlyAPI, Store, environment,
    journal, now, policy, write_json,
)

HOME = Path("/home/trader/spread-paper-execution")
FILES = ("spread_paper_study.py", "spread_paper_recorder.py", "spread_cash_reconciliation.py",
         "nba_entry_study.py", "nba_entry_runner.py", "spread_entry_recorder.py", "spread_entry_quality.py",
         "spread_forward_core.py", "spread_forward_recorder.py", "spread_forward_candidates.py")


def code_hash():
    return hashlib.sha256(b"".join((Path(__file__).parent / f).read_bytes() for f in FILES)).hexdigest()


def snapshot(ticker, own, get):
    requested = now()
    payload = get("/markets/" + ticker + "/orderbook", {"depth": 0})
    return {"ticker": ticker, "requested_at": requested.isoformat(), "completed_at": now().isoformat(),
            "external_book": external_book(payload, ticker, own), "valid": True}


def cycle(home=HOME, get=public_get):
    os.umask(0o077)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (home / "observer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if (home / "STOP").exists():
            return
        health = {"at": now().isoformat(), "state": "recording", "errors": []}
        previous = home / "health.json"
        if previous.exists():
            health["last_success"] = json.loads(previous.read_text()).get("last_success")
        store = source = None
        try:
            os.nice(10)
            policy()
            if not (STATE / "KILL").is_file():
                raise EvidenceError("funded_spread_pause_required")
            original_bytes = (ORIGINAL / "manifest.json").read_bytes()
            original = json.loads(original_bytes)
            original_health = json.loads((ORIGINAL / "health.json").read_text())
            if now() < instant(original["drain_end"]) and (original_health.get("state") == "error" or (now() - instant(original_health["last_success"])).total_seconds() > 300):
                raise EvidenceError("original_observer_unhealthy")
            if sum(p.stat().st_size for p in home.glob("evidence.sqlite3*")) > 500_000_000:
                raise EvidenceError("paper_disk_budget")
            store = Store(home / "evidence.sqlite3")
            source = sqlite3.connect(f"file:{ORIGINAL / 'evidence.sqlite3'}?mode=ro", uri=True, timeout=20)
            manifest = store.meta("manifest")
            events = journal()
            if not manifest:
                manifest = {"protocol": study.PROTOCOL, "start": now().isoformat(), "end": original["end"],
                            "drain_end": original["drain_end"], "implementation_hash": code_hash(),
                            "original_manifest_hash": hashlib.sha256(original_bytes).hexdigest(),
                            "excluded_prior_events": sorted(set(original["baseline_events"]) | {o["event_ticker"] for o in orders_from_journal(events).values()}),
                            "quantity": 1, "game_budget": "5.00", "max_active_markets": 8,
                            "entry_gap_limit": "0.05", "quote_lifetimes_minutes": [65, 15],
                            "profit_target": "0.10", "exit_horizons_seconds": list(study.HORIZONS),
                            "checkpoint_allowance_seconds": 60, "primary": "flow25/depth_fresh/exit/slip2",
                            "funded_pause_required": True, "automatic_live_enable": False}
                store.meta("manifest", manifest)
                write_json(home / "manifest.json", manifest)
            if manifest["implementation_hash"] != code_hash() or manifest["original_manifest_hash"] != hashlib.sha256(original_bytes).hexdigest():
                raise EvidenceError("paper_identity_changed_new_version_required")
            if now() >= instant(manifest["drain_end"]):
                health.update(state="complete", last_success=now().isoformat())
                write_json(home / "health.json", health)
                return
            state = store.meta("state") or {"rows": [], "fees": {}}
            rows, fees = state["rows"], state["fees"]
            api = ReadOnlyAPI(environment(ENVIRONMENT))
            before = normalized_orders(api.pages("/portfolio/orders", "orders", {"status": "resting"}))
            owned = orders_from_journal(events)
            if any(o["oid"] in owned for o in before):
                raise EvidenceError("resting_funded_spread_orders_present")
            # Cash polling is independent of the stopped worker and original journal.
            last_cash = store.meta("cash_at")
            if not last_cash or (now() - instant(last_cash)).total_seconds() >= 300:
                since = min(instant(o["utc"]) for o in owned.values()) - timedelta(seconds=120)
                raw = api.pages("/portfolio/fills", "fills", {"min_ts": int(since.timestamp())})
                settlements = api.pages("/portfolio/settlements", "settlements", {"min_ts": int(since.timestamp())})
                positions = api.pages("/portfolio/positions", "market_positions")
                cash = reconciliation(events, raw, settlements, positions, now())
                write_json(home / "reconciliation.json", {"protocol": "spread-cash-reconciliation-v1", "generated_at": now().isoformat(), "report": cash})
                # Raw signed evidence remains local and private; append immutable snapshots.
                store.put("signed_cash", str(time.time_ns()), {"at": now().isoformat(), "fills": raw, "settlements": settlements, "positions": positions})
                store.meta("cash_at", now().isoformat())
                health["cash_status"] = cash["status"]
            current = now()
            active = {r["ticker"] for r in rows if current <= instant(r["observe_until"])}
            admissions, reasons = [], Counter()
            if current < instant(manifest["end"]) and len(active) < 8:
                candidates = read_rows(source, "candidate", (current - timedelta(minutes=15)).isoformat(), 8000)
                latest = {}
                for c in candidates:
                    latest.setdefault(c["ticker"], c)
                known = {r["ticker"] for r in rows}
                for c in sorted(latest.values(), key=lambda x: x["ticker"]):
                    if not c.get("eligible"):
                        reasons[c.get("reason", "ineligible")] += 1
                    elif c["event_ticker"] in manifest["excluded_prior_events"]:
                        reasons["prior_funded_event"] += 1
                    elif c["ticker"] in known:
                        reasons["already_observed_market"] += 1
                    elif len(active) + len(admissions) >= 8 or len(admissions) >= 2:
                        reasons["recording_capacity"] += 1
                    else:
                        admissions.append(c)
            new_by_ticker = {c["ticker"]: c for c in admissions}
            books = []
            for ticker in sorted(active | set(new_by_ticker)):
                try:
                    b = snapshot(ticker, before, get)
                    books.append(b)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    health["errors"].append("book_" + type(error).__name__)
            after = normalized_orders(api.pages("/portfolio/orders", "orders", {"status": "resting"}))
            for b in books:
                ticker = b["ticker"]
                if [o for o in before if o["ticker"] == ticker] != [o for o in after if o["ticker"] == ticker]:
                    b["valid"] = False
                store.put("book", str(time.time_ns()), b)
                if ticker not in new_by_ticker:
                    continue
                try:
                    series = ticker.split("-")[0]
                    if series not in fees:
                        payload = get("/series/" + series, {})["series"]
                        fees[series] = payload
                    row = study.make_opportunity(new_by_ticker[ticker], b, fees[series], now())
                    used = sum(sum(amount(s["price"]) + amount(s["fee"]) for s in r["sides"].values()) for r in rows if r["game"] == row["game"])
                    cost = sum(amount(s["price"]) + amount(s["fee"]) for s in row["sides"].values())
                    if used + cost > 5:
                        reasons["game_budget"] += 1
                        continue
                    rows.append(row)
                    store.meta("state", state)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    reasons[str(error) if type(error) is EvidenceError else type(error).__name__] += 1
            # Complete history only after expiry; books were recorded prospectively.
            pending = sorted((r for r in rows if r["history_status"] != "complete" or r.get("outcome") not in ("yes", "no")), key=lambda r: r.get("checked_at", ""))
            for r in pending[:8]:
                if now() <= instant(r["expires_at"]) + timedelta(seconds=5):
                    continue
                if r.get("checked_at") and (now() - instant(r["checked_at"])).total_seconds() < 300:
                    continue
                r["checked_at"] = now().isoformat()
                try:
                    if r["history_status"] != "complete":
                        r["trades"] = complete_trades(get, r["ticker"], instant(r["quoted_at"]), instant(r["expires_at"]))
                        # Validate every trade before changing unknown execution to complete.
                        for side in ("yes", "no"):
                            study.first_fill(r, side, r["trades"], 65, "through")
                        r["history_status"] = "complete"
                    payload = get("/markets/" + r["ticker"], {})
                    if payload is None:
                        payload = get("/historical/markets/" + r["ticker"], {})
                    market = payload["market"]
                    if market["ticker"] != r["ticker"]:
                        raise EvidenceError("market_identity_mismatch")
                    if market.get("status") in ("settled", "finalized"):
                        r["outcome"] = market.get("result")
                    r.pop("error", None)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    r["error"] = type(error).__name__
                    health["errors"].append("history_or_result_" + type(error).__name__)
                store.meta("state", state)
            store.put("scan", str(time.time_ns()), {"at": now().isoformat(), "reasons": dict(reasons), "admitted": len(admissions)})
            store.meta("state", state)
            result = study.report(rows, store.values("book"), now(), manifest["end"], manifest["start"])
            cash_status = json.loads((home / "reconciliation.json").read_text())["report"]["status"]
            if cash_status != "reconciled":
                result["review_gate"]["status"] = "not_ready"
                result["review_gate"]["reasons"].append("live_cash_reconciliation_requires_review")
            if now() >= instant(manifest["drain_end"]):
                health["state"] = "complete"
            elif now() >= instant(manifest["end"]):
                health["state"] = "settlement_followup"
            health.update(last_success=now().isoformat(), cash_status=cash_status, opportunities=len(rows) * 2, active_markets=len(active), scan_reasons=dict(reasons))
            write_json(home / "export.json", {"protocol": study.PROTOCOL, "generated_at": now().isoformat(), "manifest": {k: v for k, v in manifest.items() if k != "excluded_prior_events"}, "report": result})
        except Exception as error:
            health.update(state="error", error_class=type(error).__name__, error_code=str(error) if type(error) is EvidenceError else None)
        finally:
            if store:
                store.db.close()
            if source:
                source.close()
        write_json(home / "health.json", health)


if __name__ == "__main__":
    cycle()
