"""Public-data paper recorder; never imports a trader or sends an order."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from research import nba_entry_study as study
from research.spread_forward_core import EvidenceError, instant

ROOT = Path("outputs/nba_entry_study")
ROUTE = re.compile(r"^/(?:markets/trades|historical/(?:trades|cutoff)|(?:historical/)?markets/[A-Za-z0-9_.-]+(?:/orderbook)?|series/[A-Za-z0-9_.-]+)$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EvidenceError("redirect_refused")


def public_get(path, params):
    if not ROUTE.fullmatch(path):
        raise EvidenceError("public_read_route_required")
    time.sleep(.15)
    url = "https://external-api.kalshi.com/trade-api/v2" + path
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def run(get=public_get, root=ROOT):
    at = study.utcnow()
    path = root / "state.json"
    if path.exists():
        state = json.loads(path.read_text())
        if state["manifest"]["implementation_hash"] != study.code_hash():
            raise EvidenceError("study_identity_changed_new_version_required")
    else:
        state = {"manifest": {"protocol": study.PROTOCOL, "start": at.isoformat(),
                              "end": study.END, "drain_end": study.DRAIN_END,
                              "implementation_hash": study.code_hash(), "quantity": 1,
                              "game_budget": 5, "source_max_age_seconds": 1800,
                              "entry_window_hours": [2, 6]}, "rows": []}
    rows = state["rows"]
    health = {"generated_at": at.isoformat(), "errors": [], "state": "recording"}
    if at >= instant(study.DRAIN_END):
        health["state"] = "complete"
    else:
        pending = sorted((r for r in rows if r["execution_status"] != "complete" or r["outcome_status"] != "settled"),
                         key=lambda r: (r.get("last_checked", ""), r["quoted_at"]))
        for r in pending[:40]:
            if at < instant(r["tip_utc"]):
                continue
            r["last_checked"] = study.utcnow().isoformat()
            if r["execution_status"] != "complete":
                try:
                    trades = study.complete_trades(get, r["ticker"], instant(r["quoted_at"]), instant(r["tip_utc"]))
                    r["execution"] = study.execution(r, trades)
                    r["execution_status"] = "complete"
                    r.pop("execution_error", None)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    r["execution_status"] = "unknown"
                    r["execution_error"] = type(error).__name__
                    health["errors"].append("trade_history_" + type(error).__name__)
            if r["outcome_status"] != "settled":
                try:
                    payload = get("/markets/" + r["ticker"], {})
                    if payload is None:
                        payload = get("/historical/markets/" + r["ticker"], {})
                    if not isinstance(payload, dict) or not isinstance(payload.get("market"), dict):
                        raise EvidenceError("market_result_unavailable")
                    market = payload["market"]
                    if market.get("ticker") != r["ticker"]:
                        raise EvidenceError("market_identity_mismatch")
                    if market.get("status") in ("settled", "finalized") and market.get("result") in ("yes", "no"):
                        r.update(outcome_status="settled", result=market["result"],
                                 result_observed_at=study.utcnow().isoformat())
                except (OSError, ValueError, KeyError, TypeError) as error:
                    health["errors"].append("settlement_" + type(error).__name__)
            study.save(path, state)
        if at < instant(study.END):
            projection = Path("outputs/projections/latest.csv")
            candidates = study.eligible(study.load_csv(projection), study.utcnow())
            slots = {r["slot"] for r in rows}
            fees = {}
            used = {}
            for r in rows:
                used[r["game_id"]] = used.get(r["game_id"], 0) + r["price"] + r["fee_upper_estimate"]
            attempted = 0
            for r in candidates:
                slot = "|".join(r[k] for k in ("game_id", "player_id", "stat"))
                if slot in slots or used.get(r["game_id"], 0) >= 5 or attempted >= 40:
                    continue
                attempted += 1
                try:
                    series = r["ticker"].split("-")[0]
                    if series not in fees:
                        fees[series] = get("/series/" + series, {})["series"]
                    requested = study.utcnow()
                    book = get("/markets/" + r["ticker"] + "/orderbook", {"depth": 0})
                    completed = study.utcnow()
                    entry = study.opportunity(r, book, fees[series], completed)
                    entry["book_request_at"] = requested.isoformat()
                    entry["book_response_at"] = completed.isoformat()
                    cost = entry["price"] + entry["fee_upper_estimate"]
                    if used.get(r["game_id"], 0) + cost > 5 + 1e-9:
                        continue
                    used[r["game_id"]] = used.get(r["game_id"], 0) + cost
                    slots.add(slot)
                    rows.append(entry)
                    study.save(path, state)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    health["errors"].append("entry_" + type(error).__name__)
            health.update(eligible_candidates=len(candidates), attempted_candidates=attempted)
        else:
            health["state"] = "settlement_followup"
    study.save(path, state)
    study.save(root / "latest.json", {"manifest": state["manifest"], "health": health, "report": study.report(rows)})
    historical = Path("outputs/paper_maker/orders.csv")
    if historical.exists():
        study.save(root / "historical_audit.json", {"generated_at": at.isoformat(), **study.audit(study.load_csv(historical))})
    print("NBA_ENTRY_RESEARCH=" + health["state"] + "; errors=" + str(len(health["errors"])))


if __name__ == "__main__":
    run()
