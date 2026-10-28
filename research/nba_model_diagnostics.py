"""Versioned model diagnostics on the unchanged equal-size paper study."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from research import nba_entry_study as study
from research.spread_forward_core import instant
from research.spread_paper_study import interval

ROOT = Path("outputs/nba_model_diagnostics")


def input_quality(rows, at):
    counts = Counter()
    for row in rows:
        issues = []
        try:
            age = (at - instant(row["snapshot_utc"])).total_seconds()
            if not 0 <= age <= 1800:
                issues.append("projection_stale_or_future")
        except (KeyError, ValueError, TypeError):
            issues.append("projection_timestamp_unknown")
        try:
            age = (at - instant(row["book_updated_utc"])).total_seconds()
            if not (0 <= age <= 1800 and study.number(row["book_n"]) >= 2
                    and instant(row["book_commence_utc"]) == instant(row["tip_utc"])):
                issues.append("fresh_two_book_consensus_missing")
        except (KeyError, ValueError, TypeError):
            issues.append("fresh_two_book_consensus_missing")
        if row.get("minutes_estimate_source") in (None, "", "prior_games_only"):
            issues.append("tonight_minutes_unverified")
        if row.get("lineup_confirmation_status") != "confirmed":
            issues.append("lineup_unverified")
        else:
            try:
                if not 0 <= (at - instant(row["lineup_confirmed_at"])).total_seconds() <= 1800:
                    issues.append("lineup_confirmation_stale")
            except (KeyError, ValueError, TypeError):
                issues.append("lineup_confirmation_timestamp_missing")
        if row.get("injury_status"):
            issues.append("reported_injury_status")
        if str(row.get("requires_book", "")).lower() == "true":
            issues.append("history_or_team_change_requires_books")
        counts.update(issues)
        counts["fully_verified_rows"] += not issues
    return {"rows": len(rows), "issues": dict(counts),
            "meaning": "Freshly generated predictions do not establish confirmed lineups or tonight-specific minutes. Missing inputs remain unverified."}


def calibration(rows):
    buckets, games = defaultdict(list), defaultdict(list)
    errors, market_errors, book_errors = [], [], []
    forecasts, wins = [], []
    for row in rows:
        p = 1 - study.number(row["p_model_yes"])
        won = int(row["result"] == "no")
        forecasts.append(p)
        wins.append(won)
        squared = (p - won) ** 2
        errors.append(squared)
        buckets[min(9, int(p * 10))].append((p, won))
        book = row["entry_book"]
        market = (study.number(book["no"][0][0]) + 1 - study.number(book["yes"][0][0])) / 2
        market_error = (market - won) ** 2
        market_errors.append(market_error)
        games[row["game_id"]].append(squared - market_error)
        inputs = row.get("inputs", {})
        try:
            age = (instant(row["quoted_at"]) - instant(inputs["book_updated_utc"])).total_seconds()
            if 0 <= age <= 1800 and study.number(inputs["book_n"]) >= 2 and instant(inputs["book_commence_utc"]) == instant(row["tip_utc"]):
                book_errors.append(((1 - study.number(inputs["p_book"])) - won) ** 2)
        except (KeyError, ValueError, TypeError):
            pass
    n = len(rows)
    return {
        "opportunities": n, "independent_games": len(games),
        "mean_predicted_win_probability": sum(forecasts) / n if n else None,
        "actual_win_rate": sum(wins) / n if n else None,
        "model_brier": sum(errors) / n if n else None,
        "market_midpoint_brier": sum(market_errors) / n if n else None,
        "fresh_book_brier": sum(book_errors) / len(book_errors) if book_errors else None,
        "fresh_book_observations": len(book_errors),
        "model_minus_market_brier_game_95_interval": interval([sum(v) / len(v) for v in games.values()]),
        "probability_buckets": [{"forecast_range": [k / 10, (k + 1) / 10], "n": len(v),
                                 "predicted": sum(x[0] for x in v) / len(v), "actual": sum(x[1] for x in v) / len(v)} for k, v in sorted(buckets.items())],
        "note": "Lower Brier score is better. Market midpoint is a forecast benchmark, not an executable price. Book and model scores must use matched coverage for a causal comparison.",
    }


def diagnostics(state, projection_rows, at):
    rows = state.get("rows", [])
    resolved = [r for r in rows if r.get("outcome_status") == "settled" and r.get("result") in ("yes", "no")]
    sections = {"all_resolved_opportunities": calibration(resolved)}
    for assumption in study.ASSUMPTIONS:
        known = [r for r in resolved if r.get("execution_status") == "complete"]
        sections[assumption + "_filled"] = calibration([r for r in known if r["execution"][assumption]["filled"]])
        sections[assumption + "_unfilled"] = calibration([r for r in known if not r["execution"][assumption]["filled"]])
    quality = input_quality(projection_rows, at)
    return {
        "protocol": "nba-model-diagnostics-v1", "generated_at": at.isoformat(),
        "source_protocol": state.get("manifest", {}).get("protocol"),
        "input_quality": quality, "calibration": sections,
        "paper_comparison": study.report(rows),
        "promotion_status": "research_only_no_live_enable",
        "next_requirements": ["Fresh prospective games under the fixed equal-size protocol.",
                              "Model filter must improve fee-adjusted outcomes over the same-opportunity NO baseline.",
                              "Verify lineup and tonight-specific minutes before relying on model-derived sizing.",
                              "Compare filled and unfilled forecast errors by game; do not fit corrections to the evaluation games."],
    }


def run(root=ROOT):
    at = study.utcnow()
    state = json.loads(Path("outputs/nba_entry_study/state.json").read_text())
    value = diagnostics(state, study.load_csv(Path("outputs/projections/latest.csv")), at)
    study.save(root / "latest.json", value)
    print("NBA_MODEL_DIAGNOSTICS=recorded")


if __name__ == "__main__":
    run()
