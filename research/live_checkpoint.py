"""Grade each live bot against the checkpoint written down before it traded.

LIVE results only. Reads a local clone of the owner's PRIVATE fills export
(``tools/export_private_fills.py``; see deploy/PRIVATE_FILL_EXPORT.md) and
prints a report. It writes nothing, and refuses a data folder inside this
public repository, so private data never lands here.

    python -m research.live_checkpoint --data ~/smm-private-data

Pre-registered rules (RESEARCH_LOG.md):
- NBA v5 ("How v5 will be judged"), with v6 pooled in ("NBA rules v6": the
  same selection at 3 contracts an order): settled profit per filled
  contract after fees, game-clustered t. Checkpoint at 1,900 settled filled
  orders, the $5,000 allowance ($2,000 before v6), or 30 days from the first
  v5 order, whichever comes first. t >= 2 and positive: the
  edge is real at these settings; positive with t < 2: keep collecting;
  t <= -1: stop and review. (Not positive with t > -1 is not covered by the
  plan; the report says so and leaves it to the owner.) The allowance is
  summed as the bot sums it: every NBA order of any version, at cost plus
  its fee reserve.
- Spread maker ("Spread maker pilot ... (plan)" and the 5-contract
  amendment): after 300 filled contracts or 4 weeks, continue if live profit
  per contract is above zero; stop and review if the -$40 total stop is hit
  (checked at any time, on the bot's own realized ledger from the export) or
  live fills are less than half the shadow's (read here as the measured
  fill share below 0.5 of the first-in-line contracts; see the fill-share
  amendment in RESEARCH_LOG.md).
- NFL: no checkpoint of its own; reported for completeness.
"""

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from research.fill_sizing_replay import clustered_mean_t

ROOT = Path(__file__).resolve().parents[1]
# NBA review (RESEARCH_LOG.md, 2026-10-23, "NBA rules v6"): v6 keeps v5's
# selection and pricing and only trades 3 contracts an order, so v5 and v6 are
# judged together from the first v5 order and also reported apart. The bar
# counts settled filled ORDERS (at one contract an order, v5's fills and
# contracts were the same); the allowance bar follows the allowance
# ($2,000 -> $5,000).
NBA_VERSIONS = ("nba-no-v5-one-contract-breadth", "nba-no-v6-three-contracts")
NBA_VERSION = NBA_VERSIONS[-1]  # the bot's current rules
NBA_BARS = {"settled_fills": 1900, "allowance_dollars": 5000.0, "days": 30}
NBA_FEE_RESERVE = 1.10  # live/prod_nba_auto.py FEE_RESERVE
# Each spread rule version is judged on its own orders, the current one (v3,
# RESEARCH_LOG.md, 2026-10-23, "Spread maker v3") with the v2 bars; earlier
# versions are reported apart.
SPREAD_VERSION = "spread-maker-v3-24h-starts"
SPREAD_BARS = {
    "filled_contracts": 300,
    "days": 28,
    "total_stop": 40.0,
    "fill_share": 0.5,
}


def _read(folder, kind):
    files = sorted((folder / kind).glob("*.csv")) if (folder / kind).exists() else []
    frames = [pd.read_csv(f, low_memory=False) for f in files]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _stats(values, weights, clusters):
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    if weights.sum() <= 0 or len(values) == 0:
        return None, None, 0
    mean, t = clustered_mean_t(values, weights, np.asarray(clusters))
    clusters_n = len(set(np.asarray(clusters)[weights > 0]))
    return (
        100 * float(mean),
        (None if t is None or np.isnan(t) else float(t)),
        clusters_n,
    )


def _reserve(cost):
    """The NBA bot's charge against its allowance (``prod_nba_auto.reserve``)."""
    return math.ceil(round(float(cost), 4) * NBA_FEE_RESERVE * 100 - 1e-8) / 100


def _days(first, now):
    if first is None or pd.isna(first):
        return 0.0
    return (now - first).total_seconds() / 86400


