"""Ladder outliers, a forward paper test (RESEARCH_LOG.md, 2026-11-26,
"Ladder outliers, a forward paper test"). Paper only: nothing reaches Kalshi.

Every hour, for open NBA points, rebounds, assists and threes markets: fit
logit(mid) = a - b x strike to each ladder (one player, stat and game; 4+
two-sided strikes). A strike 3+ cents above the curve gets one paper NO bid of
1 contract one cent inside, resting one hour before tip-off; strikes within
1 cent of the curve get the same order as a control. Fills come from Kalshi's
public trades, settlement from Kalshi's result.

    python -m live.paper_ladder --due
    python -m live.paper_ladder

Ledger: outputs/paper_ladder/orders.csv; scorecard.json beside it.
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

OUT = Path("outputs/paper_ladder")
SERIES = ("KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT")
# --- the plan, fixed before any order -------------------------------------------
MIN_STRIKES = 4
OUTLIER, CONTROL = 0.03, 0.01
REST_SECONDS = 3600
TIP_BEFORE_OCCURRENCE_HOURS = 3
QUEUE, HAIRCUT = 5, 0.02
PASS_FILLS, PASS_GAMES, PASS_T = 300, 60, 2.0
EARLY_FILLS, EARLY_CENTS = 150, -5.0
MIN_MINUTES_BETWEEN = 50
TICK = 0.01
COLUMNS = ["group", "placed_utc", "placed_ts", "cancel_ts", "tip_utc", "series", "ladder",
           "game", "ticker", "floor_strike", "yes_bid", "yes_ask", "mid", "fitted", "resid",
           "improved", "price", "yes_level", "status", "traded", "result", "profit"]  # fmt: skip


def due(now, path, minutes=MIN_MINUTES_BETWEEN):
    try:
        last = datetime.fromisoformat(path.read_text("utf-8").strip())
    except (OSError, ValueError):
        return True
    return (now - last).total_seconds() >= minutes * 60


def ladder_quotes(markets, now):
    """Two-sided, pre-game strikes with ladder key, tip-off and residual."""
    import numpy as np
    import pandas as pd

    m = pd.DataFrame(markets)
    if m.empty:
        return m
    for c in ("yes_bid_dollars", "yes_ask_dollars", "floor_strike"):
        m[c] = pd.to_numeric(m.get(c), errors="coerce")
    m["yes_bid"], m["yes_ask"] = m.yes_bid_dollars, m.yes_ask_dollars
    occ = pd.to_datetime(
        m.get("occurrence_datetime"), utc=True, format="ISO8601", errors="coerce"
    )
    exp = pd.to_datetime(
        m.get("expected_expiration_time"), utc=True, format="ISO8601", errors="coerce"
    )
    m["tip"] = occ.fillna(exp) - pd.Timedelta(hours=TIP_BEFORE_OCCURRENCE_HOURS)
    now = pd.Timestamp(now)
    ok = (
        (m.yes_bid > 0) & (m.yes_ask < 1) & (m.yes_ask > m.yes_bid)
        & m.floor_strike.notna()
        & (m.tip >= now + pd.Timedelta(seconds=REST_SECONDS))
    )  # fmt: skip
    m = m[ok].copy()
    m["ladder"] = m.ticker.str.rsplit("-", n=1).str[0]
    m["game"] = m.ticker.str.split("-").str[1]
    m["mid"] = (m.yes_bid + m.yes_ask) / 2
    m["fitted"], m["resid"] = np.nan, np.nan
    for _, idx in m.groupby("ladder").groups.items():
        if len(idx) < MIN_STRIKES:
            continue
        x = m.loc[idx, "floor_strike"].to_numpy(float)
        y = np.clip(m.loc[idx, "mid"].to_numpy(float), 0.01, 0.99)
        if np.ptp(x) == 0:
            continue
        slope, intercept = np.polyfit(x, np.log(y / (1 - y)), 1)
        fit = 1 / (1 + np.exp(-(intercept + slope * x)))
        m.loc[idx, "fitted"], m.loc[idx, "resid"] = fit, y - fit
    return m.dropna(subset=["resid"])


def new_orders(q, ledger, now, series):
    import numpy as np
    import pandas as pd

    if q.empty or "ticker" not in q:
        return pd.DataFrame(columns=COLUMNS)
    q = q[~q.ticker.isin(set(ledger.ticker))].copy()
    q["group"] = np.select(
        [q.resid >= OUTLIER - 1e-9, q.resid.abs() <= CONTROL + 1e-9],
        ["outlier", "control"],
        "",
    )
    q = q[q.group != ""]
    if q.empty:
        return pd.DataFrame(columns=COLUMNS)
    spread = (q.yes_ask - q.yes_bid).round(4)
    q["improved"] = spread >= 2 * TICK - 1e-9
    q["price"] = np.round(np.where(q.improved, 1 - q.yes_ask + TICK, 1 - q.yes_ask), 4)
    q["yes_level"] = np.round(1 - q.price, 4)
    q = q[(q.price > 0) & (q.price < 1)]
    now = pd.Timestamp(now)
    q["placed_utc"] = now.isoformat(timespec="minutes")
    q["placed_ts"] = int(now.timestamp())
    q["cancel_ts"] = int(now.timestamp()) + REST_SECONDS
    q["tip_utc"] = q.tip.dt.strftime("%Y-%m-%dT%H:%MZ")
    q["series"] = series
    q["status"] = "resting"
    for c in ("traded", "result", "profit"):
        q[c] = None
    for c in ("mid", "fitted", "resid"):
        q[c] = q[c].round(4)
    return q[COLUMNS]


def check(ledger, fetch_trades, now_ts):
    """Contracts traded through each finished order's NO bid."""
    import pandas as pd

    from kalshi.maker import fills

    ledger = ledger.copy()
    ledger["status"] = ledger.status.astype(object)
    for i in ledger.index[(ledger.status == "resting") & (ledger.cancel_ts <= now_ts)]:
        row = ledger.loc[i]
        raw = fetch_trades(row.ticker, int(row.placed_ts), int(row.cancel_ts)) or []
        traded = 0.0
        if raw:
            t = pd.DataFrame(raw)
            t["ticker"] = row.ticker
            stamp = pd.to_datetime(t.created_time, utc=True, format="ISO8601")
            t["ts"] = (stamp - pd.Timestamp(0, tz="UTC")).dt.total_seconds()
            placed = pd.DataFrame([{"ticker": row.ticker, "end_ts": int(row.placed_ts),
                                    "tip_ts": int(row.cancel_ts), "side": "no",
                                    "yes_level": float(row.yes_level),
                                    "improved": str(row.improved).lower() == "true"}])  # fmt: skip
            traded = float(fills(placed, t).get(row.ticker, 0.0))
        ledger.at[i, "traded"] = traded
        ledger.at[i, "status"] = "filled" if traded >= 1 else "unfilled"
    return ledger


