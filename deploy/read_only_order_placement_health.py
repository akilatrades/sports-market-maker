#!/usr/bin/env python3
"""Owner-approved, offline-only diagnostic of funded worker *local* state.

Executed as unprivileged trader over pinned SSH. No Kalshi API calls, reads of
private env files, or writes. Print whitelisted status codes and counters
only. Avoid revealing orders, balances, positions, secrets, or tickers in
public GitHub Actions logs.
"""
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def show_systemd(unit):
    try:
        call = subprocess.run(
            ["systemctl", "show", unit, "--no-pager", "--property",
             "LoadState,ActiveState,SubState,Result,ExecMainStatus,LastTriggerUSec,NextElapseUSecRealtime"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        values = {}
        for line in call.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k in ("LoadState", "ActiveState", "SubState", "Result",
                         "ExecMainStatus", "LastTriggerUSec", "NextElapseUSecRealtime"):
                    values[k] = v[:90]
        return values or {"state": "unknown"}
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "unreadable"}


def safe_time(value):
    if not value:
        return "unavailable", None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if d.tzinfo is None:
            return "undated", None
        hours = (datetime.now(timezone.utc) - d).total_seconds() / 3600
        return d.astimezone(timezone.utc).isoformat(), round(hours, 2)
    except (ValueError, TypeError):
        return "invalid", None


def numerical_counts(data):
    if not isinstance(data, dict):
        return {}
    result = {}
    for key, value in data.items():
        # Prevent free-form strings, tickers, player names or untrusted data
        # from being printed to a public workflow log.
        if isinstance(value, bool):
            result[str(key)[:65]] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            result[str(key)[:65]] = value
    return dict(list(sorted(result.items()))[:35])



def classify_recent_failure(sport):
    """Return only a whitelisted error class from local systemd logs.

    Never print actual traces, account ids, tickers, prices, or secrets.
    This is a read-only local journal lookup; no exchange API is called.
    """
    unit=f"market-maker-prod-{sport}-auto.service"
    try:
        process=subprocess.run(
            ["journalctl", "-u", unit, "--since", "25 minutes ago",
             "--no-pager", "-o", "cat", "-n", "300"],
            text=True, capture_output=True, timeout=12, check=False)
        if process.returncode!=0:
            return {"log_access":"denied_or_unavailable"}
        text=process.stdout.lower()
        signatures=[
            ("unowned fill on pilot market", "manual_or_unowned_fill"),
            ("foreign fill in an owned nba market", "manual_or_unowned_fill"),
            ("unowned or wrong-side account position", "unowned_or_wrong_side_position"),
            ("held inventory exceeds accepted intent", "held_inventory_mismatch"),
            ("unowned resting order", "unowned_resting_order"),
            ("foreign resting", "unowned_resting_order"),
            ("unreconciled shared active capacity", "shared_capacity_reconciliation"),
            ("spread fill direction disagrees with journal", "spread_fill_mismatch"),
            ("spread fill price disagrees with journal", "spread_fill_mismatch"),
            ("unaccountable spread settlement", "settlement_mismatch"),
            ("spread settlement disagrees with its fills", "settlement_mismatch"),
            ("ambiguous production order", "unreconciled_ambiguous_order"),
            ("unreconciled production submission", "unreconciled_submission"),
            ("position appeared for reconciled rejected order", "position_after_rejection"),
            ("unowned", "other_unowned_activity"),
        ]
        found=[label for needle,label in signatures if needle in text]
        return {"log_access":"ok",
                "recognized_failure_categories":sorted(set(found)),
                "trading_error_observed":"tradingerror" in text,
                "last_25m_lookback":True}
    except (OSError,subprocess.TimeoutExpired):
        return {"log_access":"unavailable"}

def local_report(sport):
    root = Path("/home/trader") / f"prod-{sport}-auto"
    result = {
        "state_directory_present": root.is_dir(),
        "kill_switch_present": os.path.lexists(str(root / "KILL")),
    }
    path = root / "last_scan.json"
    if path.is_file():
        try:
            scan = json.loads(path.read_text())
            when = scan.get("run_utc") or scan.get("utc")
            result["scan_utc"], result["scan_age_hours"] = safe_time(when)
            if scan.get("mode") in ("live", "shadow", "dry"):
                result["scan_mode"] = scan["mode"]
            decision = scan.get("decision")
            if isinstance(decision, str):
                result["scan_decision"] = decision[:75]
            for k in ("candidate_count", "orders_placed_this_pass",
                      "resting_order_count", "legacy_prior_version_resting_orders",
                      "gross_reserved"):
                if k in scan and type(scan[k]) in (int, float):
                    result[k] = scan[k]
            for key in ("selection_funnel", "skipped", "filters", "skip_reasons"):
                if key in scan:
                    result[key] = numerical_counts(scan[key])
            live = scan.get("live")
            if isinstance(live, dict):
                result["live_decision"] = str(live.get("decision", "unknown"))[:75]
                result["live_counters"] = numerical_counts(live)
                if live.get("decision") == "halt":
                    error = str(live.get("error") or "")
                    # Only classify the error; it may contain private
                    # exchange account or position information.
                    categories = (
                        ("Ambiguous", "ambiguous_submission"),
                        ("reconcil", "reconciliation"),
                        ("loss_stop", "loss_stop"),
                        ("HALT", "safety_halt"),
                        ("SHARD", "shard_routing"),
                        ("HTTP", "exchange_http"),
                    )
                    result["halt_category"] = next(
                        (name for needle, name in categories if needle in error),
                        "other")
        except (OSError, ValueError, TypeError):
            result["scan_status"] = "unreadable"
    else:
        result["scan_status"] = "missing"

    events_path = root / "journal.jsonl"
    if events_path.is_file():
        summary = Counter()
        recent = Counter()
        try:
            for raw in events_path.open():
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                kind = event.get("event")
                if kind not in ("intent", "accepted", "unknown_outcome",
                                "rejected_4xx", "fill", "canceled", "cancel",
                                "reconciled_absent"):
                    continue
                summary[kind] += 1
                _, age = safe_time(event.get("utc"))
                if age is not None and 0 <= age <= 24:
                    recent[kind] += 1
            result["journal_totals"] = dict(summary)
            result["journal_last_24h"] = dict(recent)
        except OSError:
            result["journal_status"] = "unreadable"
    else:
        result["journal_status"] = "missing"
    return result


def main():
    print("health_utc=" + datetime.now(timezone.utc).isoformat())
    for sport in ("nba", "nfl", "spread"):
        print("COHORT=" + sport)
        for suffix in ("timer", "service"):
            unit = f"market-maker-prod-{sport}-auto.{suffix}"
            print("SYSTEMD_" + suffix.upper() + "=" +
                  json.dumps(show_systemd(unit), sort_keys=True))
        print("LOCAL_STATE=" + json.dumps(local_report(sport), sort_keys=True))
        print("FAILURE_CLASS=" + json.dumps(classify_recent_failure(sport), sort_keys=True))
    print("SPREAD_MARKER_PRESENT=" +
          str(Path("/etc/market-maker-spread.enabled").exists()).lower())


if __name__ == "__main__":
    main()
