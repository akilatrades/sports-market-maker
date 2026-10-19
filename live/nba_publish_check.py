"""Validate publishable NBA model inputs before GitHub Actions makes them public.

This command is read-only: no authenticated Kalshi calls, no trading, no writes.
"""
import argparse
import csv
import io
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from live.nba_inputs import validate


def inspect(data, meta, now):
    age = validate(data, meta, now)
    if not isinstance(meta.get("rows"), int) or meta["rows"] < 0:
        raise ValueError("invalid_model_row_count")
    if meta["rows"] > 0 and (
        meta.get("open_markets", 0) <= 0 or meta.get("schedule_games", 0) <= 0
    ):
        raise ValueError("positive_rows_without_live_games_or_markets")
    if (meta.get("schedule_games", 0) > 0 and meta.get("open_markets", 0) > 0
            and meta["rows"] == 0):
        raise ValueError("open_games_and_props_but_no_priced_rows")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    required = {
        "ticker", "p_model", "tip_utc", "injury_status", "game_id",
        "player_id", "requires_book", "team_espn",
    }
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("missing_published_projection_columns")
    seen = set()
    rows = 0
    for row in reader:
        rows += 1
        ticker = row["ticker"]
        if not ticker or ticker in seen:
            raise ValueError("empty_or_duplicate_projection_ticker")
        seen.add(ticker)
        try:
            probability = float(row["p_model"])
            tip = datetime.fromisoformat(row["tip_utc"].replace("Z", "+00:00"))
        except (ValueError, TypeError) as error:
            raise ValueError("invalid_projection_probability_or_tip") from error
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("invalid_projection_probability")
        if tip.tzinfo is None:
            raise ValueError("unaware_projection_tip")
    if rows != meta["rows"]:
        raise ValueError("published_projection_row_count_mismatch")
    return {
        "generated_utc": meta["generated_utc"],
        "age_hours": round(age, 3),
        "rows": rows,
        "schedule_games": meta.get("schedule_games"),
        "open_markets": meta.get("open_markets"),
        "checksum": meta["sha256"],
        "status": "validated_research_inputs_not_trading_approval",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("outputs/projections"))
    args = parser.parse_args()
    data = (args.directory / "latest.csv").read_bytes()
    meta = json.loads((args.directory / "latest_meta.json").read_text())
    print(json.dumps(inspect(data, meta, datetime.now(UTC)), indent=2))


if __name__ == "__main__":
    main()
