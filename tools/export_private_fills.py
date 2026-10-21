"""Export the bots' orders, fills and settlements to a PRIVATE GitHub repo.

Runs on the trading server from its own timer. It reads only the two bot
journals (the bots already record every order, fill, queue reading, price
move after a fill, cancel and settlement there); it makes no Kalshi request
and needs no Kalshi credentials. It writes nothing on the server.

Output: daily CSV files per market and a summary, one row per order, fill and
settled market, using an explicit list of columns. Exchange order, client
order and fill identifiers are replaced by short one-way hashes (enough to
join the files); keys, balances and account details are never in the
journals' exported columns.

Pushing is opt-in (``--push``) and goes only to the repository named in
PRIVATE_EXPORT_REPO with the token in PRIVATE_EXPORT_TOKEN (a fine-grained
token limited to that repository's contents). It refuses unless GitHub says
the repository is private, and never to the public project repository. All
files go up as one commit, and only when something changed.

Run: python -m tools.export_private_fills            (counts only, no push)
     python -m tools.export_private_fills --out DIR  (write the files locally)
     python -m tools.export_private_fills --push     (server timer)
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PUBLIC_REPO = "akilatrades/sports-market-maker"
JOURNALS = {
    "nba": Path("/home/trader/prod-nba-auto/journal.jsonl"),
    "nfl": Path("/home/trader/prod-nfl-auto/journal.jsonl"),
}
# Copied from each order's intent record, when present. Nothing else is.
INTENT_FIELDS = [
    "ticker",
    "player",
    "price_cents",
    "count",
    "cost",
    "game_id",
    "team",
    "tip_utc",
    "strategy_version",
    "model_version",
    "probability_source",
    "p_yes",
    "book_n",
    "edge",
    "baseline_edge",
    "extra_maker_ticks",
    "net_edge_after_fee_bound",
    "fee_bound_dollars",
    "model_probability_yes_at_entry",
    "sportsbook_probability_yes_at_entry",
    "kalshi_yes_bid_at_entry",
    "kalshi_yes_ask_at_entry",
    "book_updated_utc_at_entry",
    "model_generated_utc",
    "projected_minutes_at_entry",
    "projected_minutes_source_at_entry",
    "historical_minutes_baseline_at_entry",
    "lineup_confirmation_status_at_entry",
    "fee_type",
    "fee_multiplier",
]
ORDER_COLUMNS = [
    "market",
    "order_ref",
    "intent_utc",
    "side",
    *INTENT_FIELDS,
    "minutes_before_tip",
    "status",
    "accepted_utc",
    "first_queue_ahead",
    "last_queue_ahead",
    "cancel_utc",
    "cancel_reason",
    "cancel_veto",
    "filled_contracts",
    "first_fill_utc",
    "avg_fill_no_price",
    "fill_fees_dollars",
    "settled_utc",
    "settlement_net_profit_dollars",
]
MARKOUTS = [f"markout_{kind}_{h}m" for h in (5, 15, 60) for kind in ("mid", "bid")]
FILL_COLUMNS = [
    "market",
    "fill_ref",
    "order_ref",
    "fill_utc",
    "ticker",
    "side",
    "count",
    "no_price",
    "yes_price",
    "fee",
    "is_taker",
    "minutes_before_tip",
    "strategy_version",
    "probability_source",
    "price_cents",
    "edge",
    "net_edge_after_fee_bound",
    "sportsbook_probability_yes_at_entry",
    "model_probability_yes_at_entry",
    *MARKOUTS,
]
SETTLEMENT_COLUMNS = [
    "market",
    "ticker",
    "settled_utc",
    "strategy_version",
    "revenue_dollars",
    "yes_cost_dollars",
    "no_cost_dollars",
    "fee_dollars",
    "net_profit_dollars",
    "accounting_complete",
]


class ExportError(RuntimeError):
    pass


def read_events(path):
    """Journal events; a line still being written at the end is skipped."""
    if not path.exists():
        return None
    raw = path.read_text()
    lines = raw.split("\n")
    if lines and lines[-1]:  # no trailing newline yet: the writer is mid-line
        lines = lines[:-1]
    return [json.loads(line) for line in lines if line]


def ref(value):
    """A short one-way hash: joins files without exposing exchange IDs."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:12] if value else ""


