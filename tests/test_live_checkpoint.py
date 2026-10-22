"""The live checkpoint report: pre-registered verdicts on a synthetic export."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from research import live_checkpoint as cp

NOW = datetime(2026, 11, 30, tzinfo=UTC)


def _csv(path, rows):
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def nba_export(root, games=40, win=True, days_ago=31):
    start = NOW - timedelta(days=days_ago)
    orders, fills, settled = [], [], []
    for g in range(games):
        for k in range(3):
            ticker = f"KXNBAPTS-G{g}-P{k}"
            ref = f"o{g}-{k}"
            orders.append(
                {
                    "order_ref": ref,
                    "intent_utc": (start + timedelta(hours=g)).isoformat(),
                    "ticker": ticker,
                    "cost": 0.5,
                    "game_id": g,
                    "status": "accepted",
                    "filled_contracts": 1,
                    "strategy_version": cp.NBA_VERSION,
                }
            )
            fills.append({"order_ref": ref, "ticker": ticker, "count": 1})
            profit = 0.5 if (win and (g + k) % 4) else -0.5
            settled.append(
                {
                    "ticker": ticker,
                    "net_profit_dollars": profit,
                    "accounting_complete": True,
                }
            )
    _csv(root / "data/nba/orders/2026-10-22.csv", orders)
    _csv(root / "data/nba/fills/2026-10-22.csv", fills)
    _csv(root / "data/nba/settlements/2026-10-22.csv", settled)


def spread_export(root, pair_price=(41, 49), share=0.4, days_ago=29, n=40):
    start = NOW - timedelta(days=days_ago)
    orders, fills, settled = [], [], []
    for i in range(n):
        ticker, event = f"KXDOTA2GAME-E{i}-A", f"KXDOTA2GAME-E{i}"
        for side, price in zip(("yes", "no"), pair_price):
            ref = f"s{i}{side}"
            orders.append(
                {
                    "order_ref": ref,
                    "intent_utc": start.isoformat(),
                    "ticker": ticker,
                    "event_ticker": event,
                    "side": side,
                    "status": "accepted",
                }
            )
            fills.append(
                {
                    "fill_ref": f"f{ref}",
                    "order_ref": ref,
                    "ticker": ticker,
                    "fill_utc": (
                        start + timedelta(minutes=5 if side == "yes" else 9)
                    ).isoformat(),
                    "side": side,
                    "count": 5,
                    "price": price / 100,
                }
            )
        settled.append({"ticker": ticker, "market_result": "yes"})
    _csv(root / "data/spread/orders/2026-10-22.csv", orders)
    _csv(root / "data/spread/fills/2026-10-22.csv", fills)
    _csv(root / "data/spread/settlements/2026-10-22.csv", settled)
    summary = {
        "markets": {
            "spread": {
                "data_through_utc": NOW.isoformat(),
                "live_fill_share": {"fill_share": share},
            }
        },
        "spread_shadow_simulated": {
            "first_in_line": {"cents_per_contract": 6.0},
            "flow_share_0.25": {"cents_per_contract": 5.0},
        },
    }
    (root / "data/summary.json").write_text(json.dumps(summary))


def test_nba_positive_and_significant_after_30_days(tmp_path):
    nba_export(tmp_path)
    r = cp.no_bot(tmp_path / "data/nba", NOW, cp.NBA_VERSION)
    assert r["settled_markets"] == 120 and r["games"] == 40
    progress, verdict = cp.nba_verdict(r)
    assert r["cents_per_contract"] > 0 and r["t_game_clustered"] >= 2
    assert "edge is real" in verdict


def test_nba_before_the_checkpoint_is_inconclusive(tmp_path):
    nba_export(tmp_path, games=5, days_ago=3)
    _, verdict = cp.nba_verdict(cp.no_bot(tmp_path / "data/nba", NOW, cp.NBA_VERSION))
    assert "not reached" in verdict and "inconclusive" in verdict


def test_spread_pairs_and_fill_share(tmp_path):
    spread_export(tmp_path, share=0.6)
    summary = json.loads((tmp_path / "data/summary.json").read_text())
    r = cp.spread_bot(tmp_path / "data/spread", NOW, summary)
    # Each market: 5 pairs at 41c + 49c = +$0.50 on 10 contracts.
    assert r["net_profit_dollars"] == pytest.approx(20.0) and r[
        "cents_per_contract"
    ] == pytest.approx(5.0)
    assert r["filled_contracts"] == 400 and r["events"] == 40
    _, verdict = cp.spread_verdict(r)
    assert verdict.startswith("Checkpoint reached: live profit per contract above zero")


def test_spread_low_fill_share_means_stop_and_review(tmp_path):
    spread_export(tmp_path, share=0.3)
    summary = json.loads((tmp_path / "data/summary.json").read_text())
    _, verdict = cp.spread_verdict(
        cp.spread_bot(tmp_path / "data/spread", NOW, summary)
    )
    assert "under half the shadow's" in verdict


def test_unresolved_spread_markets_are_excluded_not_guessed(tmp_path):
    spread_export(tmp_path, pair_price=(41, 49))
    path = tmp_path / "data/spread/fills/2026-10-22.csv"
    lines = path.read_text().splitlines()
    path.write_text(
        "\n".join(line for line in lines if "nof" not in line and "s0no" not in line)
        + "\n"
    )
    (tmp_path / "data/spread/settlements/2026-10-22.csv").write_text(
        "ticker,market_result\n"
    )
    summary = json.loads((tmp_path / "data/summary.json").read_text())
    r = cp.spread_bot(tmp_path / "data/spread", NOW, summary)
    assert r["open_markets_excluded"] == 1  # one market holds a lone YES, no result yet


def test_report_refuses_data_inside_the_public_repo(tmp_path):
    with pytest.raises(SystemExit, match="outside this public repository"):
        cp.main(["--data", str(cp.ROOT / "outputs")])


def test_report_labels_live_and_simulated(tmp_path):
    nba_export(tmp_path)
    spread_export(tmp_path)
    text = cp.report(tmp_path, NOW)
    assert "LIVE CHECKPOINT REPORT" in text and "SIMULATED (not added" in text
    assert "NBA (nba-no-v5" in text and "SPREAD MAKER" in text
