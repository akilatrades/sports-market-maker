"""Export the bots' orders, fills and settlements to a PRIVATE GitHub repo.

Runs on the trading server from its own timer. It reads only the two bot
journals (the bots already record every order, fill, queue reading, price
move after a fill, cancel and settlement there); it makes no Kalshi request
and needs no Kalshi credentials. It writes nothing on the server. Journals
are read line by line, keeping only the fields exported, so memory stays
small even after a long season.

Output: daily CSV files per market and a summary, one row per order, fill and
settled market, using explicit column lists. Exchange order, client order and
fill identifiers are replaced by short one-way hashes (enough to join the
files); keys, balances and account details are never exported.

Pushing is opt-in (``--push``) and goes only to the repository named in
PRIVATE_EXPORT_REPO with the token in PRIVATE_EXPORT_TOKEN (a fine-grained
token limited to that repository's contents). It refuses unless GitHub
reports exactly that repository as private (not internal, not archived, no
GitHub Pages), never pushes to the public project repository, and never
follows redirects. All files go up as one commit, only when something
changed.

Run: python -m tools.export_private_fills            (counts only, no push)
     python -m tools.export_private_fills --out DIR  (write the files locally)
     python -m tools.export_private_fills --push     (server timer)
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PUBLIC_REPO = "akilatrades/sports-market-maker"
JOURNALS = {
    "nba": Path("/home/trader/prod-nba-auto/journal.jsonl"),
    "nfl": Path("/home/trader/prod-nfl-auto/journal.jsonl"),
}
# Copied from each order's intent record, when present. Nothing else is.
# NBA and NFL name some fields differently; both are kept.
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
    "p_yes",  # NBA: probability used
    "p_yes_used",  # NFL: probability used
    "p_model_yes",  # NFL: model probability
    "book_n",
    "edge",
    "baseline_edge",
    "extra_maker_ticks",
    "net_edge_after_fee_bound",  # NBA
    "edge_after_fee_buffer",  # NFL
    "fee_bound_dollars",  # NBA
    "fee_buffer_dollars",  # NFL
    "model_probability_yes_at_entry",
    "sportsbook_probability_yes_at_entry",
    "kalshi_yes_bid_at_entry",
    "kalshi_yes_ask_at_entry",
    "book_updated_utc_at_entry",
    "model_generated_utc",  # NBA
    "model_made_utc",  # NFL
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
    "cancel_requested_utc",
    "cancel_confirmed_utc",
    "cancel_reason",
    "cancel_veto",
    "emergency_cancel_utc",
    "filled_contracts",
    "first_fill_utc",
    "avg_fill_no_price",
    "fill_fees_dollars",
    "settled_utc",
    "market_settlement_net_profit_dollars",
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
    "edge_after_fee_buffer",
    "sportsbook_probability_yes_at_entry",
    "model_probability_yes_at_entry",
    "p_model_yes",
    *MARKOUTS,
]
SETTLEMENT_FIELDS = [
    "revenue_dollars",
    "yes_cost_dollars",
    "no_cost_dollars",
    "fee_dollars",
    "net_profit_dollars",
    "accounting_complete",
]
SETTLEMENT_COLUMNS = ["market", "ticker", "settled_utc", "strategy_version"]
SETTLEMENT_COLUMNS += SETTLEMENT_FIELDS
# Journal fields kept while reading, by event kind; everything else is
# dropped at once (memory) and can never reach the output.
KEEP = {
    "intent": {"utc", "client_order_id", *INTENT_FIELDS},
    "accepted": {"utc", "client_order_id", "order_id"},
    "unknown_outcome": {"client_order_id"},
    "reconciled_rejected": {"client_order_id", "utc"},
    "queue": {"order_id", "ahead"},
    "cancel_intent": {"utc", "order_id", "reason", "veto"},
    "cancel_accepted": {"utc", "order_id"},
    "emergency_cancel": {"utc", "order_id"},
    "fill": {
        "fill_id",
        "utc",
        "ticker",
        "order_id",
        "count",
        "yes_price",
        "no_price",
        "fee",
        "is_taker",
    },
    "markout": {"fill_id", "horizon_minutes", "mid_move_dollars", "bid_move_dollars"},
    "settlement": {"ticker", "utc", *SETTLEMENT_FIELDS},
}
# Never delete more than this share of a market's files in one run (a bad
# read must not wipe the archive; git history keeps everything anyway).
MAX_DELETE_SHARE = 0.25


class ExportError(RuntimeError):
    pass


def events(path):
    """Slim journal events, one line at a time.

    Yields (kind, fields) for the kinds in KEEP. A line still being written
    at the end of the file is skipped, as are blank, non-JSON or non-object
    lines (counted in ``skipped``).
    """
    skipped = {"lines": 0}

    def generate():
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            for line in f:
                if not line.endswith("\n"):
                    break  # the writer is mid-line; the next export reads it
                try:
                    record = json.loads(line)
                except ValueError:
                    if line.strip():
                        skipped["lines"] += 1
                    continue
                if not isinstance(record, dict):
                    skipped["lines"] += 1
                    continue
                kind = record.get("event")
                if kind in KEEP:
                    yield kind, {k: record[k] for k in KEEP[kind] if k in record}

    return generate(), skipped


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


def tables(market, stream):
    """(orders, fills, settlements, latest event time) for one bot's journal."""
    intents, status, accepted, client_of = {}, {}, {}, {}
    q_first, q_last, cancel, cancel_ok, emergency = {}, {}, {}, {}, {}
    fills, markouts, settlements = {}, {}, {}
    latest = None
    for kind, e in stream:
        stamp = _time(e.get("utc"))
        if stamp and (latest is None or stamp > latest):
            latest = stamp
        cid, oid = e.get("client_order_id"), e.get("order_id")
        oid = str(oid) if oid else None
        if kind == "intent" and cid:
            intents[cid] = e
            status.setdefault(cid, "intent_only")
        elif kind == "accepted" and cid:
            accepted[cid] = e.get("utc", "")
            status[cid] = "accepted"
            if oid:
                client_of[oid] = cid
        elif kind == "unknown_outcome" and cid:
            status[cid] = "unknown_outcome"
        elif kind == "reconciled_rejected" and cid:
            status[cid] = "reconciled_rejected"
        elif not oid:
            if kind == "markout" and e.get("fill_id"):
                markouts[(e["fill_id"], e.get("horizon_minutes"))] = e
            elif kind == "settlement" and e.get("ticker"):
                settlements[e["ticker"]] = e  # the latest record is the correction
        elif kind == "queue" and e.get("ahead") is not None:
            q_first.setdefault(oid, e["ahead"])
            q_last[oid] = e["ahead"]
        elif kind == "cancel_intent":
            cancel[oid] = e
        elif kind == "cancel_accepted":
            cancel_ok[oid] = e.get("utc", "")
        elif kind == "emergency_cancel":
            emergency[oid] = e.get("utc", "")
        elif kind == "fill":
            fills.setdefault(oid, []).append(e)
    order_of = {cid: oid for oid, cid in client_of.items()}
    intent_by_ticker = {i.get("ticker"): i for i in intents.values()}
    orders, fill_rows = [], []
    for cid, intent in intents.items():
        oid = order_of.get(cid)
        own = fills.get(oid, []) if oid else []
        counts = [_number(f.get("count")) for f in own]
        prices = [_number(f.get("no_price")) for f in own]
        priced = [(c, p) for c, p in zip(counts, prices) if c and p is not None]
        priced_count = sum(c for c, _ in priced)
        fees = [_number(f.get("fee")) for f in own]
        stop = cancel.get(oid, {})
        settled = settlements.get(intent.get("ticker"), {})
        orders.append(
            {
                "market": market,
                "order_ref": ref(cid),
                "intent_utc": intent.get("utc", ""),
                "side": "no",  # both bots post passive NO orders only
                **{k: intent.get(k, "") for k in INTENT_FIELDS},
                "minutes_before_tip": _minutes(
                    intent.get("utc"), intent.get("tip_utc")
                ),
                "status": status.get(cid, ""),
                "accepted_utc": accepted.get(cid, ""),
                "first_queue_ahead": q_first.get(oid, ""),
                "last_queue_ahead": q_last.get(oid, ""),
                "cancel_requested_utc": stop.get("utc", ""),
                "cancel_confirmed_utc": cancel_ok.get(oid, ""),
                "cancel_reason": stop.get("reason", ""),
                "cancel_veto": stop.get("veto", ""),
                "emergency_cancel_utc": emergency.get(oid, ""),
                "filled_contracts": sum(c for c in counts if c),
                "first_fill_utc": min((f.get("utc", "") for f in own), default=""),
                "avg_fill_no_price": round(
                    sum(c * p for c, p in priced) / priced_count, 4
                )
                if priced_count
                else "",
                "fill_fees_dollars": round(sum(f for f in fees if f is not None), 6)
                if own
                else "",
                "settled_utc": settled.get("utc", ""),
                "market_settlement_net_profit_dollars": settled.get(
                    "net_profit_dollars", ""
                ),
            }
        )
        for f in own:
            row = {
                "market": market,
                "fill_ref": ref(f.get("fill_id")),
                "order_ref": ref(cid),
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
                if k not in row and k in INTENT_FIELDS:
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
            **{k: s.get(k, "") for k in SETTLEMENT_FIELDS},
        }
        for ticker, s in settlements.items()
    ]
    return orders, fill_rows, settlement_rows, latest


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


