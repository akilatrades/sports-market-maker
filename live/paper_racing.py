"""Racing markets, a forward paper test (RESEARCH_LOG.md, 2026-11-26,
"Racing markets, a forward paper test"). Paper only: nothing reaches Kalshi.

The same engine and rule as live/paper_mentions.py (NO one cent inside the
spread, 4-7 hours before expected expiration, resting one hour, first-in-line
fills from public trades), on F1, IndyCar, MotoGP and NASCAR series. Ledger:
outputs/paper_racing/.

    python -m live.paper_racing --due
    python -m live.paper_racing
"""

import sys
from pathlib import Path

from live import paper_mentions

OUT = Path("outputs/paper_racing")
PASS_EVENTS = 20  # one race has several markets (RESEARCH_LOG.md)
PREFIXES = ("KXF1", "KXINDYCAR", "KXMOTOGP", "KXNASCAR")
# The racing series in the cross-market scan, fixed before any paper order.
SERIES = [
    "KXF1", "KXF1DELAY", "KXF1FASTESTLAP", "KXF1FASTLAP", "KXF1H2H", "KXF1POLE",
    "KXF1POLEPOSITION", "KXF1RACE", "KXF1RACEPODIUM", "KXF1RACESPRINT",
    "KXF1SPRINTPOLE", "KXF1SPRINTTOP10", "KXF1SPRINTTOP5", "KXF1TOP10", "KXF1TOP5",
    "KXF1TOPCONSTRUCTOR", "KXINDYCARRACE", "KXINDYCARTOP10", "KXINDYCARTOP3",
    "KXINDYCARTOP5", "KXMOTOGPRACE", "KXNASCAR", "KXNASCARFASTLAP", "KXNASCARH2H",
    "KXNASCARPOLE", "KXNASCARRACE", "KXNASCARTOP10", "KXNASCARTOP20",
    "KXNASCARTOP3", "KXNASCARTOP5", "KXNASCARTOPTEAM",
]  # fmt: skip


def is_racing(ticker):
    return str(ticker).startswith(PREFIXES)


def main(argv=None):
    return paper_mentions.main(
        argv, out=OUT, fixed=SERIES, match=is_racing, pass_events=PASS_EVENTS
    )


if __name__ == "__main__":
    sys.exit(main())
