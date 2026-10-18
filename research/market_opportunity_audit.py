"""Bounded public production liquidity census; quotes are not evidence of edge."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from kalshi.api import get_json

SERIES = (
    "KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT", "KXNBAGAME",
    "KXNHLGAME", "KXMLBGAME", "KXITFMATCH", "KXNCAAMB1HSPREAD",
    "KXNWSLSPREAD", "KXLALIGASPREAD", "KXNASCARRACE", "KXUFCMOF",
    "KXHIGHCHI", "KXHIGHLAX", "KXRAINNYC", "KXBTC", "KXBTC15M",
    "KXETH15M", "KXCPI", "KXFED", "KXPAYROLLS",
)


def inspect(series):
    meta = get_json(f"/series/{series}", {}, retries=1)
    if not meta or "series" not in meta:
        return {"series": series, "status": "series_unavailable"}
    rows, seen, cursor = [], set(), ""
    for _ in range(3):
        params = {"series_ticker":series, "status":"open", "limit":200}
        if cursor:
            params["cursor"] = cursor
        page = get_json("/markets", params, retries=1)
        if not page or not isinstance(page.get("markets"), list):
            raise ValueError("missing_markets_list")
        rows.extend(page["markets"])
        cursor = page.get("cursor") or ""
        if not cursor:
            break
        if cursor in seen:
            raise ValueError("repeated_cursor")
        seen.add(cursor)
    m = meta["series"]
    result = {"series":series, "category":m.get("category"), "title":m.get("title"),
              "fee_type":m.get("fee_type"), "fee_multiplier":m.get("fee_multiplier"),
              "sampled_open_markets":len(rows), "pagination_complete":not bool(cursor),
              "status":"ok", "edge_established":False}
    if not rows:
        return result
    f = pd.DataFrame(rows).drop_duplicates("ticker")
    def numeric(column):
        return pd.to_numeric(f[column], errors="coerce") if column in f else pd.Series(float("nan"), index=f.index)
    bid, ask = numeric("yes_bid_dollars"), numeric("yes_ask_dollars")
    valid = (bid > 0) & (ask < 1) & (bid < ask)
    result.update(two_sided=int(valid.sum()), median_spread_cents=float(((ask-bid)[valid]*100).median()) if valid.any() else None,
                  volume_24h_contracts=float(numeric("volume_24h_fp").sum()),
                  open_interest_contracts=float(numeric("open_interest_fp").sum()))
    top = f.assign(v=numeric("volume_24h_fp")).sort_values("v", ascending=False).head(3)
    columns = [c for c in ("ticker","title","yes_bid_dollars","yes_ask_dollars","yes_bid_size_fp","yes_ask_size_fp","volume_24h_fp","close_time","expected_expiration_time") if c in top]
    result["sample_markets"] = top[columns].where(pd.notna(top[columns]), None).to_dict("records")
    return result


def main():
    now = datetime.now(UTC)
    results = []
    for series in SERIES:
        try:
            results.append(inspect(series))
        except Exception as error:
            results.append({"series":series, "status":type(error).__name__, "edge_established":False})
    payload = {"as_of_utc":now.isoformat(), "source":"Kalshi public production API",
               "scope":"At most 600 open markets per named series, page order may bias coverage; no trading and no fair-value inference.",
               "series":results}
    out = Path("outputs/launch_audit_20261018")
    out.mkdir(parents=True, exist_ok=True)
    (out / "production_liquidity.json").write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"utc":now.isoformat(), "series":[{k:v for k,v in r.items() if k != "sample_markets"} for r in results]}, indent=2))


if __name__ == "__main__":
    main()
