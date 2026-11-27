"""Feature extraction and exploratory microstructure hypothesis diagnostics from recorder JSONL.

This is research-only: no order execution, no prediction claim, no strategy selection.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

DEFAULT_INPUT = "data/research/live_events.jsonl"
OUT = Path("outputs/microstructure_research")
HORIZONS_MIN = (5, 15)


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def price_dollars(value: Any) -> float | None:
    """Convert fixed-point dollar strings or legacy integer-cent values."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v / 100.0 if v > 1 else v


def level_pairs(levels: Any) -> list[tuple[float, float]]:
    out = []
    if not isinstance(levels, list):
        return out
    for item in levels:
        try:
            if isinstance(item, dict):
                p = price_dollars(item.get("price", item.get("price_dollars")))
                q = float(item.get("quantity", item.get("size", item.get("count", 0))))
            else:
                p = price_dollars(item[0])
                q = float(item[1])
            if p is not None and 0 <= p <= 1 and math.isfinite(q) and q >= 0:
                out.append((p, q))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def load_events(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except json.JSONDecodeError:
                print(f"[warn] ignoring malformed JSON at line {line_no}")
    return rows


def build_features(
    events: list[dict], horizons: tuple[int, ...] = HORIZONS_MIN
) -> list[dict]:
    """Build one feature row per book snapshot; targets use later observed snapshots only."""
    meta = {}
    books = defaultdict(list)
    trades = defaultdict(list)
    for e in events:
        mid = e.get("market_id")
        if not mid:
            continue
        ts = parse_ts(e.get("source_timestamp"))
        if not ts:
            continue
        kind = e.get("event_type")
        if kind == "market_snapshot":
            meta[mid] = e
        elif kind == "book_snapshot":
            yes = level_pairs(e.get("yes_bid_levels"))
            no = level_pairs(e.get("no_bid_levels"))
            yes.sort(key=lambda x: x[0], reverse=True)
            no.sort(key=lambda x: x[0], reverse=True)
            ybid = yes[0][0] if yes else None
            n_bid = no[0][0] if no else None
            yask = 1.0 - n_bid if n_bid is not None else None
            midprice = (
                (ybid + yask) / 2 if ybid is not None and yask is not None else None
            )
            row = {
                "market_id": mid,
                "event_id": e.get("event_id"),
                "timestamp": ts.isoformat(),
                "yes_bid": ybid,
                "yes_ask": yask,
                "mid": midprice,
                "spread": (yask - ybid)
                if yask is not None and ybid is not None
                else None,
                "yes_levels": yes,
                "no_levels": no,
            }
            books[mid].append(row)
        elif kind == "public_trade":
            try:
                qty = float(e.get("count_fp", e.get("count", 0)) or 0)
            except (ValueError, TypeError):
                qty = 0
            side = str(e.get("taker_outcome_side") or "").lower()
            trades[mid].append(
                {
                    "timestamp": ts,
                    "qty": qty,
                    "side": side,
                    "yes_price": price_dollars(
                        e.get("yes_price_dollars", e.get("yes_price"))
                    ),
                    "trade_id": e.get("trade_id"),
                }
            )
    result = []
    for market_id, snapshots in books.items():
        snapshots.sort(key=lambda x: x["timestamp"])
        market_trades = sorted(trades[market_id], key=lambda x: x["timestamp"])
        meta_row = meta.get(market_id, {})
        for i, s in enumerate(snapshots):
            t = parse_ts(s["timestamp"])
            close = parse_ts(meta_row.get("close_time"))
            out = {
                "market_id": market_id,
                "event_id": s.get("event_id"),
                "timestamp": s["timestamp"],
                "title": meta_row.get("title"),
                "series": meta_row.get("series_ticker", meta_row.get("series")),
                "time_to_close_minutes": ((close - t).total_seconds() / 60)
                if close
                else None,
                "yes_bid": s["yes_bid"],
                "yes_ask": s["yes_ask"],
                "mid": s["mid"],
                "spread": s["spread"],
            }
            for n in (1, 3, 5):
                out[f"yes_depth_{n}"] = sum(q for _, q in s["yes_levels"][:n])
                out[f"no_depth_{n}"] = sum(q for _, q in s["no_levels"][:n])
                yd, nd = out[f"yes_depth_{n}"], out[f"no_depth_{n}"]
                out[f"imbalance_{n}"] = (yd - nd) / (yd + nd) if yd + nd > 0 else None
            recent = [
                tr
                for tr in market_trades
                if 0 <= (t - tr["timestamp"]).total_seconds() <= 300
            ]
            out["public_trade_count_5m"] = len(recent)
            out["public_volume_5m"] = sum(tr["qty"] for tr in recent)
            yes_vol = sum(
                tr["qty"] for tr in recent if tr["side"] in ("yes", "affirmative")
            )
            no_vol = sum(tr["qty"] for tr in recent if tr["side"] in ("no", "negative"))
            out["public_yes_volume_5m"] = yes_vol
            out["public_no_volume_5m"] = no_vol
            out["public_flow_imbalance_5m"] = (
                (yes_vol - no_vol) / (yes_vol + no_vol)
                if yes_vol + no_vol > 0
                else None
            )
            for h in horizons:
                future = next(
                    (
                        f
                        for f in snapshots[i + 1 :]
                        if f["mid"] is not None
                        and (parse_ts(f["timestamp"]) - t).total_seconds() >= h * 60
                        and (parse_ts(f["timestamp"]) - t).total_seconds() <= h * 2 * 60
                    ),
                    None,
                )
                actual_gap = (
                    ((parse_ts(future["timestamp"]) - t).total_seconds() / 60)
                    if future
                    else None
                )
                out[f"mid_return_{h}m"] = (
                    future["mid"] - s["mid"]
                    if future and s["mid"] is not None
                    else None
                )
                out[f"mid_return_{h}m_observed_gap"] = actual_gap
            result.append(out)
    return result


def corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (vx * vy) ** 0.5


def diagnostics(features: list[dict]) -> list[dict]:
    specs = [
        ("imbalance_1", "mid_return_5m", "Top-level book imbalance vs 5m mid return"),
        ("imbalance_3", "mid_return_5m", "Three-level imbalance vs 5m mid return"),
        ("imbalance_5", "mid_return_5m", "Five-level imbalance vs 5m mid return"),
        (
            "public_flow_imbalance_5m",
            "mid_return_5m",
            "Trailing public trade flow vs 5m mid return",
        ),
        ("spread", "mid_return_5m", "Spread vs 5m mid return"),
        ("public_volume_5m", "mid_return_5m", "Public tape volume vs 5m mid return"),
        ("imbalance_1", "mid_return_15m", "Top-level book imbalance vs 15m mid return"),
        (
            "public_flow_imbalance_5m",
            "mid_return_15m",
            "Trailing public trade flow vs 15m mid return",
        ),
    ]
    out = []
    for feature, target, label in specs:
        pairs = [
            (float(r[feature]), float(r[target]))
            for r in features
            if r.get(feature) is not None
            and r.get(target) is not None
            and math.isfinite(float(r[feature]))
            and math.isfinite(float(r[target]))
        ]
        xs, ys = zip(*pairs) if pairs else ([], [])
        sorted_x = sorted(xs)
        if len(sorted_x) >= 6:
            lo, hi = sorted_x[len(sorted_x) // 3], sorted_x[(2 * len(sorted_x)) // 3]
            low = [y for x, y in pairs if x <= lo]
            high = [y for x, y in pairs if x >= hi]
        else:
            low, high = [], []
        out.append(
            {
                "hypothesis": label,
                "feature": feature,
                "target": target,
                "n": len(pairs),
                "pearson_r": corr(list(xs), list(ys)),
                "low_group_n": len(low),
                "low_group_mean_return": mean(low) if low else None,
                "high_group_n": len(high),
                "high_group_mean_return": mean(high) if high else None,
                "high_minus_low": (mean(high) - mean(low)) if high and low else None,
                "status": "exploratory_only; overlapping snapshots and event clustering not adjusted",
            }
        )
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(dict.fromkeys(k for row in rows for k in row.keys()))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def render_html(features: list[dict], tests: list[dict], output: Path) -> None:
    rows = []
    for d in tests:
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(d.get(k, '')))}</td>"
                for k in (
                    "hypothesis",
                    "n",
                    "pearson_r",
                    "low_group_mean_return",
                    "high_group_mean_return",
                    "high_minus_low",
                    "status",
                )
            )
            + "</tr>"
        )
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Microstructure Research</title>
<style>body{{font-family:system-ui;margin:2rem;max-width:1200px}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left;font-size:13px}}th{{background:#f3f3f3}}
.note{{background:#fff8df;padding:12px;border:1px solid #e8d69a}}</style></head><body>
<h1>Microstructure Research Diagnostics</h1><div class="note"><b>Exploratory only.</b> Returns are observed mid-price changes,
not executable P&amp;L. Snapshots overlap; event clustering, sampling and selection effects are not adjusted.
No strategy or profitability claim is made.</div>
<p>Feature rows: {len(features)} | diagnostics: {len(tests)}</p>
<table><thead><tr><th>Test</th><th>N</th><th>Pearson r</th><th>Low group mean</th><th>High group mean</th><th>High-low</th><th>Interpretation</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></body></html>"""
    output.write_text(doc, encoding="utf-8")


def run(input_path: str, out_dir: Path) -> dict:
    events = load_events(input_path)
    features = build_features(events)
    tests = diagnostics(features)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "features.csv", features)
    write_csv(out_dir / "hypothesis_diagnostics.csv", tests)
    (out_dir / "research_summary.json").write_text(
        json.dumps(
            {
                "input_records": len(events),
                "feature_rows": len(features),
                "diagnostics": tests,
                "disclaimer": "Exploratory; no inference adjusted for event clustering or overlapping horizons.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    render_html(features, tests, out_dir / "index.html")
    return {
        "input_records": len(events),
        "feature_rows": len(features),
        "diagnostic_count": len(tests),
        "output_dir": str(out_dir),
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Exploratory microstructure feature extraction from research JSONL"
    )
    p.add_argument("--input", default=DEFAULT_INPUT, help="Recorder JSONL input")
    p.add_argument("--output-dir", default=str(OUT))
    args = p.parse_args()
    stats = run(args.input, Path(args.output_dir))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
