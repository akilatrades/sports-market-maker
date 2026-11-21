"""The NBA player-pool page: its numbers and how it is built (no network)."""

import json
import re

import numpy as np
import pandas as pd
import pytest

from research import nba_player_pool_dashboard as D

TEAMS = {"BOS": "F", "NY": "G"}  # NY is ESPN's spelling; the page shows NYK


def box_scores(seasons=(2026, 2027), games=12, per_team=6, seed=0):
    """Two teams playing each other, a few games a season."""
    rng = np.random.default_rng(seed)
    rows = []
    for season in seasons:
        start = pd.Timestamp(f"{season - 1}-11-01 00:00", tz="UTC")
        for game in range(games):
            tip = start + pd.Timedelta(days=2 * game)
            for t, (team, position) in enumerate(TEAMS.items()):
                for n in range(per_team):
                    minutes = float(rng.integers(12, 38))
                    fga = int(rng.integers(3, 20))
                    fta = int(rng.integers(0, 8))
                    rows.append(
                        {
                            "game_id": season * 1000 + game,
                            "season": season,
                            "season_type": "regular",
                            "tip_utc": tip,
                            "team": team,
                            "player_id": 1000 * (t + 1) + n,
                            "player": f"{team} Player {n}",
                            "position": position,
                            "starter": n < 5,
                            "did_not_play": False,
                            "minutes": minutes,
                            "points": float(fga + fta + rng.integers(0, 6)),
                            "rebounds": float(rng.integers(0, 12)),
                            "assists": float(rng.integers(0, 9)),
                            "threes": float(rng.integers(0, 5)),
                            "fg3a": float(rng.integers(0, 9)),
                            "fga": float(fga),
                            "fta": float(fta),
                            "tov": float(rng.integers(0, 5)),
                        }
                    )
    return pd.DataFrame(rows)


def projections():
    return pd.DataFrame(
        {
            "snapshot_utc": "2026-11-21T00:07:16.961699+00:00",
            "tip_utc": "2026-11-21 03:00:00+00:00",
            "ticker": [
                "KXNBAPTS-26NOV20BOSNYK-BOSP0-20",
                "KXNBAPTS-26NOV20BOSNYK-BOSP0-25",
                "KXNBAPTS-26NOV20BOSNYK-NYKP1-15",
            ],
            "event_ticker": "KXNBAPTS-26NOV20BOSNYK",
            "player": ["BOS Player 0", "BOS Player 0", "NY Player 1"],
            "player_id": [1000, 1000, 2001],
            "player_key": ["bos player 0", "bos player 0", "ny player 1"],
            "team": ["BOS", "BOS", "NYK"],
            "stat": "points",
            "line": [19.5, 24.5, 14.5],
            "model_mean": [21.0, 21.0, 12.0],
            "p_model": [0.55, 0.31, 0.30],
            "yes_bid_dollars": [0.52, 0.28, 0.0],
            "yes_ask_dollars": [0.54, 0.30, 0.33],
            "injury_status": [None, None, "Day-To-Day"],
        }
    )


def books():
    return pd.DataFrame(
        {
            "player_key": ["bos player 0", "bos player 0", "someone else"],
            "stat": "points",
            "line": [19.5, 22.5, 19.5],  # only the first sits on a Kalshi line
            "away": "BOS",
            "home": "NYK",
            "p_book": [0.57, 0.44, 0.50],
            "book_n": [5, 7, 3],
            "updated_utc": "2026-11-21 00:05:00+00:00",
            "commence_utc": "2026-11-21 03:00:00+00:00",
        }
    )


