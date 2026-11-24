"""research/esports_ratings.py on made-up matches (no network)."""

import numpy as np
import pandas as pd

from research import esports_ratings as E


def test_team_names_come_from_kalshis_rules_text():
    rules = (
        "If PRIVATE wins the CyberClash Closed Qualifier 2026: UPGRADE vs. PRIVATE "
        "CS2 match originally scheduled for Oct 16, 2026 at 12:00 PM EDT"
    )
    m = {"yes_sub_title": "PRIVATE", "title": "PRIVATE wins", "rules_primary": rules}
    assert E.teams_of(m) == ("private", "upgrade")
    m = {**m, "yes_sub_title": "UPGRADE", "title": "UPGRADE wins"}
    assert E.teams_of(m) == ("upgrade", "private")
    dota = (
        "If Team Liquid wins the TI 2026: Team Liquid vs. Tundra Esports Dota 2 "
        "match originally scheduled"
    )
    assert E.teams_of({"yes_sub_title": "Team Liquid", "rules_primary": dota}) == (
        "team liquid",
        "tundra esports",
    )
    assert E.teams_of({"yes_sub_title": "Nobody", "rules_primary": dota}) is None


def test_team_names_come_from_the_subtitle_and_title():
    m = {
        "yes_sub_title": "Team Vitality",
        "title": "Will Team Vitality win the Vitality vs. NAVI match?",
    }
    assert E.teams_of({"yes_sub_title": "FaZe", "title": "FaZe vs NAVI"}) == (
        "faze",
        "navi",
    )
    assert E.teams_of({"yes_sub_title": "NAVI", "title": "FaZe vs. NAVI"}) == (
        "navi",
        "faze",
    )
    assert E.teams_of({"yes_sub_title": "", "title": "FaZe vs NAVI"}) is None
    assert E.teams_of(m) in (("team vitality", "navi"), None)


def match(i, team, opp, won, bid=0.45, ask=0.47, hours=0):
    start = pd.Timestamp("2026-01-01T00:00Z") + pd.Timedelta(hours=6 * i + hours)
    return {
        "series": "KXCS2GAME",
        "title": "cs2",
        "event_ticker": f"E{i}",
        "ticker": f"T{i}",
        "team": team,
        "opponent": opp,
        "start_utc": start.isoformat(),
        "result": "yes" if won else "no",
        "yes_bid": bid,
        "yes_ask": ask,
        "last_price": ask,
        "candle_utc": "",
    }


def test_elo_uses_only_finished_matches():
    rows = [match(0, "a", "b", True), match(1, "a", "b", True)]
    # A third match starting 1 hour after the second cannot use its result.
    rows.append(
        {**match(1, "a", "b", True, hours=1), "event_ticker": "E2", "ticker": "T2"}
    )
    m = E.elo(pd.DataFrame(rows))
    assert m.p_elo.iloc[0] == 0.5
    assert m.p_elo.iloc[1] > 0.5 and m.p_elo.iloc[2] == m.p_elo.iloc[1]
    assert m.n_team.tolist() == [0, 1, 1]


def test_the_rule_buys_the_cheap_side_and_pays_the_fee():
    f = pd.DataFrame(
        {
            "event_ticker": ["x", "y", "z"],
            "title": ["cs2"] * 3,
            "p_elo": [0.70, 0.30, 0.50],
            "yes_bid": [0.58, 0.58, 0.48],
            "yes_ask": [0.60, 0.60, 0.50],
            "y": [1.0, 0.0, 1.0],
        }
    )
    b = E.rule(f)
    # x: Elo 70 vs ask 60 -> buy YES, wins 40c less 2c fee; y: NO at 42 vs 70 -> buy NO.
    assert b.event.tolist() == ["x", "y"]
    assert np.allclose(b.pnl, [1 - 0.60 - 0.02, 1 - 0.42 - 0.02])


def test_a_strong_team_is_found_and_scored_end_to_end():
    rng = np.random.default_rng(0)
    teams = [f"t{i}" for i in range(8)]
    strength = {t: i for i, t in enumerate(teams)}
    rows = []
    for i in range(600):
        a, b = rng.choice(teams, 2, replace=False)
        p = 1 / (1 + 10 ** ((strength[b] - strength[a]) / 4))
        # Kalshi's price ignores strength: always a coin flip.
        mid = rng.uniform(0.35, 0.65)  # noise around a coin flip
        rows.append(match(i, a, b, rng.random() < p, bid=mid - 0.01, ask=mid + 0.01))
    s = E.summarize(pd.DataFrame(rows))
    assert s["matches_scored"] > 400
    assert s["second_half"]["logloss_elo"] < s["second_half"]["logloss_mid"]
    assert s["rule"]["bets"] > 0 and s["rule"]["cents_per_contract"] > 0