def settle(ledger, fetch_market):
    from kalshi.maker import maker_fee

    ledger = ledger.copy()
    ledger["status"] = ledger.status.astype(object)
    ledger["result"] = ledger.result.astype(object)
    for i in ledger.index[ledger.status == "filled"]:
        market = fetch_market(ledger.at[i, "ticker"])
        if not market or market.get("result") not in {"yes", "no"}:
            continue
        price = float(ledger.at[i, "price"])
        won = 1.0 if market["result"] == "no" else 0.0
        ledger.at[i, "result"] = market["result"]
        ledger.at[i, "profit"] = round(won - price - float(maker_fee(price)), 4)
        ledger.at[i, "status"] = "settled"
    return ledger


def run(now, fetch_markets, fetch_trades, fetch_market, ledger, sleep=time.sleep):
    import pandas as pd

    ledger = check(ledger, fetch_trades, int(now.timestamp()))
    ledger = settle(ledger, fetch_market)
    seen = {}
    for series in SERIES:
        try:
            markets = fetch_markets(series, status="open", historical=False)
        except OSError as error:
            seen[series] = {"error": str(error)[:80]}
            continue
        q = ladder_quotes(markets, now)
        posted = new_orders(q, ledger, now, series)
        if len(posted):
            ledger = pd.concat([ledger, posted], ignore_index=True)[COLUMNS]
        seen[series] = {"open": len(markets), "fitted_strikes": int(len(q)),
                        "ladders": int(q.ladder.nunique()) if len(q) else 0,
                        "posted_outlier": int((posted.group == "outlier").sum()) if len(posted) else 0,
                        "posted_control": int((posted.group == "control").sum()) if len(posted) else 0}  # fmt: skip
        sleep(0.05)
    return ledger, seen


