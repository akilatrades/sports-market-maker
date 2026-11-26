"""Mention markets, a forward paper test (RESEARCH_LOG.md, 2026-11-24,
"Mention markets, a forward paper test"). Paper only: nothing reaches Kalshi.

Every hour: check fills and settle earlier paper orders, then rest a NO order
one cent inside the spread for one hour on every open mention market whose
expected expiration is 4 to 7 hours away (the cross-market scan's rule,
unchanged). Fills come from Kalshi's public trades; settlement from Kalshi's
result. Ledger: outputs/paper_mentions/orders.csv; scorecard beside it.

    python -m live.paper_mentions --due   # "due" or "not due" (stdlib only)
    python -m live.paper_mentions         # one run (reads Kalshi public data)
"""

import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PARSE_TIME = datetime.fromisoformat  # kept apart from the clock (tests replace it)
OUT = Path("outputs/paper_mentions")
LEDGER = OUT / "orders.csv"
LAST_RUN = OUT / "last_run.txt"
# The 105 mention series in the cross-market scan (outputs/scan), fixed
# before any paper order.
SERIES = [
    "KX60MINMENTION",
    "KXACOOPERMENTION",
    "KXALLINMENTION",
    "KXALTMANMENTION",
    "KXAMODEIMENTION",
    "KXAOCMENTION",
    "KXARMSTRONGMENTION",
    "KXATHLETEMENTION",
    "KXAWARDMENTION",
    "KXBANNONMENTION",
    "KXBERNIEMENTION",
    "KXBESSENTMTPMENTION",
    "KXBIANCOMENTION",
    "KXBIDENMENTION",
    "KXBONGINOMENTION",
    "KXBURNHAMMENTION",
    "KXCANDACEMENTION",
    "KXCFBMENTION",
    "KXCMAMENTION",
    "KXCOLBERTMENTION",
    "KXCONGRESSMENTION",
    "KXCROCKETTMENTION",
    "KXDEBATEMENTION",
    "KXDWTSMENTION",
    "KXEARNINGSMENTIONCOINBASE",
    "KXEARNINGSMENTIONCOST",
    "KXEARNINGSMENTIONEA",
    "KXEARNINGSMENTIONGS",
    "KXEARNINGSMENTIONHOOD",
    "KXEARNINGSMENTIONJPM",
    "KXEARNINGSMENTIONMU",
    "KXEARNINGSMENTIONSNOW",
    "KXEARNINGSMENTIONUBER",
    "KXENTMENTION",
    "KXFEDMENTION",
    "KXFIGHTMENTION",
    "KXFOXNEWSMENTION",
    "KXFTNMENTION",
    "KXGRIFFINMENTION",
    "KXGUTFELDMENTION",
    "KXHANNITYMENTION",
    "KXHARTMENTION",
    "KXHEARINGMENTION",
    "KXHILTONMENTION",
    "KXHOMANMENTION",
    "KXINFANTINOMENTION",
    "KXJENSENMENTION",
    "KXJOHNSONMENTION",
    "KXKAMALAMENTION",
    "KXKARDASHIANMENTION",
    "KXKHANNAMENTION",
    "KXKIMMELMENTION",
    "KXKIRKMENTION",
    "KXLASTWORDMENTION",
    "KXLATENIGHTMENTION",
    "KXLOVEISLMENTION",
    "KXMADDOWMENTION",
    "KXMAHERMENTION",
    "KXMAMDANIMENTION",
    "KXMENTION",
    "KXMINAJMENTION",
    "KXMLBMENTION",
    "KXNBAMENTION",
    "KXNCAABMENTION",
    "KXNCAAMENTION",
    "KXNEWSNATIONMENTION",
    "KXNEWSOMMENTION",
    "KXNFLMENTION",
    "KXNYCMAYORDEBATEMENTION",
    "KXNYCMDEBMENTION",
    "KXOBAMAMENTION",
    "KXPAULMENTION",
    "KXPERSONMENTION",
    "KXPOLITICSMENTION",
    "KXPORTERMENTION",
    "KXPOWELLMENTION",
    "KXPSAKIMENTION",
    "KXROGANMENTION",
    "KXRUBIOMENTION",
    "KXSCHUMERMENTION",
    "KXSCOTUSMENTION",
    "KXSECPRESSMENTION",
    "KXSHIRLEYMENTION",
    "KXSNFMENTION",
    "KXSNLMENTION",
    "KXSTARMERMENTION",
    "KXSTEYERMENTION",
    "KXSURVIVORMENTION",
    "KXSWIFTMENTION",
    "KXTALARICOMENTION",
    "KXTBPNMENTION",
    "KXTHEWEEKNIGHTMENTION",
    "KXTHREADGUYMENTION",
    "KXTNFMENTION",
    "KXTRUMPMENTION",
    "KXTRUMPMENTIONB",
    "KXUNMENTION",
    "KXVANCEMENTION",
    "KXVLADTENEVMENTION",
    "KXWALLERMENTION",
    "KXWBCMENTION",
    "KXWOMENTION",
    "KXZAKARIAMENTION",
    "KXZIWEMENTION",
    "KXZUCKMENTION",
]
# Kalshi adds and renames series, so every run also lists the series of all
# open events and adds any whose name contains MENTION (2026-11-26 addendum).
MATCH = "MENTION"
WINDOW_HOURS = (4, 7)  # the scan's window: 7 to 4 hours before expiration
NEXT_RUN_HOURS = 1  # each order rests one hour, as in the scan
MIN_MINUTES_BETWEEN = 50
PASS_CONTRACTS, PASS_EVENTS, PASS_T = 400, 40, 2.0
EARLY_STOP_CONTRACTS, EARLY_STOP_CENTS = 200, -5.0


