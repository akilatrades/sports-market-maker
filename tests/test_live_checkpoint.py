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
    # One market holds a lone YES with no result yet: left out, never guessed.
    assert r["markets_with_held_contracts_excluded"] == 1
    # Closed pairs count at once, even with no settlement record (Kalshi nets
    # YES against NO): the other 39 markets.
    assert r["resolved_markets"] == 39
    assert r["cents_per_contract"] == pytest.approx(5.0)


def test_spread_pairs_in_a_market_still_holding_contracts_count(tmp_path):
    spread_export(tmp_path, n=1)
    path = tmp_path / "data/spread/fills/2026-10-22.csv"
    lines = path.read_text().splitlines()
    # A third fill: 2 more YES at 41c, unpaired and unresolved.
    lines.append(lines[1].replace("fs0yes", "fs0yes2").replace(",5,", ",2,"))
    path.write_text("\n".join(lines) + "\n")
    (tmp_path / "data/spread/settlements/2026-10-22.csv").write_text(
        "ticker,market_result\n"
    )
    r = cp.spread_bot(tmp_path / "data/spread", NOW, {})
    assert r["markets_with_held_contracts_excluded"] == 1
    # The 5 closed pairs (10 contracts, +$0.50) count; the 2 held YES wait.
    assert r["resolved_contracts"] == 10
    assert r["net_profit_dollars"] == pytest.approx(0.5)


def test_spread_fees_are_subtracted(tmp_path):
    spread_export(tmp_path, n=1)
    path = tmp_path / "data/spread/fills/2026-10-22.csv"
    lines = path.read_text().splitlines()
    lines[0] += ",fee"
    lines[1:] = [line + ",0.0118" for line in lines[1:]]
    path.write_text("\n".join(lines) + "\n")
    r = cp.spread_bot(tmp_path / "data/spread", NOW, {})
    # 5 pairs on 10 contracts: +$0.50 less two fills' fees.
    assert r["cents_per_contract"] == pytest.approx(100 * (0.5 - 2 * 0.0118) / 10)


def test_spread_total_stop_uses_the_bots_ledger(tmp_path):
    spread_export(tmp_path, days_ago=2, n=2)
    summary = json.loads((tmp_path / "data/summary.json").read_text())
    summary["markets"]["spread"]["realized_pnl_dollars"] = -40.5
    r = cp.spread_bot(tmp_path / "data/spread", NOW, summary)
    # Before the checkpoint, and despite positive paired fills here.
    _, verdict = cp.spread_verdict(r)
    assert "total loss stop" in verdict


def test_spread_checkpoint_without_a_fill_share_says_so(tmp_path):
    spread_export(tmp_path, share=None)
    summary = json.loads((tmp_path / "data/summary.json").read_text())
    _, verdict = cp.spread_verdict(
        cp.spread_bot(tmp_path / "data/spread", NOW, summary)
    )
    assert "fill share has not been measured" in verdict


def test_nba_allowance_is_counted_as_the_bot_counts_it(tmp_path):
    from live import prod_nba_auto

    nba_export(tmp_path, games=2, days_ago=3)
    path = tmp_path / "data/nba/orders/2026-10-22.csv"
    lines = path.read_text().splitlines()
    # An older-version order still counts against the bot's allowance.
    lines.append(lines[1].replace(cp.NBA_VERSION, "nba-no-v4").replace("o0-0", "old"))
    path.write_text("\n".join(lines) + "\n")
    r = cp.no_bot(tmp_path / "data/nba", NOW, cp.NBA_VERSION)
    assert r["orders"] == 6
    assert r["allowance_used_dollars"] == pytest.approx(7 * prod_nba_auto.reserve(0.5))
    assert cp._reserve(0.37) == prod_nba_auto.reserve(0.37)
    assert cp.NBA_FEE_RESERVE == prod_nba_auto.FEE_RESERVE  # no silent drift


