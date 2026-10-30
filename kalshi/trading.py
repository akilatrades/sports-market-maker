"""Authenticated Kalshi trading client, with a dry-run mode.

Kalshi signs each request with RSA or Ed25519: headers carry the key id,
a millisecond timestamp and a base64 signature over
``timestamp + METHOD + path`` (the path from ``/trade-api/v2`` on, without
the query string). Credentials come from the environment:

    KALSHI_KEY_ID        the API key id from the Kalshi account page
    KALSHI_PRIVATE_KEY   a PEM key or unencrypted PKCS#8 base64 body
    KALSHI_ENV           "demo" (default) or "prod"

V2 order writes use /portfolio/events/orders with a YES-side bid/ask book.
In dry-run mode (``TradingClient(dry_run=True)``, the default) orders are
built, validated and logged but not sent; reads still go to the exchange.
Nothing in this module decides what to trade; see ``live/nba_trade.py``.
"""

import base64
import json
import os
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding

BASES = {
    "prod": "https://external-api.kalshi.com",
    "demo": "https://demo-api.kalshi.co",
}
PREFIX = "/trade-api/v2"
# Kalshi refuses a balance read repeated within about a second (HTTP 429).
# Only that read is retried, after these waits (seconds): every bot reads the
# balance before it journals an order, never between an order's journal entry
# and its result, so the retry cannot stretch that window. No other request
# is retried, and writes never are.
RETRY_THROTTLED_PATHS = frozenset({"/portfolio/balance"})
READ_RETRY_WAITS = (1.0, 2.0)
MAX_RETRY_WAIT = 3.0


def retry_wait(error, default):
    """Kalshi's Retry-After (seconds) when given, within [default, 3 s]."""
    try:
        asked = float(error.headers.get("Retry-After"))
    except (AttributeError, TypeError, ValueError):
        return default
    if not math.isfinite(asked):
        return default
    return min(max(asked, default), MAX_RETRY_WAIT)


class TradingError(RuntimeError):
    pass


def normalize_pem(pem):
    """Repair a PEM pasted into a secret: literal "\\n", lost line breaks, stray spaces."""
    text = pem.strip().replace("\\n", "\n").replace("\r", "")
    match = re.search(
        r"-----BEGIN ([A-Z ]+)-----(.*?)-----END \1-----", text, re.DOTALL
    )
    if match:
        label, body = match.group(1), re.sub(r"\s+", "", match.group(2))
    elif re.fullmatch(r"[A-Za-z0-9+/=\s]+", text):
        # Only the base64 body was pasted: assume an unencrypted PKCS#8 key.
        label, body = "PRIVATE KEY", re.sub(r"\s+", "", text)
    else:
        return text
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    return (
        f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"
    )


def load_private_key(pem):
    return serialization.load_pem_private_key(
        normalize_pem(pem).encode(), password=None
    )


def sign(private_key, timestamp_ms, method, path):
    """RSA keys sign with PSS-SHA256; Ed25519 keys sign the message directly."""
    message = f"{timestamp_ms}{method.upper()}{path}".encode()
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        signature = private_key.sign(message)
    else:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256(),
        )
    return base64.b64encode(signature).decode()