def summarize(ledger, group, queue):
    import numpy as np
    import pandas as pd

    from kalshi.stats import clustered_mean_t

    s = ledger[(ledger.group == group) & (ledger.status == "settled")].copy()
    s["traded"] = pd.to_numeric(s.traded, errors="coerce").fillna(0)
    s["profit"] = pd.to_numeric(s.profit, errors="coerce")
    s = s[s.traded >= queue]
    out = {"fills": int(len(s)), "games": int(s.game.nunique())}
    if len(s) >= 2:
        mean, t = clustered_mean_t(s.profit.to_numpy(), s.game.astype(str).to_numpy())
        after, t_after = clustered_mean_t(
            s.profit.to_numpy() - HAIRCUT, s.game.astype(str).to_numpy()
        )
        out.update(cents=round(100 * float(mean), 2), t=round(float(t), 2) if np.isfinite(t) else None,
                   cents_after_haircut=round(100 * float(after), 2),
                   t_after_haircut=round(float(t_after), 2) if np.isfinite(t_after) else None)  # fmt: skip
    return out


def verdict(ledger):
    p = summarize(ledger, "outlier", QUEUE)
    if p["fills"] == 0:
        state = "waiting"
    elif p["fills"] >= EARLY_FILLS and p.get("cents", 0) < EARLY_CENTS:
        state = "stop (early)"
    elif p["fills"] >= PASS_FILLS and p["games"] >= PASS_GAMES:
        if p.get("cents", 0) <= 0:
            state = "stop"
        elif (
            p.get("cents_after_haircut", 0) > 0
            and (p.get("t_after_haircut") or 0) >= PASS_T
        ):
            state = "pass"
        else:
            state = "inconclusive (collect to 600)"
    else:
        state = "collecting"
    return {"state": state, "primary_queue_5": p,
            "outlier_first_in_line": summarize(ledger, "outlier", 1),
            "control_queue_5": summarize(ledger, "control", QUEUE),
            "orders": ledger.group.value_counts().to_dict()}  # fmt: skip


def main(argv=None, out=OUT):
    argv = sys.argv[1:] if argv is None else argv
    out = Path(out)
    last_run = out / "last_run.txt"
    now = datetime.now(UTC)
    if "--due" in argv:
        print("due" if due(now, last_run) else "not due")
        return 0
    import pandas as pd

    from kalshi.api import fetch_market, fetch_markets, fetch_trades

    path = out / "orders.csv"
    ledger = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=COLUMNS)
    ledger, seen = run(now, fetch_markets, fetch_trades, fetch_market, ledger)
    out.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(path, index=False)
    summary = {"updated_utc": now.isoformat(timespec="minutes"),
               "kind": "PAPER (no orders sent); 1 contract per order; fills from public trades",
               "series": seen, **verdict(ledger)}  # fmt: skip
    (out / "scorecard.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    last_run.write_text(now.isoformat(timespec="seconds"), "utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "series"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
