"""Public production-source contract check. Never authenticates or trades."""

import json
from datetime import UTC, datetime, timedelta

import pandas as pd

from kalshi.api import get_json, snapshot
from kalshi.fees import maker_fee_bound
from markets.nba.kalshi import SERIES, parse
from markets.nba.live import injuries, rosters, scoreboard


def main():
    now = datetime.now(UTC)
    season = now.year + (now.month >= 8)
    day = pd.Timestamp(now).tz_convert("America/New_York").date()
    games = pd.concat(
        [scoreboard(f"{day + timedelta(days=i):%Y%m%d}", season) for i in range(3)],
        ignore_index=True,
    )
    games = games[~games.completed & (games.tip_utc > now)]
    teams = set(games.home) | set(games.away)
    roster = rosters(teams)
    report = injuries()
    if not report.empty:
        if (
            report.player_id.isna().any()
            or pd.to_datetime(report.updated, utc=True, errors="coerce").isna().any()
        ):
            raise ValueError("Injury rows lack identity or update time")
    markets = parse(snapshot(SERIES, now=now))
    ladder_pairs = 0
    dislocations = []
    if not markets.empty:
        for _, group in markets.groupby(["event_ticker", "player_key", "stat"]):
            ordered = list(group.sort_values("line").itertuples())
            for i, low in enumerate(ordered):
                for high in ordered[i+1:]:
                    if low.line >= high.line:
                        continue
                    a, b = float(low.yes_ask_dollars), 1-float(high.yes_bid_dollars)
                    if not (0 < a < 1 and 0 < b < 1):
                        continue
                    ladder_pairs += 1
                    # Screening only; verify fees, size and both settlement
                    # rules before treating any crossed ladder as executable.
                    fee = sum(__import__("math").ceil(.07*p*(1-p)*100-1e-12)/100 for p in (a,b))
                    if 1-a-b-fee > .01:
                        dislocations.append({"low":low.ticker, "high":high.ticker, "screen_edge":round(1-a-b-fee,6)})
    fees = {}
    for series in SERIES:
        payload = get_json(f"/series/{series}", {}, retries=1)["series"]
        fees[series] = {
            "type": payload["fee_type"],
            "multiplier": payload["fee_multiplier"],
            "four_contract_fee_bound_at_60c": maker_fee_bound(0.6, 4, payload, {}),
        }
    print(
        json.dumps(
            {
                "utc": now.isoformat(),
                "games": games[["game_id", "home", "away", "tip_utc"]]
                .astype(str)
                .to_dict("records"),
                "roster_counts": {k: len(v) for k, v in roster.items()},
                "injury_rows": len(report),
                "open_prop_markets": len(markets),
                "ladder_pairs_screened": ladder_pairs,
                "ladder_dislocations_needing_rules_depth_review": dislocations,
                "series_fees": fees,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