def test_nba_cases_the_plan_does_not_cover_are_left_to_the_owner():
    base = {"settled_fills": 1900, "allowance_used_dollars": 0, "days": 31}
    _, verdict = cp.nba_verdict(
        {**base, "cents_per_contract": -0.5, "t_game_clustered": -0.4}
    )
    assert "do not cover" in verdict
    _, verdict = cp.nba_verdict(
        {**base, "cents_per_contract": 1.0, "t_game_clustered": None}
    )
    assert "cannot be computed" in verdict


def test_report_refuses_data_inside_the_public_repo(tmp_path):
    with pytest.raises(SystemExit, match="outside this public repository"):
        cp.main(["--data", str(cp.ROOT / "outputs")])


def test_report_labels_live_and_simulated(tmp_path):
    nba_export(tmp_path)
    spread_export(tmp_path)
    text = cp.report(tmp_path, NOW)
    assert "LIVE CHECKPOINT REPORT" in text and "SIMULATED (not added" in text
    assert "NBA (nba-no-v7" in text and "SPREAD MAKER" in text


def test_spread_v2_is_judged_on_its_own_orders(tmp_path):
    spread_export(tmp_path, n=4)
    path = tmp_path / "data/spread/orders/2026-10-22.csv"
    lines = path.read_text().splitlines()
    lines[0] += ",strategy_version"
    # Markets 0 and 1 were quoted under v1, 2 and 3 under v2.
    lines[1:] = [
        line + ("," + ("spread-maker-v1" if i < 4 else cp.SPREAD_VERSION))
        for i, line in enumerate(lines[1:])
    ]
    path.write_text("\n".join(lines) + "\n")
    summary = json.loads((tmp_path / "data/summary.json").read_text())
    r = cp.spread_bot(tmp_path / "data/spread", NOW, summary)
    assert r["orders"] == 4 and r["filled_contracts"] == 20
    assert r["earlier_versions"] == {
        "orders": 4,
        "filled_contracts": 20.0,
        "versions": ["spread-maker-v1"],
    }
    text = cp.report(tmp_path, NOW)
    assert "earlier rules (spread-maker-v1)" in text and "not judged" in text


V5 = "nba-no-v5-one-contract-breadth"


def test_nba_versions_can_be_judged_together_counting_orders(tmp_path):
    nba_export(tmp_path, games=2, days_ago=3)
    for kind in ("orders", "fills"):
        path = tmp_path / f"data/nba/{kind}/2026-10-22.csv"
        rows = path.read_text().splitlines()
        if kind == "orders":
            rows[1] = rows[1].replace(cp.NBA_VERSION, V5)
            rows[2] = rows[2].replace(",1,", ",3,")  # a v6 order filled 3 contracts
        else:
            rows[2] = rows[2].replace(",1", ",3")
        path.write_text("\n".join(rows) + "\n")
    # v7 is judged on its own orders (it prices from the books, not the model).
    assert cp.NBA_VERSIONS == ("nba-no-v7-book-priced",)
    assert cp.NBA_BARS == {
        "settled_fills": 1900,
        "allowance_dollars": 5000.0,
        "days": 30,
    }
    both = cp.no_bot(tmp_path / "data/nba", NOW, (V5, cp.NBA_VERSION))
    # Six filled orders, eight contracts: the bar counts orders.
    assert both["settled_fills"] == 6 and both["settled_contracts"] == 8
    # A blank filled_contracts on the order does not hide its fills.
    path = tmp_path / "data/nba/orders/2026-10-22.csv"
    rows = path.read_text().splitlines()
    rows[3] = rows[3].replace(",accepted,1,", ",accepted,,")
    path.write_text("\n".join(rows) + "\n")
    pair = cp.no_bot(tmp_path / "data/nba", NOW, (V5, cp.NBA_VERSION))
    assert pair["settled_fills"] == 6
    v5 = cp.no_bot(tmp_path / "data/nba", NOW, V5)
    assert v5["orders"] == 1 and v5["settled_fills"] == 1
    text = cp.report(tmp_path, NOW)
    assert "nba-no-v7-book-priced: 5 orders" in text  # v5's order is not v7's


def test_the_checkpoint_judges_the_spread_bots_current_rules():
    from live import spread_policy

    assert cp.SPREAD_VERSION == spread_policy.STRATEGY_VERSION  # no silent drift
