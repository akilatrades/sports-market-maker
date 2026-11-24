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
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

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


def run(now, fetch_markets, fetch_trades, fetch_market, sleep=time.sleep):
    import pandas as pd

    from kalshi.paper_markets import (
        COLUMNS,
        check_fills,
        empty_ledger,
        post_orders,
        settle,
    )

    ledger = pd.read_csv(LEDGER) if LEDGER.exists() else empty_ledger()
    ledger = check_fills(ledger, fetch_trades, int(now.timestamp()))
    ledger = settle(ledger, fetch_market)
    seen = {}
    for series in SERIES:
        try:
            markets = fetch_markets(series, status="open", historical=False)
        except OSError as error:
            seen[series] = {"error": str(error)[:80]}
            continue
        posted = post_orders(
            series, markets, ledger, now,
            next_run_hours=NEXT_RUN_HOURS, window=WINDOW_HOURS,
        )  # fmt: skip
        if len(posted):
            ledger = pd.concat([ledger, posted], ignore_index=True)[COLUMNS]
        if markets or len(posted):
            seen[series] = {"open": len(markets), "posted": int(len(posted))}
        sleep(0.05)
    return ledger, seen


def verdict(ledger):
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
    elif out["contracts"] >= PASS_CONTRACTS and out["events"] >= PASS_EVENTS:
        out["state"] = (
            "pass"
            if (mean > 0 and (out["t"] or 0) >= PASS_T)
            else ("stop" if mean <= 0 else "inconclusive")
        )
    else:
        out["state"] = "collecting"
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    now = datetime.now(UTC)
    if "--due" in argv:
        print("due" if due(now) else "not due")
        return 0
    from kalshi.api import fetch_market, fetch_markets, fetch_trades

    ledger, seen = run(now, fetch_markets, fetch_trades, fetch_market)
    OUT.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(LEDGER, index=False)
    summary = {"updated_utc": now.isoformat(timespec="minutes"), "series_with_markets": seen,
               "kind": "PAPER (no orders sent); fills from public trades, first in line", **verdict(ledger)}  # fmt: skip
    (OUT / "scorecard.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    LAST_RUN.write_text(now.isoformat(timespec="seconds"), "utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "series_with_markets"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
