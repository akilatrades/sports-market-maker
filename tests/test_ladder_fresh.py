"""Fresh-data ladder rule and ladder checks on a tiny fake dataset (no network)."""

import pandas as pd

from research import ladder_checks as K
from research import ladder_fresh as F

OCC = pd.Timestamp("2026-11-10T04:00:00Z")  # tip-off about 01:00 UTC
STRIKES = (9.5, 14.5, 19.5, 24.5, 29.5)
MIDS = (0.90, 0.75, 0.58, 0.30, 0.12)  # 19.5 sits above a smooth curve


def write(tmp, series="KXNBAREB"):
    tickers = [f"{series}-26NOV09NYKBOS-NYKJBRUNSON11-{int(s + 0.5)}" for s in STRIKES]
    pd.DataFrame({"ticker": tickers, "floor_strike": STRIKES, "occurrence_datetime": OCC.isoformat(),
                  "close_time": OCC.isoformat(), "expected_expiration_time": OCC.isoformat(),
                  "result": "no"}).to_parquet(tmp / f"markets_{series}.parquet")  # fmt: skip
    hour = int((OCC - pd.Timedelta(hours=5)).timestamp())
    rows = []
    for tk, mid in zip(tickers, MIDS):
        rows.append(
            {
                "ticker": tk,
                "end_ts": hour,
                "yes_bid": mid - 0.02,
                "yes_ask": mid + 0.02,
                "volume": 5,
            }
        )
        rows.append(
            {
                "ticker": tk,
                "end_ts": hour + 4 * 3600,
                "yes_bid": mid - 0.02,
                "yes_ask": mid + 0.02,
                "volume": 5,
            }
        )  # in-game: dropped
    pd.DataFrame(rows).to_parquet(tmp / f"candles_{series}.parquet")
    trade_time = pd.Timestamp(hour + 600, unit="s", tz="UTC").isoformat()
    pd.DataFrame({"ticker": [tickers[2]], "created_time": [trade_time], "yes_price": [0.60],
                  "count": [7.0], "taker_outcome_side": ["yes"]}).to_parquet(tmp / f"trades_{series}.parquet")  # fmt: skip


def test_the_frozen_rule_fills_the_kinked_strike_on_fresh_nba_data(
    tmp_path, monkeypatch
):
    write(tmp_path)
    monkeypatch.setattr(F, "DATA", tmp_path)
    c, t = F.load("nba", data=tmp_path)
    assert len(c) == 5  # pre-game candles only
    out = F.run(c, t, "nba")
    assert (
        out["outlier_before_haircut"]["fills"] == 1 and out["pass"] is False
    )  # far too few
    assert F.load("other", data=tmp_path)[0].empty  # NBA files are not "other" sports


def test_capacity_counts_contracts_behind_a_four_contract_queue():
    f = pd.DataFrame(
        {
            "traded": [5.0, 9.0, 30.0],
            "pnl": [0.10, 0.10, -0.50],
            "month": ["2026-01"] * 3,
        }
    )
    got = K.capacity(f)
    assert (
        got["1"]["contracts_filled"] == 3
        and got["10"]["contracts_filled"] == 1 + 5 + 10
    )