def no_bot(folder, now, version=None):
    """NBA or NFL: settled profit per filled contract, clustered by game."""
    orders, fills, settled = (
        _read(folder, k) for k in ("orders", "fills", "settlements")
    )
    if orders.empty:
        return {"orders": 0}
    # The bot charges every order in its journal, of any version, to the
    # allowance, filled or not.
    costs = pd.to_numeric(orders.cost, errors="coerce").dropna()
    allowance = round(float(sum(_reserve(c) for c in costs if c >= 0)), 2)
    if version is not None:
        wanted = {version} if isinstance(version, str) else set(version)
        orders = orders[orders.strategy_version.isin(wanted)]
        if orders.empty:
            return {"orders": 0}
        fills = (
            fills[fills.order_ref.isin(orders.order_ref)] if not fills.empty else fills
        )
    orders["intent_utc"] = pd.to_datetime(orders.intent_utc, utc=True, errors="coerce")
    tickers = set(orders.ticker)
    settled = settled[settled.ticker.isin(tickers)] if not settled.empty else settled
    settled = (
        settled[settled.accounting_complete.astype(str).eq("True")]
        if not settled.empty
        else settled
    )
    contracts = (
        fills.assign(count=pd.to_numeric(fills["count"], errors="coerce"))
        .groupby("ticker")["count"]
        .sum()
        if not fills.empty
        else pd.Series(dtype=float)
    )
    game = orders.drop_duplicates("ticker").set_index("ticker").game_id
    rows = []
    for _, s in settled.iterrows():
        n = float(contracts.get(s.ticker, 0.0))
        if n <= 0:
            continue
        rows.append((float(s.net_profit_dollars) / n, n, game.get(s.ticker)))
    cents, t, games = _stats(*zip(*rows)) if rows else (None, None, 0)
    settled_tickers = {
        s.ticker
        for _, s in settled.iterrows()
        if float(contracts.get(s.ticker, 0.0)) > 0
    }
    # Filled orders from the same fills table the contracts come from.
    filled_refs = (
        set(
            fills.loc[
                (pd.to_numeric(fills["count"], errors="coerce") > 0)
                & fills.ticker.isin(settled_tickers),
                "order_ref",
            ]
        )
        if not fills.empty
        else set()
    )
    return {
        "orders": len(orders),
        "accepted": int((orders.status == "accepted").sum()),
        "filled_orders": int(
            (pd.to_numeric(orders.filled_contracts, errors="coerce") > 0).sum()
        ),
        "settled_markets": len(rows),
        # Filled orders whose market settled: one per order however many
        # contracts or pieces it filled in (the review's 1,900 bar).
        "settled_fills": len(filled_refs),
        "settled_contracts": float(sum(r[1] for r in rows)),
        "net_profit_dollars": round(float(sum(r[0] * r[1] for r in rows)), 2),
        "cents_per_contract": cents,
        "t_game_clustered": t,
        "games": games,
        "allowance_used_dollars": allowance,
        "days": round(_days(orders.intent_utc.min(), now), 1),
    }


