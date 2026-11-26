"""Tourist map: the score's directions and walk-forward selection (no data files)."""

import pandas as pd

from research import tourist_map as T


def _orders(series, spread, volume, first, n=40, pnl=0.0):
    days = pd.date_range(first, periods=n, freq="D")
    return pd.DataFrame({"series": series, "event_ticker": [f"{series}-{i}" for i in range(n)],
                         "date": days.strftime("%Y-%m-%d"), "yes_bid": 0.40,
                         "yes_ask": 0.40 + spread, "volume": volume, "traded": 10,
                         "pnl": pnl, "result": "no", "side": "no"})  # fmt: skip


def test_wide_quiet_young_series_score_highest():
    d = T.prepare(pd.concat([
        _orders("KXOLD", 0.01, 500, "2025-09-11"),
        _orders("KXTOURIST", 0.20, 1, "2025-10-01"),
        _orders("KXMID", 0.05, 50, "2025-09-20"),
    ]))  # fmt: skip
    start = pd.Timestamp("2025-11-01")
    s = T.scores(d[d.day < start], start)
    assert s.score.idxmax() == "KXTOURIST" and s.score.idxmin() == "KXOLD"
    assert s.loc["KXOLD", "age"] == float("inf")  # seen in the scan's first two weeks


def test_selection_uses_only_earlier_months():
    early = _orders("KXA", 0.20, 1, "2025-09-25", n=36)  # through October
    late = _orders("KXB", 0.20, 1, "2025-11-02", n=40)  # first seen in November
    d = T.prepare(pd.concat([early, late]))
    chosen, eligible = T.picks(d, pd.Period("2025-11", "M"), 1.0, 5, "tourist")
    assert eligible == {"KXA"} and chosen == {"KXA"}  # KXB is invisible in November