def _time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else None


def _day(value):
    stamp = _time(value)
    return stamp.astimezone(ET).strftime("%Y-%m-%d") if stamp else "undated"


def _minutes(earlier, later):
    a, b = _time(earlier), _time(later)
    return round((b - a).total_seconds() / 60, 1) if a and b else ""


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tables(market, events):
    """(orders, fills, settlements) rows for one bot's journal."""
    intents, accepted_by_client, client_by_order = {}, {}, {}
    status = {}
    for e in events:
        kind = e.get("event")
        if kind == "intent" and e.get("client_order_id"):
            intents[e["client_order_id"]] = e
            status.setdefault(e["client_order_id"], "intent_only")
        elif kind == "accepted" and e.get("client_order_id"):
            accepted_by_client[e["client_order_id"]] = e
            client_by_order[str(e.get("order_id"))] = e["client_order_id"]
            status[e["client_order_id"]] = "accepted"
        elif kind == "unknown_outcome" and e.get("client_order_id"):
            status[e["client_order_id"]] = "unknown_outcome"
    queues, cancels, fills_by_client, markouts = {}, {}, {}, {}
    settlements = {}
    for e in events:
        kind = e.get("event")
        client = client_by_order.get(str(e.get("order_id")))
        if kind == "queue" and client:
            queues.setdefault(client, []).append(e.get("ahead"))
        elif kind == "cancel_intent" and client:
            cancels[client] = e
        elif kind == "fill" and client:
            fills_by_client.setdefault(client, []).append(e)
        elif kind == "markout" and e.get("fill_id"):
            markouts[(e["fill_id"], e.get("horizon_minutes"))] = e
        elif kind == "settlement" and e.get("ticker"):
            settlements[e["ticker"]] = e  # the latest record is the correction
    intent_by_ticker = {i.get("ticker"): i for i in intents.values()}
    orders = []
    for client, intent in intents.items():
        fills = fills_by_client.get(client, [])
        counts = [_number(f.get("count")) or 0 for f in fills]
        prices = [_number(f.get("no_price")) for f in fills]
        filled = sum(counts)
        paid = sum(c * p for c, p in zip(counts, prices) if p is not None)
        fees = [_number(f.get("fee")) for f in fills]
        queue = [q for q in queues.get(client, []) if q is not None]
        cancel = cancels.get(client, {})
        settled = settlements.get(intent.get("ticker"), {})
        orders.append(
            {
                "market": market,
                "order_ref": ref(client),
                "intent_utc": intent.get("utc", ""),
                "side": "no",  # both bots post passive NO orders only
                **{k: intent.get(k, "") for k in INTENT_FIELDS},
                "minutes_before_tip": _minutes(
                    intent.get("utc"), intent.get("tip_utc")
                ),
                "status": status.get(client, ""),
                "accepted_utc": accepted_by_client.get(client, {}).get("utc", ""),
                "first_queue_ahead": queue[0] if queue else "",
                "last_queue_ahead": queue[-1] if queue else "",
                "cancel_utc": cancel.get("utc", ""),
                "cancel_reason": cancel.get("reason", ""),
                "cancel_veto": cancel.get("veto", ""),
                "filled_contracts": filled,
                "first_fill_utc": min((f.get("utc", "") for f in fills), default=""),
                "avg_fill_no_price": round(paid / filled, 4) if filled else "",
                "fill_fees_dollars": round(sum(f for f in fees if f is not None), 6)
                if fills
                else "",
                "settled_utc": settled.get("utc", ""),
                "settlement_net_profit_dollars": settled.get("net_profit_dollars", ""),
            }
        )
    fill_rows = []
    for client, fills in fills_by_client.items():
        intent = intents.get(client, {})
        for f in fills:
            row = {
                "market": market,
                "fill_ref": ref(f.get("fill_id")),
                "order_ref": ref(client),
                "fill_utc": f.get("utc", ""),
                "ticker": f.get("ticker", ""),
                "side": "no",
                "count": f.get("count", ""),
                "no_price": f.get("no_price", ""),
                "yes_price": f.get("yes_price", ""),
                "fee": f.get("fee", ""),
                "is_taker": f.get("is_taker", ""),
                "minutes_before_tip": _minutes(f.get("utc"), intent.get("tip_utc")),
            }
            for k in FILL_COLUMNS:
                if k not in row:
                    row[k] = intent.get(k, "")
            for h in (5, 15, 60):
                m = markouts.get((f.get("fill_id"), h), {})
                row[f"markout_mid_{h}m"] = m.get("mid_move_dollars", "")
                row[f"markout_bid_{h}m"] = m.get("bid_move_dollars", "")
            fill_rows.append(row)
    settlement_rows = [
        {
            "market": market,
            "ticker": ticker,
            "settled_utc": s.get("utc", ""),
            "strategy_version": intent_by_ticker.get(ticker, {}).get(
                "strategy_version", ""
            ),
            **{k: s.get(k, "") for k in SETTLEMENT_COLUMNS[4:]},
        }
        for ticker, s in settlements.items()
    ]
    return orders, fill_rows, settlement_rows