def spread_bot(folder, now, summary, version=SPREAD_VERSION):
    """Spread maker: realized P&L per filled contract from its own fills,
    after fees (pairs at the second fill, held contracts at settlement),
    clustered by event, plus the measured fill share. Contracts still held
    in an unresolved market are left out until it resolves; pairs already
    closed in it count."""
    orders, fills, settled = (
        _read(folder, k) for k in ("orders", "fills", "settlements")
    )
    if orders.empty:
        return {"orders": 0}
    earlier = {}
    if version is not None and "strategy_version" in orders:
        mine = orders.strategy_version.eq(version)
        other = orders[~mine]
        if len(other):
            other_fills = (
                fills[fills.order_ref.isin(other.order_ref)]
                if not fills.empty
                else fills
            )
            earlier = {
                "orders": int(len(other)),
                "filled_contracts": float(
                    pd.to_numeric(other_fills.get("count"), errors="coerce").sum()
                )
                if not other_fills.empty
                else 0.0,
                "versions": sorted(
                    other.strategy_version.dropna().astype(str).unique()
                ),
            }
        orders = orders[mine]
        fills = (
            fills[fills.order_ref.isin(orders.order_ref)] if not fills.empty else fills
        )
        if orders.empty:
            return {"orders": 0, "earlier_versions": earlier}
    orders["intent_utc"] = pd.to_datetime(orders.intent_utc, utc=True, errors="coerce")
    event_of = orders.drop_duplicates("ticker").set_index("ticker").event_ticker
    result = (
        settled.drop_duplicates("ticker", keep="last").set_index("ticker").market_result
        if not settled.empty
        else pd.Series(dtype=object)
    )
    per_market, open_markets = {}, 0
    if not fills.empty:
        fee = (
            pd.to_numeric(fills["fee"], errors="coerce").fillna(0.0)
            if "fee" in fills
            else 0.0
        )
        fills = fills.assign(
            count=pd.to_numeric(fills["count"], errors="coerce"),
            price=pd.to_numeric(fills["price"], errors="coerce"),
            fee=fee,
            when=pd.to_datetime(fills.fill_utc, utc=True, errors="coerce"),
        ).sort_values(["ticker", "when", "fill_ref"])
        for ticker, rows in fills.groupby("ticker"):
            # Each lot carries its share of its fill's fee.
            lots, pnl, paired = [], 0.0, 0.0
            for r in rows.itertuples():
                left, fee_each = r.count, (r.fee / r.count if r.count else 0.0)
                while left > 1e-9 and lots and lots[0][0] != r.side:
                    side, price, count, lot_fee = lots[0]
                    m = min(left, count)
                    pnl += m * (1 - r.price - price - fee_each - lot_fee)
                    paired += 2 * m
                    left -= m
                    lots[0] = (side, price, count - m, lot_fee)
                    if lots[0][2] <= 1e-9:
                        lots.pop(0)
                if left > 1e-9:
                    lots.append((r.side, r.price, left, fee_each))
            n = paired
            if lots:
                outcome = result.get(ticker)
                if outcome in ("yes", "no"):
                    pnl += sum(c * (float(s == outcome) - p - f) for s, p, c, f in lots)
                    n += sum(c for _, _, c, _ in lots)
                else:
                    open_markets += 1  # held contracts wait; never guessed
            if n > 1e-9:
                per_market[ticker] = (pnl, n)
    rows = [
        (pnl / n, n, event_of.get(t, t)) for t, (pnl, n) in per_market.items() if n > 0
    ]
    cents, t, events = _stats(*zip(*rows)) if rows else (None, None, 0)
    spread_summary = summary.get("markets", {}).get("spread", {})
    share = spread_summary.get("live_fill_share") or {}
    ledger = spread_summary.get("realized_pnl_dollars")
    return {
        "orders": len(orders),
        "accepted": int((orders.status == "accepted").sum()),
        "filled_contracts": float(fills["count"].sum()) if not fills.empty else 0.0,
        "resolved_markets": len(rows),
        "markets_with_held_contracts_excluded": open_markets,
        "resolved_contracts": float(sum(r[1] for r in rows)),
        "net_profit_dollars": round(float(sum(r[0] * r[1] for r in rows)), 2),
        # The bot's own realized ledger, the number its loss stops use.
        "ledger_realized_dollars": (None if ledger is None else float(ledger)),
        "cents_per_contract": cents,
        "t_event_clustered": t,
        "events": events,
        "days": round(_days(orders.intent_utc.min(), now), 1),
        "earlier_versions": earlier,
        "fill_share": share.get("fill_share"),
        "cautious_replay_share": share.get("cautious_replay_share"),
        "shadow_simulated": summary.get("spread_shadow_simulated"),
    }