@dataclass
class Order:
    """One limit order as Kalshi's API takes it; prices in whole cents."""

    ticker: str
    side: str  # "yes" or "no"
    count: int
    price_cents: int  # price of the side bought or sold
    expiration_ts: int | None = None  # Unix seconds; None rests until cancelled
    post_only: bool = True
    # Tagged so the kill switch can tell the strategy's orders from any other
    # order in the account (Kalshi echoes client_order_id back on orders).
    client_order_id: str = field(default_factory=lambda: f"smm-{uuid.uuid4()}")
    action: str = "buy"  # "sell" closes contracts we hold (the early exit)
    exchange_index: int | None = None  # assigned by signed market-shard verification
    time_in_force: str = "good_till_canceled"
    reduce_only: bool = False
    fractional: bool = False  # explicit opt-in; legacy integer validation stays

    def validate(self):
        if self.side not in ("yes", "no"):
            raise TradingError(f"bad side {self.side!r}")
        if self.action not in ("buy", "sell"):
            raise TradingError(f"bad action {self.action!r}")
        if self.fractional:
            if (
                not isinstance(self.count, Decimal)
                or not self.count.is_finite()
                or self.count <= 0
                or self.count % Decimal("0.01")
            ):
                raise TradingError(f"bad fixed-point count {self.count!r}")
        elif not isinstance(self.count, int) or self.count < 1:
            raise TradingError(f"bad count {self.count!r}")
        if self.time_in_force not in ("good_till_canceled", "immediate_or_cancel"):
            raise TradingError("Unsupported time_in_force")
        if self.time_in_force == "immediate_or_cancel" and (
            self.post_only or self.expiration_ts is not None
        ):
            raise TradingError("IOC cannot be post-only or have an expiration")
        if self.reduce_only and self.time_in_force != "immediate_or_cancel":
            raise TradingError("reduce_only requires IOC")
        if not isinstance(self.price_cents, int) or not 1 <= self.price_cents <= 99:
            raise TradingError(f"bad price {self.price_cents!r}")
        if self.exchange_index is not None and (
            type(self.exchange_index) is not int or not 0 <= self.exchange_index <= 100
        ):
            raise TradingError("Invalid exchange_index")
        if self.expiration_ts is not None and self.expiration_ts <= time.time():
            raise TradingError(f"expiration {self.expiration_ts} is in the past")

    def body(self):
        """V2 single-YES-book order. Preserve original outcome/action semantics.

        Buying NO == asking/selling YES at 1 - NO price; selling NO ==
        bidding/buying YES at 1 - NO price. V2 prices use dollar strings.
        """
        self.validate()
        if self.side == "yes":
            book_side = "bid" if self.action == "buy" else "ask"
            yes_cents = self.price_cents
        else:
            book_side = "ask" if self.action == "buy" else "bid"
            yes_cents = 100 - self.price_cents
        body = {
            "ticker": self.ticker,
            "client_order_id": self.client_order_id,
            "side": book_side,
            "count": f"{self.count:.2f}",
            "price": f"{yes_cents / 100:.4f}",
            "time_in_force": self.time_in_force,
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": self.post_only,
            "cancel_order_on_pause": True,
        }
        if self.exchange_index is not None:
            body["exchange_index"] = self.exchange_index
        if self.reduce_only:
            body["reduce_only"] = True
        if self.expiration_ts is not None:
            body["expiration_time"] = int(self.expiration_ts)
        return body


