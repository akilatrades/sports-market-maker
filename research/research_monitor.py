"""Generate a simple local HTML summary from recorder JSONL events."""
from __future__ import annotations
import argparse, json
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


def summarize(rows):
    counts = Counter(r.get("event_type", "unknown") for r in rows)
    by_market = defaultdict(lambda: Counter())
    for r in rows:
        market = r.get("market_id", "(unknown)")
        by_market[market][r.get("event_type", "unknown")] += 1
        if r.get("event_type") == "fill" and not r.get("public_trade"):
            by_market[market]["private_fill_count"] += 1
    return counts, by_market


def html_report(rows, output):
    counts, markets = summarize(rows)
    total = len(rows)
    rows_html = "".join(
        f"<tr><td>{market}</td><td>{c.get('market_snapshot',0)}</td><td>{c.get('book_snapshot',0)}</td>"
        f"<td>{c.get('fill',0)}</td><td>{c.get('private_fill_count',0)}</td></tr>"
        for market, c in sorted(markets.items())
    )
    cards = "".join(f"<div class='card'><b>{typ}</b><div>{num}</div></div>" for typ, num in sorted(counts.items()))
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Sports Market Research Monitor</title>
<style>body{{font:15px system-ui;margin:24px;background:#10131a;color:#e8edf4}}h1{{font-size:24px}}.cards{{display:flex;flex-wrap:wrap;gap:10px}}.card{{background:#202735;border-radius:8px;padding:14px;min-width:110px}}.card div{{font-size:22px;margin-top:6px}}table{{border-collapse:collapse;width:100%;margin-top:22px}}td,th{{border-bottom:1px solid #394150;padding:9px;text-align:left}}small{{color:#aab4c2}}</style></head>
<body><h1>Sports Market Research Monitor</h1><small>Local file report from JSONL recorder. Public trade prints are not your own fills; this dashboard does not estimate strategy profitability.</small>
<p>Records loaded: {total}</p><div class='cards'>{cards}</div><table><thead><tr><th>Market ticker</th><th>Market snapshots</th><th>Book snapshots</th><th>Public trades</th><th>Private fills</th></tr></thead><tbody>{rows_html}</tbody></table>
</body></html>"""
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(html, encoding="utf-8")
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/research/live_events.jsonl")
    p.add_argument("--output", default="outputs/research_monitor/index.html")
    args = p.parse_args()
    events = load_events(args.input)
    counts = html_report(events, args.output)
    print(f"wrote {args.output}; total events={len(events)}; types={dict(counts)}")

if __name__ == "__main__":
    main()
