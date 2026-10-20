"""Production Kalshi exchange-shard preflight. Signed GETs only.

Prediction markets can live on different exchange instances. Aggregated cash
is not proof that the instance owning a market can collateralize an order.
Never transfer funds or mutate the account from this helper.
"""

from decimal import Decimal, InvalidOperation

from kalshi.trading import TradingError


def shard_balance(balance_response, exchange_index):
    entries = balance_response.get("balance_breakdown")
    if not isinstance(entries, list):
        raise TradingError("Missing shard balance breakdown: HALT")
    seen = []
    for row in entries:
        if not isinstance(row, dict):
            raise TradingError("Malformed shard balance breakdown: HALT")
        try:
            shard = int(row["exchange_index"])
        except (KeyError, TypeError, ValueError) as error:
            raise TradingError("Invalid exchange shard in balance: HALT") from error
        if shard != exchange_index:
            continue
        value = row.get("balance")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError) as error:
            raise TradingError("Invalid shard balance amount: HALT") from error
        if not amount.is_finite() or amount < 0:
            raise TradingError("Invalid shard balance amount: HALT")
        seen.append(amount)
    if len(seen) > 1:
        raise TradingError("Duplicate exchange shard balance: HALT")
    return seen[0] if seen else Decimal("0")


def verify_market_shard(market_response):
    if not isinstance(market_response, dict):
        raise TradingError("Market shard response missing")
    market = market_response.get("market")
    if not isinstance(market, dict):
        raise TradingError("Market shard record missing")
    shard = market.get("exchange_index")
    if type(shard) is not int or not 0 <= shard <= 100:
        raise TradingError("Exchange shard missing or invalid: HALT")
    return shard


def require_funded_shard(client, ticker, reserve_dollars):
    """Return verified route, or fail without ever sending an order POST."""
    from urllib.parse import quote

    if not isinstance(ticker, str) or not ticker or not ticker.startswith("KX"):
        raise TradingError("Invalid market ticker for shard routing")
    try:
        required = Decimal(str(reserve_dollars))
    except (TypeError, InvalidOperation) as error:
        raise TradingError("Invalid reserved dollar amount") from error
    if not required.is_finite() or required <= 0:
        raise TradingError("Invalid reserved dollar amount")
    market = client._request("GET", f"/markets/{quote(ticker, safe='')}")
    shard = verify_market_shard(market)
    if market["market"].get("ticker") != ticker:
        raise TradingError("Market ticker mismatch in shard routing: HALT")
    breakdown = client._request("GET", "/portfolio/balance")
    available = shard_balance(breakdown, shard)
    if available < required:
        raise TradingError(
            f"SHARD_UNFUNDED_{shard}: Kalshi account funds are not allocated to this matching engine; no order was sent."
        )
    return shard
