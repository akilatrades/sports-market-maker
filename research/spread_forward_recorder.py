"""Private, GET-only prospective recorder. Never imports a funded worker."""

import argparse
import ast
import base64
import fcntl
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import zlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding

from research.spread_forward_core import (
    HORIZONS,
    MAX_LATE,
    EvidenceError,
    amount,
    canonical,
    digest,
    external_book,
    instant,
    normalize_fill,
    normalized_orders,
    orders_from_journal,
    replay,
)
from research.spread_forward_candidates import candidate

HOME = Path("/home/trader/spread-forward-study")
PRODUCTION = Path("/home/trader/sports-market-maker-prod-auto")
STATE = Path("/home/trader/prod-spread-auto")
ENVIRONMENT = Path("/etc/market-maker-prod-nba-auto.env")
DEPLOYED = "fe7a5e7a8cfff8eeb5018d5d047f549f8a7f7cbd"
POLICY_BLOB = "04cdd6bb57e2df8a0945cc67298723a3afe55f52"
VERSION = "spread-maker-v3-24h-starts"
PROTOCOL = "spread-forward-30d-v1"
PREFIX = "/trade-api/v2"
ORIGIN = "https://external-api.kalshi.com"


def now():
    return datetime.now(UTC)


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(canonical(value) + "\n")
    temp.chmod(0o600)
    os.replace(temp, path)


def environment(path):
    """Read existing credentials without executing shell or copying secrets."""
    result = {}
    for token in shlex.split(path.read_text(), comments=True):
        if "=" not in token:
            raise EvidenceError("unsupported_environment_format")
        key, value = token.split("=", 1)
        if key in ("KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY", "KALSHI_ENV"):
            result[key] = value
    if result.get("KALSHI_ENV") != "prod":
        raise EvidenceError("production_environment_required")
    if not all(result.get(k) for k in ("KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY")):
        raise EvidenceError("missing_credentials")
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EvidenceError("redirect_refused")


