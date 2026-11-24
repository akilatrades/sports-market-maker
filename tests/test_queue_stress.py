"""Queue stress study: families, the queue filter and the candidate bar."""

import pandas as pd

from research import queue_stress as Q


def test_families_by_series_name():
    assert Q.family("KXNFLMENTION") == "mention"
    assert Q.family("KXFIGHTMENTION") == "mention"  # mention wins over combat
    assert Q.family("KXUFCMOV") == "combat"
    assert Q.family("KXNASCARRACE") == "racing"
    assert Q.family("KXNBAPTS") == "player prop"
    assert Q.family("KXMLBF5") == "part of game"
    assert Q.family("KXNBAGAME") == "game"
    assert Q.family("KXWTI") == "finance"
    assert Q.family("KXPGATOUR") == "other"


def _fills(n_events, pnl, traded, side="no", series="KXNFLMENTION"):
    rows = []
    for e in range(n_events):
        for date in ("2025-11-01", "2026-05-01"):
            rows.append({"price": 0.7, "side": side, "traded": traded,
                         "result": "no", "event_ticker": f"E{e}{date}",
                         "date": date, "won": 1, "pnl": pnl, "series": series})  # fmt: skip
    return pd.DataFrame(rows)


def test_a_queue_drops_small_fills_and_the_bar_needs_everything():
    noisy = _fills(300, 0.30, traded=10)
    noisy.loc[noisy.index % 4 < 2, "pnl"] = -0.20  # mean 5 cents in each half
    small = _fills(300, -0.50, traded=2)  # gone once 5 contracts are required
    g = Q.grid(Q.prepare(pd.concat([noisy, small])))
    row = g[(g.family == "mention") & (g.side == "no")].set_index("queue")
    assert row.loc[1, "fills"] == 1200 and row.loc[5, "fills"] == 600
    assert row.loc[5, "mean_cents"] > row.loc[1, "mean_cents"]
    picked = Q.candidates(g)
    assert [(c["family"], c["side"]) for c in picked] == [("mention", "no")]
    assert Q.candidates(g, {**Q.BAR, "events": 10_000}) == []