def nba_verdict(r):
    progress = {
        "settled filled orders": f"{r['settled_fills']:,g} / {NBA_BARS['settled_fills']:,}",
        "allowance": f"${r['allowance_used_dollars']:,.0f} / ${NBA_BARS['allowance_dollars']:,.0f}",
        "days": f"{r['days']} / {NBA_BARS['days']}",
    }
    reached = (
        r["settled_fills"] >= NBA_BARS["settled_fills"]
        or r["allowance_used_dollars"] >= NBA_BARS["allowance_dollars"]
        or r["days"] >= NBA_BARS["days"]
    )
    c, t = r.get("cents_per_contract"), r.get("t_game_clustered")
    if not reached:
        verdict = "Checkpoint not reached: no conclusion yet (fewer observations = inconclusive, not failed)."
    elif c is None:
        verdict = (
            "Checkpoint reached but no settled contracts to judge: review the data."
        )
    elif t is None:
        verdict = (
            "Checkpoint reached but the game-clustered t cannot be computed "
            "(too few games): review the data."
        )
    elif c > 0 and t >= 2:
        verdict = "Checkpoint reached: positive with t >= 2, the edge is real at these settings."
    elif t <= -1:
        verdict = "Checkpoint reached: t <= -1, stop and review."
    elif c > 0:
        verdict = "Checkpoint reached: positive but t < 2, keep collecting."
    else:
        verdict = (
            "Checkpoint reached: not positive but t > -1, a case the plan's rules "
            "do not cover; the owner decides."
        )
    return progress, verdict


def spread_verdict(r):
    progress = {
        "filled contracts": f"{r['filled_contracts']:,.0f} / {SPREAD_BARS['filled_contracts']}",
        "days": f"{r['days']} / {SPREAD_BARS['days']}",
    }
    realized = r.get("ledger_realized_dollars")
    if realized is None:
        realized = r["net_profit_dollars"]
    if realized <= -SPREAD_BARS["total_stop"]:
        return progress, "Stop and review: the total loss stop has been reached."
    share = r.get("fill_share")
    reached = (
        r["filled_contracts"] >= SPREAD_BARS["filled_contracts"]
        or r["days"] >= SPREAD_BARS["days"]
    )
    if not reached:
        return progress, "Checkpoint not reached: no conclusion yet."
    if share is None:
        return (
            progress,
            "Checkpoint reached but the live fill share has not been measured: "
            "its bar cannot be checked; review the data.",
        )
    if share < SPREAD_BARS["fill_share"]:
        return (
            progress,
            f"Stop and review: live fill share {share:.2f} is under half the shadow's.",
        )
    c = r.get("cents_per_contract")
    if c is None:
        return (
            progress,
            "Checkpoint reached but nothing resolved to judge: review the data.",
        )
    if c > 0:
        return (
            progress,
            "Checkpoint reached: live profit per contract above zero, continue (no size change before review).",
        )
    return (
        progress,
        "Checkpoint reached: live profit per contract not above zero, stop and review.",
    )


def _fmt(value, spec="+.2f", suffix=""):
    return "—" if value is None else f"{value:{spec}}{suffix}"


def _money(value):
    return f"{'−' if value < 0 else '+'}${abs(value):,.2f}"


