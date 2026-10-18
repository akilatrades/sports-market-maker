"""Conservative maker-fee bounds from current series and event metadata."""

import math

from kalshi.api import get_json
from kalshi.trading import TradingError


def maker_fee_bound(price, count, series, event):
    kind = event.get("fee_type_override") or series.get("fee_type")
    multiplier = event.get("fee_multiplier_override")
    if multiplier is None:
        multiplier = series.get("fee_multiplier")
    try:
        multiplier = float(multiplier)
    except (TypeError, ValueError) as error:
        raise TradingError("unknown_fee_multiplier") from error
    if not math.isfinite(multiplier) or multiplier < 0:
        raise TradingError("invalid_fee_multiplier")
    if kind == "quadratic":
        rate = 0.0
    elif kind == "quadratic_with_maker_fees":
        rate = 0.0175 * multiplier
    else:
        raise TradingError("unsupported_fee_type")
    # Whole contracts / whole-cent prices. Cent rounding per one-contract
    # fill is deliberately conservative for both direct and FCM members.
    per_contract = math.ceil(rate * price * (1 - price) * 100 - 1e-12) / 100
    return round(count * per_contract, 6)


def live_maker_fee_bound(ticker, price, count):
    series_ticker, event_suffix, *_ = ticker.split("-")
    event_ticker = series_ticker + "-" + event_suffix
    series = get_json(f"/series/{series_ticker}", {}, retries=1)
    event = get_json(f"/events/{event_ticker}", {}, retries=1)
    if not isinstance(series, dict) or not isinstance(event, dict):
        raise TradingError("fee_metadata_unavailable")
    s, e = series.get("series", {}), event.get("event", {})
    if s.get("ticker") != series_ticker or e.get("event_ticker") != event_ticker:
        raise TradingError("fee_metadata_identity")
    return maker_fee_bound(price, count, s, e), {
        "fee_type": e.get("fee_type_override") or s.get("fee_type"),
        "fee_multiplier": e.get("fee_multiplier_override")
        if e.get("fee_multiplier_override") is not None else s.get("fee_multiplier"),
    }