def due(now, path=LAST_RUN, minutes=MIN_MINUTES_BETWEEN):
    try:
        last = datetime.fromisoformat(path.read_text("utf-8").strip())
    except (OSError, ValueError):
        return True
    return (now - last).total_seconds() >= minutes * 60


def open_events(get_json, max_pages=100):
    """(series ticker, event title) of every open Kalshi event, and whether
    the listing reached its end. Public market data only."""
    rows, cursor = [], ""
    for _ in range(max_pages):
        params = {"status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        page = get_json("/events", params) or {}
        for event in page.get("events") or []:
            ticker = str(event.get("series_ticker") or "")
            if ticker:
                rows.append((ticker, str(event.get("title") or "")))
        cursor = page.get("cursor") or ""
        if not cursor:
            return rows, True
    return rows, False


def discover(get_json, match=None, max_pages=60, events=None):
    """Series tickers of all open Kalshi events that ``match`` accepts (a
    substring, or a function of the ticker)."""
    match = MATCH if match is None else match
    keep = match if callable(match) else (lambda ticker: match in ticker)
    if events is None:
        events, _ = open_events(get_json, max_pages)
    return {ticker for ticker, _ in events if keep(ticker)}


SPORT_WORDS = ("NFL", "NBA", "NCAA", "CFB", "CBB", "NHL", "MLB", "SNF", "TNF", "MNF")
TALK = re.compile(r"\b(say|said|mention|announcer|broadcast|word)", re.IGNORECASE)


def sports_talk(events):
    """Open sports series whose event titles are about what gets said: the
    markets last season's mention edge came from, under any name."""
    return sorted({t for t, title in events
                   if any(w in t for w in SPORT_WORDS) and TALK.search(title)})  # fmt: skip


def why_not(markets, now, window=WINDOW_HOURS):
    """Why open markets were or were not quoted: hours to expected
    expiration and two-sided quotes."""
    hours, two_sided = [], 0
    for m in markets:
        try:
            exp = PARSE_TIME(
                str(m.get("expected_expiration_time")).replace("Z", "+00:00")
            )
            hours.append((exp - now).total_seconds() / 3600)
        except ValueError:
            pass
        try:
            bid, ask = float(m.get("yes_bid_dollars")), float(m.get("yes_ask_dollars"))
            two_sided += int(0 < bid < ask < 1)
        except (TypeError, ValueError):
            pass
    hours.sort()
    return {"two_sided": two_sided,
            "in_window": sum(window[0] <= h <= window[1] for h in hours),
            "hours_to_expiry_min": round(hours[0], 1) if hours else None,
            "hours_to_expiry_median": round(hours[len(hours) // 2], 1) if hours else None}  # fmt: skip


def run(
    now, fetch_markets, fetch_trades, fetch_market, sleep=time.sleep,
    series=None, ledger_path=None,
):  # fmt: skip
    import pandas as pd

    from kalshi.paper_markets import (
        COLUMNS,
        check_fills,
        empty_ledger,
        post_orders,
        settle,
    )

    path = LEDGER if ledger_path is None else ledger_path
    ledger = pd.read_csv(path) if path.exists() else empty_ledger()
    ledger = check_fills(ledger, fetch_trades, int(now.timestamp()))
    ledger = settle(ledger, fetch_market)
    seen = {}
    for name in SERIES if series is None else series:
        try:
            markets = fetch_markets(name, status="open", historical=False)
        except OSError as error:
            seen[name] = {"error": str(error)[:80]}
            continue
        posted = post_orders(
            name, markets, ledger, now,
            next_run_hours=NEXT_RUN_HOURS, window=WINDOW_HOURS,
        )  # fmt: skip
        if len(posted):
            ledger = pd.concat([ledger, posted], ignore_index=True)[COLUMNS]
        if markets or len(posted):
            seen[name] = {"open": len(markets), "posted": int(len(posted)),
                          **why_not(markets, now)}  # fmt: skip
        sleep(0.05)
    return ledger, seen


def verdict(ledger, pass_events=PASS_EVENTS):
    """The plan's bar on settled paper orders, pooled across series."""
    import numpy as np
    import pandas as pd

    from kalshi.stats import clustered_mean_t

    s = ledger[ledger.status == "settled"].copy()
    s["contracts"] = pd.to_numeric(s.filled_contracts, errors="coerce").fillna(0)
    s["profit"] = pd.to_numeric(s.profit, errors="coerce").fillna(0)
    s = s[s.contracts > 0]
    out = {"settled_orders": int(len(s)), "contracts": int(s.contracts.sum()),
           "events": int(s.event_ticker.nunique()), "dollars": round(float(s.profit.sum()), 2)}  # fmt: skip
    if s.contracts.sum() == 0:
        return {**out, "state": "waiting"}
    values = np.repeat((s.profit / s.contracts).to_numpy(), s.contracts.astype(int))
    clusters = np.repeat(s.event_ticker.to_numpy(), s.contracts.astype(int))
    mean, t = (
        clustered_mean_t(values, clusters)
        if len(values) > 1
        else (values.mean(), float("nan"))
    )
    out["cents_per_contract"] = round(100 * float(mean), 2)
    out["t"] = round(float(t), 2) if np.isfinite(t) else None
    if (
        out["contracts"] >= EARLY_STOP_CONTRACTS
        and out["cents_per_contract"] < EARLY_STOP_CENTS
    ):
        out["state"] = "stop (early)"
    elif out["contracts"] >= PASS_CONTRACTS and out["events"] >= pass_events:
        out["state"] = (
            "pass"
            if (mean > 0 and (out["t"] or 0) >= PASS_T)
            else ("stop" if mean <= 0 else "inconclusive")
        )
    else:
        out["state"] = "collecting"
    return out


def main(argv=None, out=None, fixed=None, match=None, pass_events=PASS_EVENTS):
    argv = sys.argv[1:] if argv is None else argv
    out = OUT if out is None else Path(out)
    last_run = out / "last_run.txt"
    now = datetime.now(UTC)
    if "--due" in argv:
        print("due" if due(now, last_run) else "not due")
        return 0
    from kalshi.api import fetch_market, fetch_markets, fetch_trades, get_json

    fixed = SERIES if fixed is None else fixed
    try:
        events, complete = open_events(get_json)
    except OSError:
        events, complete = [], False
    found = discover(get_json, match, events=events)
    series = sorted(set(fixed) | found)
    ledger, seen = run(now, fetch_markets, fetch_trades, fetch_market,
                       series=series, ledger_path=out / "orders.csv")  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(out / "orders.csv", index=False)
    summary = {"updated_utc": now.isoformat(timespec="minutes"),
               "series_checked": len(series), "series_found_open": len(found),
               "open_events_listed": len(events), "open_events_complete": complete,
               "sports_talk_series_open": sports_talk(events),
               "series_added_since_plan": sorted(found - set(fixed)),
               "series_with_markets": seen,
               "kind": "PAPER (no orders sent); fills from public trades, first in line", **verdict(ledger, pass_events)}  # fmt: skip
    (out / "scorecard.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    last_run.write_text(now.isoformat(timespec="seconds"), "utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "series_with_markets"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
