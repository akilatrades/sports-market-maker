"""Generate local research coverage, market snapshots and CSV summaries from JSONL."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_events(path: str):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"[warn] skip malformed line {line_no}: {exc}")
    return rows


def price_to_dollars(price):
    if price is None:
        return None
    try:
        value = float(price)
    except (ValueError, TypeError):
        return None
    # Legacy API prices are integer cents; fixed-point dollar prices are < 1.
    return value / 100 if value > 1 else value


def top_price(levels):
    if not levels:
        return None
    try:
        return price_to_dollars(levels[0][0])
    except (IndexError, TypeError):
        return None


def summarize(rows):
    counts = Counter(r.get("event_type", "unknown") for r in rows)
    by_market = defaultdict(lambda: Counter())
    latest_market = {}
    latest_book = {}
    trade_volume = defaultdict(float)
    for r in rows:
        market = r.get("market_id", "(unknown)")
        kind = r.get("event_type", "unknown")
        by_market[market][kind] += 1
        if kind == "market_snapshot":
            latest_market[market] = r
        elif kind == "book_snapshot":
            latest_book[market] = r
        elif kind == "public_trade":
            try:
                trade_volume[market] += float(r.get("count_fp", r.get("count", 0)) or 0)
            except (TypeError, ValueError):
                pass
        elif kind == "fill" and not r.get("public_trade"):
            by_market[market]["private_fill_count"] += 1

    snapshot_rows = []
    for market in sorted(set(by_market)):
        m = latest_market.get(market, {})
        b = latest_book.get(market, {})
        yes_bid = top_price(b.get("yes_bid_levels", []))
        no_bid = top_price(b.get("no_bid_levels", []))
        yes_ask = 1 - no_bid if no_bid is not None else None
        spread = (yes_ask - yes_bid) if yes_bid is not None and yes_ask is not None else None
        snapshot_rows.append({
            "ticker": market,
            "event_ticker": m.get("event_id"),
            "title": m.get("title"),
            "status": m.get("status"),
            "close_time": m.get("close_time"),
            "last_price": m.get("last_price_dollars"),
            "market_yes_bid": m.get("yes_bid_dollars"),
            "book_yes_bid": yes_bid,
            "implied_yes_ask": yes_ask,
            "spread_dollars": spread,
            "market_snapshots": by_market[market]["market_snapshot"],
            "book_snapshots": by_market[market]["book_snapshot"],
            "public_trades": by_market[market]["public_trade"],
            "public_trade_volume": trade_volume[market],
            "private_fills": by_market[market]["private_fill_count"],
        })
    return counts, by_market, snapshot_rows


def html_report(rows, output):
    counts, _, market_rows = summarize(rows)
    total = len(rows)
    cards = "".join(
        f"<div class='card'><b>{kind}</b><div>{num}</div></div>"
        for kind, num in sorted(counts.items())
    )
    table_rows = "".join(
        "<tr>" + "".join(f"<td>{row.get(key, '')}</td>" for key in (
            "ticker", "status", "last_price", "book_yes_bid", "implied_yes_ask",
            "spread_dollars", "public_trades", "public_trade_volume",
            "market_snapshots", "book_snapshots"
        )) + "</tr>"
        for row in market_rows
    )
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Sports Market Research Monitor</title>
<style>body{{font:15px system-ui;margin:24px;background:#10131a;color:#e8edf4}}h1{{font-size:24px}}.cards{{display:flex;flex-wrap:wrap;gap:10px}}.card{{background:#202735;border-radius:8px;padding:14px;min-width:110px}}.card div{{font-size:22px;margin-top:6px}}table{{border-collapse:collapse;width:100%;margin-top:22px}}td,th{{border-bottom:1px solid #394150;padding:9px;text-align:left}}small{{color:#aab4c2}}</style></head>
<body><h1>Sports Market Research Monitor</h1><small>Read-only market data coverage. Public tape prints are not your own fills. Implied asks use the binary-market relation ask = 1 − opposite-side bid. No profitability claim.</small>
<p>Records loaded: {total}</p><div class='cards'>{cards}</div><table><thead><tr><th>Ticker</th><th>Status</th><th>Last price</th><th>YES bid</th><th>Implied YES ask</th><th>Spread ($)</th><th>Public prints</th><th>Print volume</th><th>Market obs</th><th>Book obs</th></tr></thead><tbody>{table_rows}</tbody></table>
</body></html>"""
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    csv_path = out_path.with_name("market_snapshot.csv")
    if market_rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(market_rows[0]))
            writer.writeheader()
            writer.writerows(market_rows)
    return counts, csv_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/research/live_events.jsonl")
    parser.add_argument("--output", default="outputs/research_monitor/index.html")
    args = parser.parse_args()
    events = load_events(args.input)
    counts, csv_path = html_report(events, args.output)
    print(f"wrote {args.output} and {csv_path}; records={len(events)}; types={dict(counts)}")


if __name__ == "__main__":
    main()