def build_files(journals):
    """({path in the private repo: text}, summary, markets read completely).

    The summary is stamped with the newest journal event, not the clock, so
    an export with nothing new produces identical files (and no commit).
    A market whose journal is missing or unreadable produces no files, and
    its existing files in the private repo are left alone.
    """
    files, summary, complete = {}, {"markets": {}}, set()
    for market, path in journals.items():
        if not path.exists():
            summary["markets"][market] = {"status": "journal_missing"}
            continue
        try:
            stream, skipped = events(path)
            orders, fills, settlements, latest = tables(market, stream)
        except Exception as error:  # one bad journal must not stop the other
            summary["markets"][market] = {"status": f"error_{type(error).__name__}"}
            continue
        complete.add(market)
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
            "data_through_utc": latest.astimezone(UTC).isoformat() if latest else None,
            "skipped_lines": skipped["lines"],
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
    return files, summary, complete


README = """# Private bot data (do not make this repository public)

Written every hour by `tools/export_private_fills.py` on the trading server,
from the two bots' journals. Never edit by hand: the next export rewrites it.
These are LIVE results; never mix them with replays or simulations.

- `data/<nba|nfl>/orders/<day>.csv`: one row per order the bot submitted (or
  tried to), by Eastern date of submission. Entry evidence (price, sportsbook
  and model probability, edge, Kalshi bid/ask, minutes before tip-off), then
  what happened: accepted, queue position, cancel request/confirmation,
  reason and veto, filled contracts and price, fees.
  `market_settlement_net_profit_dollars` is the settled profit of the whole
  MARKET (ticker), repeated on each order for that market; the bots post at
  most one order per market, but never sum it across orders without checking.
- `data/<nba|nfl>/fills/<day>.csv`: one row per fill, with the entry evidence
  of its order and the NO-price moves 5, 15 and 60 minutes after the fill
  (positive = the market moved our way; fees not included).
- `data/<nba|nfl>/settlements/<day>.csv`: one row per settled market: revenue,
  costs, fees and net profit as Kalshi reported them.
- `data/summary.json`: counts and settled profit by market and rules version,
  up to the newest journal event (`data_through_utc`).

`order_ref` and `fill_ref` are one-way hashes of the exchange identifiers,
for joining the files. NBA and NFL name a few entry fields differently
(e.g. `p_yes` and `p_yes_used`); both columns exist, one is blank per market.
"""


