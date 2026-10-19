"""Publish redacted, exchange-verified NFL/NBA settlement totals to GitHub Pages.

Must be run from the trading Droplet with Kalshi production GET-only
credentials. By default PRINTS ONLY a public-safe summary. Publishing is
opt-in and requires a separate least-privilege GitHub Contents token.

Never includes balances, position/order identities, journal entries, player
names, market tickers, trades, private URLs or credentials in the published file.
The public site is a lagged 10-15-minute snapshot, NOT streaming real-time.
"""

import argparse
import base64
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from live.account_dashboard import ReadOnlyClient, cohort_settled_pnl, read_journal

REPO = "akilatrades/sports-market-maker"
PUBLISHED = "outputs/dashboard/production_pnl.json"
API = f"https://api.github.com/repos/{REPO}/contents/{PUBLISHED}"
JOURNALS = {
    "nfl": Path("/home/trader/prod-nfl-auto/journal.jsonl"),
    "nba": Path("/home/trader/prod-nba-auto/journal.jsonl"),
}


def build_report(cohorts, exchange_fills, settlements, now):
    """Turn private portfolio data into explicit aggregate-only public values."""
    if now.tzinfo is None:
        raise ValueError("timestamp_must_have_timezone")
    markets = {}
    for market in ("nfl", "nba"):
        events = cohorts.get(market)
        if events is None:
            markets[market] = {
                "status": "unavailable",
                "settled_profit_dollars": None,
                "settled_markets": None,
                "exchange_accepted_orders": None,
                "note": "Production cohort journal unavailable; no P&L assertion.",
            }
            continue
        outcome = cohort_settled_pnl(events, settlements, exchange_fills)
        state = outcome["status"]
        if state in {"cost_or_ownership_mismatch", "incomplete_settlement"}:
            # Don't publish a newly timestamped report masking a reconciliation
            # error. The public UI's expiration logic will hide old P&L.
            raise ValueError(f"{market}_pnl_reconciliation_incomplete")
        profit = outcome.get("settled_profit_dollars")
        if state == "verified" and (not isinstance(profit, (int, float))):
            raise ValueError(f"{market}_invalid_realized_profit")
        markets[market] = {
            "status": "verified_snapshot" if state == "verified" else state,
            "settled_profit_dollars": round(profit, 2) if state == "verified" else None,
            "settled_markets": outcome.get("settled_markets"),
            "exchange_accepted_orders": outcome.get("accepted_orders"),
            "note": (
                "Realized P&L only on reconciled settlement markets, after "
                "verified owned fill cost and exchange-reported fees. Open "
                "positions, cash movements and unsettled orders excluded."
            ),
        }
    # Intentionally choose an ALLOWLIST, never copy an account response or
    # settlement object into the public JSON.
    return {
        "schema_version": 1,
        "as_of_utc": now.astimezone(UTC).isoformat(),
        "source": (
            "Signed read-only Kalshi production fills/settlements; "
            "matched to separate private NFL and NBA order journals"
        ),
        "refresh_type": "automated_signed_aggregate_snapshot_not_real_time",
        "markets": markets,
    }


def collect_report(now=None, client=None, journals=None):
    now = now or datetime.now(UTC)
    client = client or ReadOnlyClient()
    paths = journals or JOURNALS
    cohorts = {}
    for name in ("nfl", "nba"):
        path = paths[name]
        cohorts[name] = read_journal(path) if path.exists() else None
    starts = [
        datetime.fromisoformat(e["utc"]).timestamp()
        for events in cohorts.values()
        if events is not None
        for e in events
        if e.get("event") == "intent"
    ]
    params = {"min_ts": int(min(starts)) - 60} if starts else {}
    # All exchange operations use ReadOnlyClient, which disallows writes.
    fills = client.pages("/portfolio/fills", "fills", **params) if starts else []
    settlements = (
        client.pages("/portfolio/settlements", "settlements", **params)
        if starts
        else []
    )
    return build_report(cohorts, fills, settlements, now)


def call_github(method, url, token, payload=None):
    if not token:
        raise RuntimeError("github_public_pnl_publisher_token_not_configured")
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "public-aggregate-kalshi-pnl-publisher",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except (HTTPError, URLError) as error:
        # Never print exception strings or request metadata: auth tokens,
        # endpoint responses and internal account details must remain private.
        raise RuntimeError(
            f"github_publisher_request_failed_{type(error).__name__}"
        ) from None


def publish(report, token):
    response = call_github("GET", API, token)
    previous = json.loads(base64.b64decode(response["content"]))
    prev_date = datetime.fromisoformat(previous["as_of_utc"].replace("Z", "+00:00"))
    next_date = datetime.fromisoformat(report["as_of_utc"])
    if next_date <= prev_date:
        raise ValueError("refuse_to_publish_older_or_equal_production_snapshot")
    encoded = base64.b64encode(
        (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    ).decode()
    call_github(
        "PUT",
        API,
        token,
        {
            "message": "Refresh sanitized NFL/NBA signed settlement snapshot (data only)",
            "branch": "main",
            "sha": response["sha"],
            "content": encoded,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Explicitly publish aggregate report using GitHub token",
    )
    args = parser.parse_args()
    try:
        report = collect_report()
        if args.publish:
            publish(report, os.environ.get("GITHUB_PNL_PUBLISH_TOKEN", ""))
            print(
                "PUBLIC NBA/NFL SETTLEMENT SNAPSHOT PUBLISHED (no account identifiers)"
            )
        else:
            print(json.dumps(report, indent=2, allow_nan=False))
            print("READ ONLY: nothing published; set --publish for opt-in.")
    except Exception as error:
        # Keep the error type and safe code only, not raw exchange body.
        print(
            f"PUBLIC PNL REPORT NOT VERIFIED/PUBLISHED: {type(error).__name__}",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