def test_usage_and_true_shooting_follow_the_box_score_arithmetic():
    one_game = pd.DataFrame(
        {
            "game_id": 1,
            "season": 2027,
            "season_type": "regular",
            "tip_utc": pd.Timestamp("2026-11-01", tz="UTC"),
            "team": "NY",
            "player_id": range(5),
            "player": [f"P{n}" for n in range(5)],
            "position": "G",
            "did_not_play": False,
            "minutes": [48.0, 48.0, 48.0, 48.0, 48.0],
            "points": [30.0, 10.0, 10.0, 10.0, 10.0],
            "rebounds": 5.0,
            "assists": 5.0,
            "threes": 1.0,
            "fga": [20.0, 5.0, 5.0, 5.0, 5.0],
            "fta": [0.0, 0.0, 0.0, 0.0, 0.0],
            "tov": [0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )
    table = D.season_table(one_game, 2027)
    # He took 20 of the team's 40 shots while playing every minute.
    assert table.usage.iloc[0] == pytest.approx(0.5)
    assert table.usage.iloc[1] == pytest.approx(0.125)
    assert table.usage.sum() == pytest.approx(1.0)
    assert table.ts.iloc[0] == pytest.approx(30 / (2 * 20))
    assert table.team.iloc[0] == "NYK"
    assert table.games.iloc[0] == 1 and table.points.iloc[0] == 30.0


def test_a_player_who_sat_does_not_count_as_a_game():
    players = box_scores(seasons=(2027,), games=4)
    sat = (players.player_id == 1000) & (players.game_id == 2027 * 1000 + 3)
    players.loc[sat, ["did_not_play", "minutes"]] = [True, 0.0]
    table = D.season_table(players, 2027)
    assert table.loc[1000, "games"] == 3 and table.loc[1001, "games"] == 4


def test_the_baseline_for_the_next_game_uses_only_earlier_games():
    players = box_scores()
    last = players.tip_utc.max()
    earlier = players[players.tip_utc < last]
    # What the page would have shown before the final game ...
    shown = D.current_state(earlier, 2027)
    # ... is exactly what the check scores that game against.
    before = D.pregame_state(players)
    before = before[before.tip_utc == last].set_index("player_id")
    for column in ["proj_minutes"] + [f"proj_{stat}" for stat in D.STATS]:
        pd.testing.assert_series_equal(
            shown.loc[before.index, column],
            before[column],
            check_names=False,
            check_exact=False,
        )
    # Changing how the final game went cannot change its own projection.
    changed = players.copy()
    changed.loc[changed.tip_utc == last, "points"] += 40
    again = D.pregame_state(changed)
    again = again[again.tip_utc == last].set_index("player_id")
    pd.testing.assert_series_equal(again.proj_points, before.proj_points)


def test_the_baseline_is_half_rates_and_half_recent_form():
    state = pd.DataFrame(
        {"ew_minutes": [30.0]}
        | {f"rate_{stat}": [0.8] for stat in D.STATS}
        | {f"ew_{stat}": [20.0] for stat in D.STATS}
    )
    out = D.baseline(state)
    assert D.BLEND == 0.5
    assert out.proj_points.iloc[0] == pytest.approx(0.5 * 0.8 * 30 + 0.5 * 20)
    assert out.proj_minutes.iloc[0] == 30.0


def test_the_check_reports_both_methods_on_the_same_games():
    players = box_scores(games=16)
    check = D.check_baseline(players, 2026)
    assert check["season"] == "2025-26"
    # Each of the 12 players is scored from his sixth game of the season on.
    assert check["player_games"] == 12 * (16 - D.MIN_GAMES_FOR_CHECK)
    for stat in D.STATS:
        assert check[f"miss_baseline_{stat}"] > 0
        assert check[f"miss_average_{stat}"] > 0
    assert all(swing > 0 for _, swing in check["swing_curve"])


def test_the_swing_follows_the_curve_and_grows_past_its_end():
    curve = [[5.0, 4.0], [15.0, 6.0], [25.0, 8.0]]
    swing = D.points_swing(pd.Series([5.0, 10.0, 25.0, 36.0, 2.0]), curve)
    assert swing.tolist()[:3] == pytest.approx([4.0, 5.0, 8.0])
    assert swing.iloc[3] == pytest.approx(8.0 * (36 / 25) ** 0.5)
    assert swing.iloc[4] == pytest.approx(4.0)  # never below the lowest level
    assert D.points_swing(pd.Series([10.0]), []).isna().all()


def test_value_is_zero_at_the_replacement_rank():
    players = box_scores(per_team=120, games=3)
    check = D.check_baseline(players, 2026)
    table = D.player_rows(players, 2027, check["swing_curve"])
    regulars = table[table.proj_minutes >= D.VALUE_MINUTES]
    ranked = regulars.value.sort_values(ascending=False)
    assert len(ranked) > D.REPLACEMENT_RANK
    assert ranked.iloc[D.REPLACEMENT_RANK - 1] == pytest.approx(0.0)
    assert ranked.iloc[0] > 0 > ranked.iloc[-1]
    assert sum(D.VALUE_WEIGHTS.values()) == pytest.approx(1.0)


def test_the_payload_is_strict_json_with_real_prices_only():
    payload = D.build_payload(box_scores(), projections(), books())
    text = json.dumps(payload, allow_nan=False)  # raises on NaN or infinity
    # The same inputs give the same payload: no clock in it.
    assert payload == D.build_payload(box_scores(), projections(), books())
    assert payload["meta"]["season"] == "2026-27"
    assert len(payload["players"]) == 12
    first = payload["players"][0]
    assert {"player_id", "player", "team", "proj_points", "swing", "value"} <= set(
        first
    )
    slate = payload["slate"]
    assert slate["columns"] == D.SLATE_COLUMNS and len(slate["rows"]) == 3
    assert slate["snapshot_utc"] == "2026-11-21T00:07:16.961699+00:00"
    # Only the sportsbook line that sits exactly on a Kalshi line is kept.
    assert payload["books"]["columns"] == D.BOOK_COLUMNS
    assert [row[:3] for row in payload["books"]["rows"]] == [
        ["bos player 0", "points", 19.5]
    ]
    # A missing injury status is null, not the text "nan".
    assert slate["rows"][0][slate["columns"].index("injury_status")] is None
    for word in ("simulat", "placeholder", "mkt_", "best_edge"):
        assert word not in text.lower()


def test_the_page_builds_without_price_files():
    payload = D.build_payload(box_scores(), None, None)
    assert payload["slate"] == {
        "snapshot_utc": None,
        "columns": D.SLATE_COLUMNS,
        "rows": [],
    }
    assert payload["books"]["rows"] == []
    assert len(payload["players"]) == 12


def test_render_fills_the_template_and_cannot_close_the_script_early():
    template = D.TEMPLATE.read_text("utf-8")
    assert template.count(D.PLACEHOLDER) == 1
    players = box_scores()
    players.loc[players.player_id == 1000, "player"] = "</script><b>x"
    page = D.render(D.build_payload(players, projections(), books()), template)
    assert D.PLACEHOLDER not in page
    assert page.count("</script>") == template.count("</script>")
    assert "<\\/script><b>x" in page
    with pytest.raises(ValueError):
        D.render({}, "no placeholder here")


def test_the_committed_page_is_the_template_plus_data():
    """Edit the template and rebuild; never edit the built page by hand."""
    page = D.PAGE.read_text("utf-8")
    lines = page.split("\n")
    at = [n for n, line in enumerate(lines) if line.startswith("const PAYLOAD = ")]
    assert len(at) == 1
    payload = json.loads(lines[at[0]][len("const PAYLOAD = ") : -1])
    lines[at[0]] = f"const PAYLOAD = {D.PLACEHOLDER};"
    assert "\n".join(lines) == D.TEMPLATE.read_text("utf-8")
    assert len(payload["players"]) > 300
    assert payload["slate"]["columns"] == D.SLATE_COLUMNS
    # No made-up market prices: the old page's simulated columns are gone.
    assert not re.search(r"mkt_|best_edge|placeholder market", page, re.IGNORECASE)


def test_the_pool_is_tonights_slate_and_earlier_nights_drop_off():
    """Last night's games must not linger on the page as "tonight"."""
    template = D.TEMPLATE.read_text("utf-8")
    # The Players tab can be limited to the teams with a game today.
    assert 'id="p-tonight"' in template
    assert "teams.has(r.team)" in template
    # A night ends at 5am Eastern; rows from an earlier night are left out,
    # and "PTS tonight" is filled from today's games only.
    assert "const DAY_STARTS_HOUR = 5;" in template
    assert 'timeZone: "America/New_York"' in template
    assert "slateDay(r.tip) < today" in template
    assert "slateDay(r.tip) === today) tonight.set(r.id, r.mean)" in template


def test_best_plays_take_their_numbers_from_the_nba_bot():
    """The "Best plays" filter repeats the bot's entry tests. The numbers
    travel with the data, so a rule change reaches the page without an edit."""
    from kalshi.maker import maker_fee
    from kalshi.paper_props import FEE_SHARE
    from live import prod_nba_auto as bot

    rules = D.best_play_rules()
    band = (round(rules["no_min"] * 100), round(rules["no_max"] * 100))
    assert band == tuple(bot.PRICE_BAND_CENTS)
    assert rules["edge_min"] == bot.ENTRY_MIN_NET_EDGE
    assert rules["edge_max"] == bot.MAX_ENTRY_NET_EDGE
    assert rules["book_minutes"] == bot.BOOK_MAX_AGE_MINUTES
    assert (rules["hours_min"], rules["hours_max"]) == tuple(bot.WINDOW)
    assert rules["min_books"] == bot.MIN_BOOKS
    assert rules["rules"] in bot.STRATEGY_VERSION
    # fee_rate x price x (1 - price) is the bot's maker fee at any price.
    for price in (0.65, 0.8, 0.95):
        fee = float(maker_fee(price, FEE_SHARE))
        assert rules["fee_rate"] * price * (1 - price) == pytest.approx(fee)

    # They ride in the payload and in the data file an open page reloads.
    payload = D.build_payload(box_scores(), projections(), books())
    assert payload["meta"]["best_plays"] == rules
    assert D.player_file(payload)["meta"]["best_plays"] == rules

    # The page reads the same names and keeps its own copy only as a fallback.
    template = D.TEMPLATE.read_text("utf-8")
    fallback = re.search(r"const BEST_FALLBACK = \{([^}]*)\};", template).group(1)
    names = {pair.split(":")[0].strip() for pair in fallback.split(",")}
    assert names == set(rules)
    assert "META.best_plays" in template
    assert 'id="s-best"' in template


def test_the_data_file_holds_the_players_tab_and_is_rewritten_alone(
    tmp_path, monkeypatch
):
    players = tmp_path / "players.parquet"
    box_scores().to_parquet(players)
    page, data = tmp_path / "page.html", tmp_path / "pool" / "latest.json"
    argv = ["build", "--players", str(players), "--projections", "none.csv"]
    argv += ["--books", "none.csv", "--out", str(page), "--data", str(data)]
    monkeypatch.setattr("sys.argv", argv + ["--data-only"])
    D.main()
    assert data.exists() and not page.exists()
    saved = json.loads(data.read_text("utf-8"))
    assert set(saved) == {"meta", "players"}
    assert len(saved["players"]) == 12
    assert saved["meta"]["season"] == "2026-27"
    assert saved["meta"]["box_scores_through_utc"].startswith("2026-11-23")
    first = data.read_bytes()
    # Without the flag the page is built too, and the data file is unchanged:
    # the workflow commits it only when the box scores have changed.
    monkeypatch.setattr("sys.argv", argv)
    D.main()
    assert page.exists() and data.read_bytes() == first
    built = json.loads(
        next(
            line[len("const PAYLOAD = ") : -1]
            for line in page.read_text("utf-8").split("\n")
            if line.startswith("const PAYLOAD = ")
        )
    )
    assert built["players"] == saved["players"] and built["meta"] == saved["meta"]