def _csv(columns, rows):
    out = io.StringIO()
    writer = csv.DictWriter(
        out, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for row in sorted(
        rows, key=lambda r: tuple(str(r.get(c, "")) for c in columns[:4])
    ):
        writer.writerow({c: "" if row.get(c) is None else row.get(c) for c in columns})
    return out.getvalue()


def build_files(journals, now):
    """{path in the private repo: text}. Journals missing on disk are skipped."""
    files, summary = {}, {"as_of_utc": now.astimezone(UTC).isoformat(), "markets": {}}
    for market, path in journals.items():
        events = read_events(path)
        if events is None:
            summary["markets"][market] = {"status": "journal_missing"}
            continue
        orders, fills, settlements = tables(market, events)
        for name, columns, rows, when in (
            ("orders", ORDER_COLUMNS, orders, "intent_utc"),
            ("fills", FILL_COLUMNS, fills, "fill_utc"),
            ("settlements", SETTLEMENT_COLUMNS, settlements, "settled_utc"),
        ):
            by_day = {}
            for row in rows:
                by_day.setdefault(_day(row.get(when)), []).append(row)
            for day, day_rows in by_day.items():
                files[f"data/{market}/{name}/{day}.csv"] = _csv(columns, day_rows)
        profits = [_number(s.get("net_profit_dollars")) for s in settlements]
        versions = {}
        for o in orders:
            v = versions.setdefault(
                str(o.get("strategy_version") or "unknown"),
                {"orders": 0, "filled_orders": 0},
            )
            v["orders"] += 1
            v["filled_orders"] += 1 if o["filled_contracts"] else 0
        summary["markets"][market] = {
            "status": "ok",
            "orders": len(orders),
            "accepted_orders": sum(o["status"] == "accepted" for o in orders),
            "filled_orders": sum(1 for o in orders if o["filled_contracts"]),
            "fills": len(fills),
            "settled_markets": len(settlements),
            "settled_net_profit_dollars": round(
                sum(p for p in profits if p is not None), 2
            )
            if settlements and all(p is not None for p in profits)
            else None,
            "by_strategy_version": versions,
        }
    files["data/summary.json"] = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    files["README.md"] = README
    return files, summary


README = """# Private bot data (do not make this repository public)

Written every hour by `tools/export_private_fills.py` on the trading server,
from the two bots' journals. Never edit by hand: the next export rewrites it.

- `data/<nba|nfl>/orders/<day>.csv`: one row per order the bot submitted (or
  tried to), by Eastern date of submission. Entry evidence (price, sportsbook
  and model probability, edge, Kalshi bid/ask, minutes before tip-off), then
  what happened: accepted, queue position, cancel time, reason and veto,
  filled contracts and price, fees, settlement profit.
- `data/<nba|nfl>/fills/<day>.csv`: one row per fill, with the entry evidence
  of its order and the NO-price moves 5, 15 and 60 minutes after the fill
  (positive = the market moved our way; fees not included).
- `data/<nba|nfl>/settlements/<day>.csv`: one row per settled market: revenue,
  costs, fees and net profit as Kalshi reported them.
- `data/summary.json`: counts and settled profit by market and rules version.

`order_ref` and `fill_ref` are one-way hashes of the exchange identifiers,
for joining the files. These are LIVE results; never mix them with replays.
"""


# --- pushing ---------------------------------------------------------------------


def blob_sha(text):
    data = text.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def github(method, path, token, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"https://api.github.com{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "smm-private-export",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        # Never print the response body or headers (tokens, data).
        raise ExportError(f"github_{method.lower()}_http_{error.code}") from None
    except URLError:
        raise ExportError(f"github_{method.lower()}_unreachable") from None


def push(files, repo, token, call=None):
    """Upload changed files as one commit. Returns the number of files changed."""
    call = call or github  # looked up at call time (tests replace it)
    if not token:
        raise ExportError("private_export_token_not_configured")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo or ""):
        raise ExportError("private_export_repo_invalid")
    if repo.lower() == PUBLIC_REPO.lower():
        raise ExportError("refuse_public_project_repository")
    info = call("GET", f"/repos/{repo}", token)
    if info.get("private") is not True:
        raise ExportError("refuse_repository_not_private")
    branch = info.get("default_branch") or "main"
    head = call("GET", f"/repos/{repo}/git/ref/heads/{branch}", token)["object"]["sha"]
    base_tree = call("GET", f"/repos/{repo}/git/commits/{head}", token)["tree"]["sha"]
    listing = call("GET", f"/repos/{repo}/git/trees/{base_tree}?recursive=1", token)
    remote = {
        t["path"]: t["sha"] for t in listing.get("tree", []) if t.get("type") == "blob"
    }
    changed = [
        p for p, text in sorted(files.items()) if remote.get(p) != blob_sha(text)
    ]
    if not changed:
        return 0
    entries = []
    for path in changed:
        blob = call(
            "POST",
            f"/repos/{repo}/git/blobs",
            token,
            {
                "content": base64.b64encode(files[path].encode()).decode(),
                "encoding": "base64",
            },
        )
        entries.append(
            {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}
        )
    tree = call(
        "POST",
        f"/repos/{repo}/git/trees",
        token,
        {"base_tree": base_tree, "tree": entries},
    )
    commit = call(
        "POST",
        f"/repos/{repo}/git/commits",
        token,
        {
            "message": f"Export {len(changed)} file(s) {datetime.now(UTC):%Y-%m-%dT%H:%MZ}",
            "tree": tree["sha"],
            "parents": [head],
        },
    )
    call(
        "PATCH",
        f"/repos/{repo}/git/refs/heads/{branch}",
        token,
        {"sha": commit["sha"], "force": False},
    )
    return len(changed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--push", action="store_true", help="upload to PRIVATE_EXPORT_REPO"
    )
    parser.add_argument(
        "--out", type=Path, help="also write the files under this folder"
    )
    parser.add_argument("--nba-journal", type=Path, default=JOURNALS["nba"])
    parser.add_argument("--nfl-journal", type=Path, default=JOURNALS["nfl"])
    args = parser.parse_args(argv)
    try:
        files, summary = build_files(
            {"nba": args.nba_journal, "nfl": args.nfl_journal}, datetime.now(UTC)
        )
        if args.out:
            for path, text in files.items():
                target = args.out / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        counts = {
            m: {
                k: v
                for k, v in s.items()
                if k in ("status", "orders", "fills", "settled_markets")
            }
            for m, s in summary["markets"].items()
        }
        changed = None
        if args.push:
            changed = push(
                files,
                os.environ.get("PRIVATE_EXPORT_REPO", ""),
                os.environ.get("PRIVATE_EXPORT_TOKEN", ""),
            )
        print(json.dumps({"counts": counts, "files_changed": changed}, sort_keys=True))
    except Exception as error:
        # Error type and safe code only: never data, URLs or tokens.
        reason = str(error) if isinstance(error, ExportError) else type(error).__name__
        print(f"PRIVATE EXPORT FAILED: {reason}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