def report(data, now=None):
    now = now or datetime.now(UTC)
    summary_path = data / "data" / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    lines = [
        f"LIVE CHECKPOINT REPORT (real orders only) · data through "
        f"{max((m.get('data_through_utc') or '' for m in summary.get('markets', {}).values()), default='') or 'unknown'}",
        "",
    ]
    nba = no_bot(data / "data" / "nba", now, NBA_VERSIONS)
    if nba.get("orders"):
        progress, verdict = nba_verdict(nba)
        lines += [
            f"NBA ({' + '.join(NBA_VERSIONS)}, judged together)",
            f"  {nba['orders']} orders, {nba['filled_orders']} filled; {nba['settled_markets']} settled markets, "
            f"{nba['settled_contracts']:g} contracts, {nba['games']} games",
            f"  Settled P&L {_money(nba['net_profit_dollars'])}; {_fmt(nba['cents_per_contract'], '+.2f', '¢')} per contract, "
            f"t {_fmt(nba['t_game_clustered'], '.2f')} (game-clustered)",
            "  Progress: " + "; ".join(f"{k} {v}" for k, v in progress.items()),
            f"  {verdict}",
        ]
        for version in NBA_VERSIONS:
            part = no_bot(data / "data" / "nba", now, version)
            if part.get("orders"):
                lines.append(
                    f"  {version}: {part['orders']} orders, {part['settled_fills']} settled "
                    f"filled orders, {part['settled_contracts']:g} contracts, settled P&L "
                    f"{_money(part['net_profit_dollars'])}, "
                    f"{_fmt(part['cents_per_contract'], '+.2f', '¢')} per contract"
                )
        lines.append("")
    spread = spread_bot(data / "data" / "spread", now, summary)
    if spread.get("orders"):
        progress, verdict = spread_verdict(spread)
        shadow = spread.get("shadow_simulated") or {}
        first = (shadow.get("first_in_line") or {}).get("cents_per_contract")
        flow = (shadow.get("flow_share_0.25") or {}).get("cents_per_contract")
        lines += [
            f"SPREAD MAKER ({SPREAD_VERSION})",
            f"  {spread['orders']} orders, {spread['filled_contracts']:g} contracts filled; "
            f"{spread['resolved_markets']} markets with realized P&L "
            f"({spread['markets_with_held_contracts_excluded']} with contracts still held, those left out), "
            f"{spread['events']} events",
            f"  Realized P&L {_money(spread['net_profit_dollars'])} after fees; "
            f"{_fmt(spread['cents_per_contract'], '+.2f', '¢')} per contract, "
            f"t {_fmt(spread['t_event_clustered'], '.2f')} (event-clustered); bot's ledger "
            f"{'—' if spread['ledger_realized_dollars'] is None else _money(spread['ledger_realized_dollars'])}",
            f"  Live fill share {_fmt(spread['fill_share'], '.2f')} "
            f"(first in line = 1.0; cautious replay on the same orders "
            f"{_fmt(spread['cautious_replay_share'], '.2f')})",
            f"  Shadow, SIMULATED (not added to the above): {_fmt(first, '+.2f', '¢')} first in line, "
            f"{_fmt(flow, '+.2f', '¢')} at flow share 0.25",
            "  Progress: " + "; ".join(f"{k} {v}" for k, v in progress.items()),
            f"  {verdict}",
            "",
        ]
    earlier = spread.get("earlier_versions") or {}
    if earlier:
        lines += [
            f"SPREAD MAKER, earlier rules ({', '.join(earlier['versions'])}): "
            f"{earlier['orders']} orders, {earlier['filled_contracts']:g} contracts "
            "filled; reported apart and not judged (each rule version is judged on its own orders)",
            "",
        ]
    nfl = no_bot(data / "data" / "nfl", now)
    if nfl.get("orders"):
        lines += [
            "NFL (all versions; no checkpoint of its own)",
            f"  {nfl['orders']} orders; {nfl['settled_markets']} settled markets; settled P&L "
            f"{_money(nfl['net_profit_dollars'])}; {_fmt(nfl['cents_per_contract'], '+.2f', '¢')} per contract",
            "",
        ]
    lines.append(
        "Live results only. Small samples are inconclusive, not failures. Never add the "
        "shadow (simulated) line to live results."
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--data", type=Path, required=True, help="local clone of the private export"
    )
    args = parser.parse_args(argv)
    data = args.data.expanduser().resolve()
    if data == ROOT or ROOT in data.parents:
        raise SystemExit(
            "Refusing: keep the private export outside this public repository."
        )
    print(report(data))


if __name__ == "__main__":
    main()