class TradingClient:
    def __init__(
        self, dry_run=True, env=None, key_id=None, private_key_pem=None, timeout=20
    ):
        self.dry_run = dry_run
        self.env = env or os.environ.get("KALSHI_ENV", "demo")
        if self.env not in BASES:
            raise TradingError(f"KALSHI_ENV must be one of {sorted(BASES)}")
        self.base = BASES[self.env]
        self.key_id = key_id or os.environ.get("KALSHI_KEY_ID", "")
        pem = private_key_pem or os.environ.get("KALSHI_PRIVATE_KEY", "")
        self.private_key = load_private_key(pem) if pem else None
        self.timeout = timeout
        self.log = []  # every would-be or actual write, for the ledger
        self._order_ticker_by_id = {}  # needed by V2 cancel auto-routing

    # --- plumbing -------------------------------------------------------------

    @property
    def can_sign(self):
        return bool(self.key_id and self.private_key)

    def _headers(self, method, path):
        if not self.can_sign:
            raise TradingError(
                "no credentials: set KALSHI_KEY_ID and KALSHI_PRIVATE_KEY"
            )
        ts = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sign(self.private_key, ts, method, path),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method, path, params=None, body=None):
        """One signed request. A throttled balance read (HTTP 429) is
        retried after a short wait; nothing else is retried, so an order or
        cancel is sent at most once per call."""
        full = PREFIX + path
        url = self.base + full
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        throttle_safe = method == "GET" and path in RETRY_THROTTLED_PATHS
        waits = READ_RETRY_WAITS if throttle_safe else ()
        for attempt in range(len(waits) + 1):
            request = urllib.request.Request(  # freshly signed each attempt
                url, data=data, method=method, headers=self._headers(method, full)
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as error:
                detail = error.read(500).decode("utf-8", "replace")
                if error.code == 429 and attempt < len(waits):
                    time.sleep(retry_wait(error, waits[attempt]))
                    continue
                raise TradingError(
                    f"{method} {path} -> HTTP {error.code}: {detail}"
                ) from error

    # --- reads ---------------------------------------------------------------

    def balance(self):
        """Available balance and portfolio value, in dollars; missing is unknown."""
        b = self._request("GET", "/portfolio/balance")
        result = {}
        for name in ("balance", "portfolio_value"):
            raw = b.get(name + "_dollars")
            divisor = 1 if raw is not None else 100
            if raw is None:
                raw = b.get(name)
            try:
                value = float(raw) / divisor
            except (TypeError, ValueError) as error:
                raise TradingError("Missing or invalid balance field") from error
            if not math.isfinite(value) or value < 0:
                raise TradingError("Invalid balance value")
            result[name] = value
        return result

    def _pages(self, path, key, params):
        out, cursor, seen = [], "", set()
        while True:
            query = {**params, **({"cursor": cursor} if cursor else {})}
            page = self._request("GET", path, query)
            rows = page.get(key)
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise TradingError(f"Missing or invalid {key} list")
            out.extend(rows)
            cursor = page.get("cursor") or ""
            if not cursor:
                return out
            if not isinstance(cursor, str) or cursor in seen:
                raise TradingError(f"Repeated or invalid {key} cursor")
            seen.add(cursor)

    def orders(self, status="resting", ticker=None):
        params = {"status": status, "limit": 200}
        if ticker:
            params["ticker"] = ticker
        orders = self._pages("/portfolio/orders", "orders", params)
        for order in orders:
            if order.get("order_id") and order.get("ticker"):
                self._order_ticker_by_id[order["order_id"]] = order["ticker"]
        return orders

    def fills(self, min_ts=None, ticker=None):
        params = {"limit": 200}
        if min_ts:
            params["min_ts"] = int(min_ts)
        if ticker:
            params["ticker"] = ticker
        return self._pages("/portfolio/fills", "fills", params)

    def settlements(self, min_ts=None):
        params = {"limit": 200}
        if min_ts:
            params["min_ts"] = int(min_ts)
        return self._pages("/portfolio/settlements", "settlements", params)

    def queue_position(self, order_id):
        """Contracts resting ahead of this order at its price (Kalshi's
        GET /portfolio/orders/{id}/queue_position, ``queue_position_fp``)."""
        page = self._request("GET", f"/portfolio/orders/{order_id}/queue_position")
        value = page.get("queue_position_fp", page.get("queue_position"))
        return float(value) if value is not None else None

    def positions(self):
        out, cursor, seen = [], "", set()
        while True:
            params = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", "/portfolio/positions", params)
            rows = page.get("market_positions")
            if not isinstance(rows, list):
                raise TradingError("Missing production positions list")
            out.extend(rows)
            cursor = page.get("cursor") or ""
            if not cursor:
                return out
            if cursor in seen:
                raise TradingError("Repeated positions cursor")
            seen.add(cursor)

    # --- writes ----------------------------------------------------------------

    def place(self, order):
        """Submit V2 single-book order; dry mode only validates and logs."""
        body = order.body()
        entry = {
            **body,
            "op": "place",
            "dry_run": self.dry_run,
            "env": self.env,
            "action": order.action,
            "outcome_side": order.side,
        }
        if self.dry_run:
            entry["order_id"] = "dry-run"
            self.log.append(entry)
            return entry
        if self.env == "prod" and os.environ.get("ALLOW_PRODUCTION_TRADING") != "YES":
            raise TradingError(
                "production order placement disabled: explicit ALLOW_PRODUCTION_TRADING=YES required"
            )
        if self.env == "prod" and order.exchange_index is None:
            raise TradingError(
                "Production order missing verified shard index; no POST sent"
            )
        result = self._request("POST", "/portfolio/events/orders", body=body)
        order_id = result.get("order_id")
        if not order_id:
            raise TradingError(
                "V2 placement returned no order ID; reconcile exchange before retrying"
            )
        entry["order_id"] = order_id
        entry["status"] = "placed"
        entry["fill_count"] = result.get("fill_count", "0.00")
        entry["remaining_count"] = result.get("remaining_count")
        self._order_ticker_by_id[order_id] = order.ticker
        self.log.append(entry)
        return entry

    def cancel(self, order_id, ticker=None):
        """Cancel a resting order using V2; market ticker is required for routing."""
        entry = {
            "op": "cancel",
            "dry_run": self.dry_run,
            "env": self.env,
            "order_id": order_id,
        }
        if self.dry_run or order_id == "dry-run":
            self.log.append(entry)
            return entry
        ticker = ticker or self._order_ticker_by_id.get(order_id)
        if not ticker:
            # Reconcile the current resting book instead of guessing the shard.
            for resting in self.orders("resting"):
                if resting.get("order_id") == order_id:
                    ticker = resting.get("ticker")
                    break
        if not ticker:
            raise TradingError(
                f"cannot route V2 cancellation for {order_id}; verify the order's ticker"
            )
        result = self._request(
            "DELETE",
            f"/portfolio/events/orders/{order_id}",
            params={"market_ticker": ticker},
        )
        entry["ticker"] = ticker
        entry["reduced_by"] = result.get("reduced_by")
        self.log.append(entry)
        return entry

    def cancel_all(self, ticker=None, prefixes=None, order_ids=None):
        """Cancel the strategy's resting orders and leave any other order alone.

        An order is the strategy's if its id is in ``order_ids`` (the ledger)
        or its client_order_id carries the strategy tag; ``prefixes`` further
        restricts to those markets. With neither given, every resting order.
        """
        cancelled = []
        owned = set(order_ids or [])
        for o in self.orders("resting", ticker):
            if prefixes and not str(o.get("ticker", "")).startswith(tuple(prefixes)):
                continue
            if order_ids is not None:
                mine = o.get("order_id") in owned or str(
                    o.get("client_order_id", "")
                ).startswith("smm-")
                if not mine:
                    continue
            cancelled.append(self.cancel(o["order_id"]))
        return cancelled