# --- pushing ---------------------------------------------------------------------


def blob_sha(text):
    data = text.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could carry the token to another host: refuse them all."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ExportError(f"github_redirect_refused_{code}")


_OPENER = urllib.request.build_opener(_NoRedirect)


def urlopen(request, timeout):
    return _OPENER.open(request, timeout=timeout)


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


def check_private(info, repo):
    if str(info.get("full_name", "")).lower() != repo.lower():
        raise ExportError("refuse_repository_name_mismatch")
    if (
        info.get("private") is not True
        or info.get("visibility", "private") != "private"
    ):
        raise ExportError("refuse_repository_not_private")
    if info.get("has_pages"):
        raise ExportError("refuse_repository_has_pages")
    if info.get("archived"):
        raise ExportError("refuse_repository_archived")


def push(files, repo, token, complete=(), call=None):
    """Upload changed files as one commit; returns (changed, deleted).

    Files under data/<market>/ that this export no longer produces are
    deleted, but only for markets read completely this run, and never more
    than MAX_DELETE_SHARE of a market's files at once.
    """
    call = call or github  # looked up at call time (tests replace it)
    if not token:
        raise ExportError("private_export_token_not_configured")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo or ""):
        raise ExportError("private_export_repo_invalid")
    if repo.lower() == PUBLIC_REPO.lower():
        raise ExportError("refuse_public_project_repository")
    info = call("GET", f"/repos/{repo}", token)
    check_private(info, repo)
    branch = info.get("default_branch") or "main"
    head = call("GET", f"/repos/{repo}/git/ref/heads/{branch}", token)["object"]["sha"]
    base_tree = call("GET", f"/repos/{repo}/git/commits/{head}", token)["tree"]["sha"]
    listing = call("GET", f"/repos/{repo}/git/trees/{base_tree}?recursive=1", token)
    if listing.get("truncated"):
        raise ExportError("tree_listing_truncated")
    remote = {
        t["path"]: t["sha"] for t in listing.get("tree", []) if t.get("type") == "blob"
    }
    changed = [
        p for p, text in sorted(files.items()) if remote.get(p) != blob_sha(text)
    ]
    deleted = []
    for market in sorted(complete):
        prefix = f"data/{market}/"
        mine = [p for p in remote if p.startswith(prefix)]
        stale = [p for p in mine if p not in files]
        if stale and len(stale) <= max(2, MAX_DELETE_SHARE * len(mine)):
            deleted += stale
    if not changed and not deleted:
        return 0, 0
    entries = [
        {"path": p, "mode": "100644", "type": "blob", "content": files[p]}
        for p in changed
    ]
    entries += [
        {"path": p, "mode": "100644", "type": "blob", "sha": None} for p in deleted
    ]
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
            "message": f"Export: {len(changed)} changed, {len(deleted)} removed",
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
    return len(changed), len(deleted)


def _inside_git_checkout(path):
    path = path.resolve()
    return any((p / ".git").exists() for p in (path, *path.parents))


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
        if args.out and _inside_git_checkout(args.out):
            # A checkout might be committed and pushed somewhere public.
            raise ExportError("refuse_out_inside_git_checkout")
        files, summary, complete = build_files(
            {"nba": args.nba_journal, "nfl": args.nfl_journal}
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
                if k
                in ("status", "orders", "fills", "settled_markets", "skipped_lines")
            }
            for m, s in summary["markets"].items()
        }
        changed = None
        if args.push:
            changed = push(
                files,
                os.environ.get("PRIVATE_EXPORT_REPO", ""),
                os.environ.get("PRIVATE_EXPORT_TOKEN", ""),
                complete=complete,
            )
        print(
            json.dumps({"counts": counts, "changed_removed": changed}, sort_keys=True)
        )
    except Exception as error:
        # Error type and safe code only: never data, URLs or tokens.
        reason = str(error) if isinstance(error, ExportError) else type(error).__name__
        print(f"PRIVATE EXPORT FAILED: {reason}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
