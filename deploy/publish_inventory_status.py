"""Publish only allowlisted droplet health fields to the triggering GitHub commit.

This avoids exposing SSH logs, account balances, credentials, or positions in
public commit statuses. No trading or remote control functionality lives here.
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen


def describe_inventory(report: str) -> tuple[str, str]:
    def field(name: str) -> str:
        match = re.search(rf"^{re.escape(name)} active=([a-z-]+)\b", report, re.M)
        return match.group(1) if match else "unknown"

    timer = field("market-maker.timer")
    nba = field("prod-nba-auto.service")
    nfl = field("prod-nfl-auto.service")
    modules = set(re.findall(r"^runner_module=(live\.[a-z_]+)$", report, re.M))
    if "live.prod_nba_auto" in modules or "live.prod_nfl_auto" in modules:
        runner = "prod"
    elif "live.nba_trade" in modules:
        runner = "legacy"
    else:
        runner = "unknown"
    revision = re.search(r"^repo_commit=([0-9a-f]{40})$", report, re.M)
    rev = revision.group(1)[:8] if revision else "unknown"
    info = f"timer={timer} nba={nba} nfl={nfl} runner={runner} repo={rev}"
    ok = "inventory_utc=" in report and timer != "unknown"
    return ("success" if ok else "failure"), info


def main() -> None:
    path = Path(sys.argv[1])
    report = path.read_text(encoding="utf-8") if path.exists() else ""
    state, description = describe_inventory(report)
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["GITHUB_SHA"]
    url = f"https://api.github.com/repos/{repo}/statuses/{sha}"
    body = {
        "state": state,
        "context": "droplet/diagnostic-inventory",
        "description": description,
        "target_url": (
            f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        ),
    }
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        if response.status != 201:
            raise RuntimeError("GitHub rejected inventory status update")
    print(f"Published redacted inventory status: {description}")


if __name__ == "__main__":
    main()