class ReadOnlyAPI:
    """Only fixed production GET routes; no arbitrary method/body/host support."""

    ROUTE = re.compile(
        r"^/(?:portfolio/(?:fills|positions|settlements|orders"
        r"(?:/[A-Za-z0-9-]+/queue_position)?)|markets"
        r"(?:/[A-Za-z0-9_.-]+(?:/orderbook)?)?|series/[A-Za-z0-9_.-]+)$"
    )

    def __init__(self, env):
        self.key_id = env["KALSHI_KEY_ID"]
        pem = env["KALSHI_PRIVATE_KEY"].strip().replace("\\n", "\n")
        match = re.search(r"-----BEGIN ([A-Z ]+)-----(.*?)-----END \1-----", pem, re.S)
        if match:
            label, body = match.group(1), re.sub(r"\s+", "", match.group(2))
        else:
            label, body = "PRIVATE KEY", re.sub(r"\s+", "", pem)
        pem = (
            f"-----BEGIN {label}-----\n"
            + "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
            + f"\n-----END {label}-----\n"
        )
        self.key = serialization.load_pem_private_key(pem.encode(), password=None)
        self.opener = urllib.request.build_opener(NoRedirect)
        self.last = 0.0

    def get(self, path, params=None):
        if not self.ROUTE.fullmatch(path):
            raise EvidenceError("read_route_not_allowed")
        time.sleep(max(0, 1.0 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        timestamp = str(int(time.time() * 1000))
        message = (timestamp + "GET" + PREFIX + path).encode()
        if isinstance(self.key, ed25519.Ed25519PrivateKey):
            signature = self.key.sign(message)
        else:
            signature = self.key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )
        request = urllib.request.Request(
            ORIGIN
            + PREFIX
            + path
            + ("?" + urllib.parse.urlencode(params) if params else ""),
            headers={
                "KALSHI-ACCESS-KEY": self.key_id,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
                "User-Agent": PROTOCOL,
            },
            method="GET",
        )
        with self.opener.open(request, timeout=12) as response:
            return json.load(response)

    def pages(self, path, key, params=None):
        params = dict(params or {}, limit=200)
        rows, cursors = [], set()
        for _ in range(500):
            payload = self.get(path, params)
            if not isinstance(payload.get(key), list):
                raise EvidenceError("missing_page_rows")
            rows.extend(payload[key])
            cursor = payload.get("cursor")
            if not cursor:
                return rows
            if cursor in cursors:
                raise EvidenceError("repeated_cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        raise EvidenceError("page_limit")


class Store:
    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path, timeout=20)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS records "
            "(kind TEXT, id TEXT, at TEXT, body BLOB, "
            "PRIMARY KEY(kind,id))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        self.db.commit()
        path.chmod(0o600)

    def put(self, kind, identity, value, at=None):
        payload = zlib.compress(canonical(value).encode())
        self.db.execute(
            "INSERT OR IGNORE INTO records VALUES (?,?,?,?)",
            (kind, str(identity), (at or now()).isoformat(), payload),
        )
        self.db.commit()

    def values(self, kind):
        return list(self.iter_values(kind))

    def iter_values(self, kind):
        return (
            json.loads(zlib.decompress(row[0]))
            for row in self.db.execute(
                "SELECT body FROM records WHERE kind=? ORDER BY at,id", (kind,)
            )
        )

    def ids(self, kind):
        return {
            row[0]
            for row in self.db.execute("SELECT id FROM records WHERE kind=?", (kind,))
        }

    def meta(self, key, value=None):
        if value is not None:
            self.db.execute(
                "INSERT OR REPLACE INTO meta VALUES (?,?)", (key, canonical(value))
            )
            self.db.commit()
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def fault(self, area, error):
        # No exception text: exchange errors and file paths can contain secrets.
        self.put(
            "fault",
            str(time.time_ns()),
            {
                "area": area,
                "class": type(error).__name__,
                "at": now().isoformat(),
                "code": str(error) if type(error) is EvidenceError else None,
            },
        )


def journal():
    text = (STATE / "journal.jsonl").read_text()
    if text and not text.endswith("\n"):
        raise EvidenceError("journal_partial_line")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def policy():
    source = PRODUCTION / "live/spread_policy.py"
    data = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != POLICY_BLOB:
        raise EvidenceError("strategy_policy_changed")
    head = subprocess.check_output(
        ["git", "-C", str(PRODUCTION), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != DEPLOYED:
        raise EvidenceError("deployed_strategy_changed")
    subprocess.run(
        [
            "git",
            "-C",
            str(PRODUCTION),
            "diff",
            "--quiet",
            "HEAD",
            "--",
            "live",
            "kalshi",
        ],
        check=True,
        capture_output=True,
    )
    result = {}
    for node in ast.parse(data).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", "")
            value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "frozenset"
            ):
                value = value.args[0]
            try:
                result[name] = ast.literal_eval(value)
            except (ValueError, TypeError):
                pass
    if result.get("STRATEGY_VERSION") != VERSION or not result.get("SERIES"):
        raise EvidenceError("invalid_policy")
    return result


def implementation_hash():
    root = Path(__file__).parent
    files = sorted(root.glob("spread_forward_*.py"))
    return digest(
        {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    )


def capture_local(store):
    """Preserve real worker opportunities/rejections, not inferred nonfills."""
    for name in ("last_scan.json", "event_starts.json", "measurements_summary.json"):
        path = STATE / name
        if path.exists():
            value = json.loads(path.read_text())
            store.put("local_" + name, digest(value), value)
    for name in ("journal.jsonl", "shadow.jsonl", "measurements.jsonl"):
        path = STATE / name
        if not path.exists():
            continue
        offset = store.meta("offset_" + name) or 0
        if path.stat().st_size < offset:
            store.fault("rotated_" + name, EvidenceError())
            offset = 0
        with path.open("rb") as stream:
            stream.seek(offset)
            for line in stream:
                if not line.endswith(b"\n"):
                    break
                value = json.loads(line)
                store.put("local_" + name, digest(value), value)
                offset += len(line)
        store.meta("offset_" + name, offset)


def survey(home, stop):
    """Slow lane: every configured series, plus queue samples and worker logs."""
    store = Store(home / "evidence.sqlite3")
    api = ReadOnlyAPI(environment(ENVIRONMENT))
    while not stop.is_set():
        began = now()
        try:
            config = policy()
            capture_local(store)
            resting = api.pages("/portfolio/orders", "orders", {"status": "resting"})
            store.put("survey_orders", began.isoformat(), resting)
            owned = orders_from_journal(journal())
            owned_tickers = {o["ticker"] for o in owned.values()}
            for order in resting:
                if stop.is_set():
                    return
                if order.get("order_id") in owned:
                    try:
                        position = api.get(
                            "/portfolio/orders/" + order["order_id"] + "/queue_position"
                        )
                        store.put(
                            "queue",
                            str(time.time_ns()),
                            {
                                "order_id": order["order_id"],
                                "at": now().isoformat(),
                                "response": position,
                            },
                        )
                    except Exception as error:
                        store.fault("queue", error)
            complete = 0
            for series in config["SERIES"]:
                if stop.is_set():
                    return
                try:
                    rows = api.pages(
                        "/markets",
                        "markets",
                        {"series_ticker": series, "status": "open"},
                    )
                    listing_at = now()
                    store.put(
                        "market_survey",
                        str(time.time_ns()),
                        {
                            "series": series,
                            "at": now().isoformat(),
                            "markets": rows,
                            "note": "independent_listing_snapshot_not_bot_selection",
                        },
                    )
                    cache = json.loads((STATE / "event_starts.json").read_text())
                    for market in rows:
                        observed = listing_at
                        adjusted = dict(market)
                        ticker = market.get("ticker")
                        if ticker in owned_tickers:
                            try:
                                before = normalized_orders(
                                    api.pages(
                                        "/portfolio/orders",
                                        "orders",
                                        {"status": "resting"},
                                    )
                                )
                                book = api.get(
                                    "/markets/" + ticker + "/orderbook", {"depth": 0}
                                )
                                after = normalized_orders(
                                    api.pages(
                                        "/portfolio/orders",
                                        "orders",
                                        {"status": "resting"},
                                    )
                                )
                                if [o for o in before if o["ticker"] == ticker] != [
                                    o for o in after if o["ticker"] == ticker
                                ]:
                                    raise EvidenceError("orders_changed_during_survey")
                                depth = external_book(book, ticker, before)
                                adjusted["yes_bid_dollars"] = (
                                    depth["yes"][0][0] if depth["yes"] else "0"
                                )
                                adjusted["yes_ask_dollars"] = (
                                    str(1 - amount(depth["no"][0][0]))
                                    if depth["no"]
                                    else "1"
                                )
                                store.put(
                                    "survey_book",
                                    str(time.time_ns()),
                                    {
                                        "ticker": ticker,
                                        "at": now().isoformat(),
                                        "book": book,
                                        "orders": [
                                            o for o in before if o["ticker"] == ticker
                                        ],
                                    },
                                )
                                observed = now()
                            except Exception as error:
                                store.put(
                                    "candidate",
                                    str(time.time_ns()),
                                    {
                                        "ticker": ticker,
                                        "event_ticker": market.get("event_ticker"),
                                        "at": now().isoformat(),
                                        "eligible": None,
                                        "reason": "external_book_unverified",
                                    },
                                )
                                store.fault("survey_book", error)
                                continue
                        decision = candidate(adjusted, series, config, cache, observed)
                        store.put("candidate", str(time.time_ns()), decision)
                    complete += 1
                except Exception as error:
                    store.fault("market_survey", error)
            if complete == len(config["SERIES"]):
                store.meta("survey_success", now().isoformat())
            store.meta(
                "survey_last",
                {
                    "at": now().isoformat(),
                    "completed": complete,
                    "expected": len(config["SERIES"]),
                },
            )
            if store.meta("manifest"):
                from research.spread_forward_report import report

                write_json(home / "report.json", report(store))
        except Exception as error:
            store.fault("survey", error)
        stop.wait(max(1, 600 - (now() - began).total_seconds()))


def cohort(orders, manifest):
    start, end = instant(manifest["start"]), instant(manifest["end"])
    baseline = set(manifest["baseline_events"])
    return {
        oid: item
        for oid, item in orders.items()
        if item.get("strategy_version") == VERSION
        and start <= instant(item["utc"]) < end
        and item.get("event_ticker") not in baseline
    }


def fetch_fills(api, since):
    return api.pages("/portfolio/fills", "fills", {"min_ts": int(since.timestamp())})


def collect_checkpoints(api, store, fills, all_fills, contaminated):
    completed = store.ids("checkpoint_done")
    remaining = {
        lot["fid"]: lot["left"]
        for queue in replay(fills)["open_lots"].values()
        for lot in queue
    }
    due = {}
    for fill in fills:
        age = (now() - instant(fill["at"])).total_seconds()
        for horizon in HORIZONS:
            key = fill["fid"] + ":" + str(horizon)
            if key not in completed and age >= horizon:
                due.setdefault(fill["ticker"], []).append(
                    {
                        "fid": fill["fid"],
                        "fill_at": fill["at"],
                        "horizon_seconds": horizon,
                        "remaining_actual": remaining.get(fill["fid"], "0"),
                        "key": key,
                    }
                )
    for ticker, references in due.items():
        snapshot = {
            "id": str(time.time_ns()),
            "ticker": ticker,
            "lots": references,
            "valid": False,
            "at": now().isoformat(),
        }
        late = any(
            (now() - instant(r["fill_at"])).total_seconds() - r["horizon_seconds"]
            > MAX_LATE
            for r in references
        )
        # Late horizons are explicit missing evidence. Do not prevent a later
        # on-time horizon in the same cycle from receiving its own snapshot.
        timely = [
            r
            for r in references
            if (now() - instant(r["fill_at"])).total_seconds() - r["horizon_seconds"]
            <= MAX_LATE
        ]
        if late:
            missed = dict(
                snapshot,
                lots=[r for r in references if r not in timely],
                reason="late_checkpoint",
            )
            store.put("checkpoint", missed["id"], missed)
        if timely:
            snapshot["id"] = str(time.time_ns())
            snapshot["lots"] = timely
            try:
                if ticker in contaminated:
                    raise EvidenceError("foreign_fill_on_study_market")
                before = normalized_orders(
                    api.pages("/portfolio/orders", "orders", {"status": "resting"})
                )
                raw_book = api.get("/markets/" + ticker + "/orderbook", {"depth": 0})
                snapshot["at"] = now().isoformat()
                after = normalized_orders(
                    api.pages("/portfolio/orders", "orders", {"status": "resting"})
                )

                def select(rows):
                    return [o for o in rows if o["ticker"] == ticker]

                snapshot.update(
                    orders_before=select(before),
                    orders_after=select(after),
                    raw_book=raw_book,
                )
                if select(before) != select(after):
                    raise EvidenceError("orders_changed_during_book")
                later_fills = api.pages(
                    "/portfolio/fills",
                    "fills",
                    {
                        "ticker": ticker,
                        "min_ts": int(min(instant(f["at"]) for f in fills).timestamp())
                        - 1,
                    },
                )

                def identity(f):
                    return f.get("fill_id") or f.get("trade_id")

                earlier_ids = {
                    identity(f)
                    for f in all_fills
                    if (f.get("ticker") or f.get("market_ticker")) == ticker
                }
                later_ids = {identity(f) for f in later_fills}
                if not later_ids <= earlier_ids:
                    raise EvidenceError("inventory_changed_during_book")
                positions = api.pages("/portfolio/positions", "market_positions")
                from decimal import Decimal

                actual_net = sum(
                    (
                        Decimal(str(p.get("position_fp", p.get("position"))))
                        for p in positions
                        if p.get("ticker") == ticker
                    ),
                    Decimal(0),
                )
                expected_net = sum(
                    (
                        amount(f["quantity"]) * (1 if f["side"] == "yes" else -1)
                        for f in fills
                        if f["ticker"] == ticker
                    ),
                    Decimal(0),
                )
                snapshot["position_net"] = str(actual_net)
                if not actual_net.is_finite() or actual_net != expected_net:
                    raise EvidenceError("signed_inventory_mismatch")
                series = ticker.split("-")[0]
                fees = api.get("/series/" + series).get("series", {})
                if fees.get("fee_type") not in (
                    "quadratic",
                    "quadratic_with_maker_fees",
                ):
                    raise EvidenceError("unsupported_fee_type")
                amount(fees.get("fee_multiplier"))
                snapshot.update(
                    external_book=external_book(raw_book, ticker, before),
                    fee_type=fees.get("fee_type"),
                    fee_multiplier=fees.get("fee_multiplier"),
                    series_fee_response=fees,
                    valid=True,
                )
                starts = [
                    instant(f["event_start_utc"])
                    for f in fills
                    if f["ticker"] == ticker and f.get("event_start_utc")
                ]
                snapshot["after_event_start"] = (
                    instant(snapshot["at"]) >= min(starts) if starts else None
                )
                snapshot["valid"] = all(
                    0
                    <= (instant(snapshot["at"]) - instant(r["fill_at"])).total_seconds()
                    - r["horizon_seconds"]
                    <= MAX_LATE
                    for r in timely
                )
            except Exception as error:
                snapshot["error_class"] = type(error).__name__
                store.fault("checkpoint", error)
            store.put("checkpoint", snapshot["id"], snapshot)
        for reference in references:
            store.put("checkpoint_done", reference["key"], {"at": now().isoformat()})


def status(home):
    path = home / "health.json"
    if not path.exists():
        return {"state": "not_started"}
    result = json.loads(path.read_text())
    result["heartbeat_age_seconds"] = round(
        (now() - instant(result["at"])).total_seconds()
    )
    # This schema contains aggregate health only. Never print the DB/manifest.
    return result


def run(home):
    os.umask(0o077)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (home / "observer.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    if (home / "STOP").exists():
        return
    os.nice(10)
    store = Store(home / "evidence.sqlite3")
    env = environment(ENVIRONMENT)
    api = ReadOnlyAPI(env)
    del env
    stop = threading.Event()
    thread = threading.Thread(target=survey, args=(home, stop), daemon=True)
    thread.start()
    manifest = store.meta("manifest")
    code_hash = implementation_hash()
    last_account = 0.0
    while not (home / "STOP").exists():
        began = now()
        health = {"at": began.isoformat(), "state": "warming_up", "protocol": PROTOCOL}
        try:
            policy()
            if manifest and manifest.get("implementation_hash") != code_hash:
                raise EvidenceError("research_implementation_changed")
            if (
                sum(p.stat().st_size for p in home.glob("evidence.sqlite3*"))
                > 2_000_000_000
            ):
                health.update(state="stopped_disk_budget")
                (home / "STOP").touch(mode=0o600)
                write_json(home / "health.json", health)
                break
            if manifest and began >= instant(manifest["drain_end"]):
                health.update(
                    state="complete", start=manifest["start"], end=manifest["end"]
                )
                (home / "STOP").touch(mode=0o600)
                write_json(home / "health.json", health)
                break
            orders = orders_from_journal(journal())
            if not manifest:
                resting = api.pages(
                    "/portfolio/orders", "orders", {"status": "resting"}
                )
                positions = api.pages("/portfolio/positions", "market_positions")
                recent = fetch_fills(api, began - timedelta(days=7))
                # Prove this credential belongs to the spread account without
                # printing or persisting the credential itself.
                if not any(row.get("order_id") in orders for row in recent + resting):
                    raise EvidenceError("spread_account_identity_unverified")
                store.put(
                    "baseline_account",
                    began.isoformat(),
                    {"orders": resting, "positions": positions, "recent_fills": recent},
                )
                success = store.meta("survey_success")
                if not success or (began - instant(success)).total_seconds() > 900:
                    raise EvidenceError("waiting_for_complete_universe_survey")
                start = now()
                # Refresh journal after baseline/survey: old orders cannot enter.
                orders = orders_from_journal(journal())
                manifest = {
                    "protocol": PROTOCOL,
                    "strategy_version": VERSION,
                    "production_revision": DEPLOYED,
                    "policy_blob": POLICY_BLOB,
                    "implementation_hash": code_hash,
                    "start": start.isoformat(),
                    "end": (start + timedelta(days=30)).isoformat(),
                    "drain_end": (start + timedelta(days=37)).isoformat(),
                    "baseline_events": sorted(
                        {x["event_ticker"] for x in orders.values()}
                        | {
                            str(x.get("ticker", "")).rsplit("-", 1)[0]
                            for x in positions + resting
                        }
                    ),
                }
                store.meta("manifest", manifest)
                write_json(home / "manifest.json", manifest)
            owned = cohort(orders, manifest)
            for oid, intent in owned.items():
                store.put("cohort_order", oid, dict(intent, order_id=oid))
            # Resume from last successful poll with overlap; hourly full sweep
            # reconciles delayed exchange delivery without duplicating fills.
            last = store.meta("fill_poll")
            full = store.meta("full_fill_sweep")
            full_due = not full or (began - instant(full)).total_seconds() >= 3600
            since = instant(manifest["start"]) - timedelta(seconds=120)
            if last and not full_due:
                since = max(since, instant(last) - timedelta(seconds=120))
            received = fetch_fills(api, since)
            for raw in received:
                fid = raw.get("fill_id") or raw.get("trade_id")
                if not fid:
                    raise EvidenceError("missing_fill_identity")
                store.put("raw_fill_version", str(fid) + ":" + digest(raw), raw)
            store.meta("fill_poll", began.isoformat())
            if full_due:
                store.meta("full_fill_sweep", began.isoformat())
            all_fills = store.values("raw_fill_version")
            tickers = {v["ticker"] for v in owned.values()}
            contaminated = {
                r.get("ticker") or r.get("market_ticker")
                for r in all_fills
                if (r.get("ticker") or r.get("market_ticker")) in tickers
                and r.get("order_id") not in owned
            }
            fills = []
            for raw in all_fills:
                if raw.get("order_id") in owned:
                    fill = normalize_fill(raw, owned[raw["order_id"]])
                    fill["event_start_utc"] = owned[raw["order_id"]].get(
                        "event_start_utc"
                    )
                    fills.append(fill)
            # Replay validates duplicate/versioned fill consistency first.
            actual = replay(fills)
            fills = list({f["fid"]: f for f in fills}.values())
            for fill in fills:
                store.put("fill", fill["fid"], fill)
            collect_checkpoints(api, store, fills, all_fills, contaminated)
            if time.monotonic() - last_account >= 300:
                positions = api.pages("/portfolio/positions", "market_positions")
                settlements = api.pages(
                    "/portfolio/settlements",
                    "settlements",
                    {"min_ts": int(instant(manifest["start"]).timestamp())},
                )
                store.put(
                    "account_snapshot",
                    str(time.time_ns()),
                    {
                        "at": now().isoformat(),
                        "positions": positions,
                        "settlements": settlements,
                    },
                )
                last_account = time.monotonic()
            checkpoints = store.values("checkpoint")
            counts = Counter(
                r["kind"]
                for r in (
                    {"kind": "valid" if c.get("valid") else "invalid"}
                    for c in checkpoints
                )
            )
            health.update(
                state="recording"
                if began < instant(manifest["end"])
                else "settlement_followup",
                start=manifest["start"],
                end=manifest["end"],
                cohort_orders=len(owned),
                fills=len({f["fid"] for f in fills}),
                fill_events=len({f["event_ticker"] for f in fills}),
                fifo_markets_before_settlement=len(actual["open_lots"]),
                contaminated_markets=len(contaminated),
                valid_checkpoints=counts["valid"],
                invalid_checkpoints=counts["invalid"],
                last_survey=store.meta("survey_success"),
                survey=store.meta("survey_last"),
                last_success=now().isoformat(),
            )
            store.meta("last_health_success", health)
        except Exception as error:
            store.fault("fast_loop", error)
            old = store.meta("last_health_success") or {}
            health.update(
                state="recording_error" if manifest else "warming_up",
                error_class=type(error).__name__,
                error_code=str(error) if type(error) is EvidenceError else None,
                last_success=old.get("last_success"),
                start=manifest.get("start") if manifest else None,
                end=manifest.get("end") if manifest else None,
            )
        write_json(home / "health.json", health)
        stop.wait(max(1, 15 - (now() - began).total_seconds()))
    stop.set()
    thread.join(timeout=15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "status"))
    args = parser.parse_args()
    if args.action == "status":
        print("SPREAD_FORWARD_HEALTH=" + canonical(status(HOME)))
    else:
        run(HOME)


if __name__ == "__main__":
    main()
