"""Spread maker pilot settings (RESEARCH_LOG.md, 2026-10-22, spread maker pilot).

Two-sided quotes one cent inside wide spreads, held to settlement. Every
limit here is the pilot's; change them only through a reviewed plan that
states the old value, the new value and why.
"""

from pathlib import Path

STRATEGY_VERSION = "spread-maker-v1"
# The shared-risk cohort journal lives in STATE; the owner creates ARM_MARKER
# to allow live orders.
STATE = Path("/home/trader/prod-spread-auto")
ARM_MARKER = Path("/etc/market-maker-spread.enabled")

MIN_SPREAD_CENTS = 8
WINDOW_HOURS = (4.0, 7.0)  # hours before the market's expected expiration
PRICE_RANGE_CENTS = (2, 98)  # both of our quotes must lie inside this range
CONTRACTS = 1
MAX_NET_PER_MARKET = 1  # never quote a side already held (net) in that market
MAX_ACTIVE_COST = 25.00  # resting orders plus held contracts at cost, dollars
DAILY_LOSS_STOP = 5.00  # own realized loss, New York day, dollars
CUMULATIVE_LOSS_STOP = 15.00  # own realized loss since launch, dollars
MAX_ORDERS_PER_PASS = 20
MAX_SUBMISSIONS_PER_DAY = 300
ORDER_LIFETIME_MINUTES = 65  # orders expire on the exchange even if the bot stops
# No new order after this many seconds from process start (lock waits count):
# systemd stops the pass at 240, and one order's calls can take up to 120.
PASS_DEADLINE_SECONDS = 110
SHADOW_REPOST_MINUTES = 60  # shadow: one quote per market and side per hour

# The 66 series that passed the 10% false-discovery check at 8c+ spreads in
# the strategy sweep (RESEARCH_LOG.md, 2026-10-22), minus the series v5 and
# the NFL bot trade. Out-of-season series simply have no open markets.
SERIES = (
    "KXABAGAME",
    "KXAHLGAME",
    "KXALEAGUESPREAD",
    "KXBALGAME",
    "KXBIG3GAME",
    "KXBOXING",
    "KXBRENTD",
    "KXCLUBFBTTS",
    "KXCLUBFGAME",
    "KXCODGAME",
    "KXCODTOTALMAPS",
    "KXCS2GAME",
    "KXCSGOGAME",
    "KXDOTA2GAME",
    "KXF1RACEPODIUM",
    "KXF1TOP5",
    "KXINXDUD",
    "KXIPLFOUR",
    "KXIPLSIX",
    "KXIPLTEAMTOTAL",
    "KXITFDOUBLES",
    "KXMLBF3",
    "KXMLBF5SPREAD",
    "KXNASCARRACE",
    "KXNASCARTOP3",
    "KXNBAPTSLEADER",
    "KXNCAABBGAME",
    "KXNCAABMENTION",
    "KXNCAAFSPREAD",
    "KXNCAAHOCKEYGAME",
    "KXNCAAMB1HSPREAD",
    "KXNCAAMB1HTOTAL",
    "KXNCAAMENTION",
    "KXNCAAWBGAME",
    "KXNCAAWBSPREAD",
    "KXNCAAWBTOTAL",
    "KXNFL1Q",
    "KXNFL1QTOTAL",
    "KXNFLMENTION",
    "KXNPBSPREAD",
    "KXNWSLSPREAD",
    "KXNZNBLGAME",
    "KXOWGAME",
    "KXPLLGAME",
    "KXR6GAME",
    "KXRLGAME",
    "KXRUGBYESLMATCH",
    "KXTNOTED",
    "KXUCLTCORNERS",
    "KXUCLWADVANCE",
    "KXUCLWGAME",
    "KXUFCDISTANCE",
    "KXUFCMOF",
    "KXUFCROUNDS",
    "KXVTBGAME",
    "KXWBCF5SPREAD",
    "KXWBCGAME",
    "KXWBCSPREAD",
    "KXWC2HSPREAD",
    "KXWCSOA",
    "KXWCSTART",
    "KXWCTCORNERS",
    "KXWNBA1QSPREAD",
    "KXWT20MATCH",
)
# Never quote these: v5 and the NFL bot trade them (a shared market would
# halt every bot), whatever the series list above says.
EXCLUDED_PREFIXES = (
    "KXNBAPTS-",
    "KXNBAREB-",
    "KXNBAAST-",
    "KXNBA3PT-",
    "KXNFLRECYDS-",
    "KXNFLANYTD-",
)
# Series with a maker multiplier on Kalshi's fee schedule (checked 2026-10-22).
# None is in SERIES today; kept as a guard against a future edit.
MAKER_FEE_SERIES = frozenset(
    {
        "KXINXY",
        "KXNASDAQ100Y",
        "KXCPI",
        "KXCPIYOY",
        "KXFED",
        "KXFEDDECISION",
        "KXGDP",
        "KXPAYROLLS",
        "KXU3",
        "KXRATECUTCOUNT",
        "KXAAAGASM",
        "KXATPMATCH",
        "KXWTAMATCH",
        "KXUCL",
        "KXUCLGAME",
        "KXNBA",
        "KXNFLGAME",
        "KXMLBGAME",
        "KXNCAAFGAME",
        "KXWNBAGAME",
        "KXWCGAME",
    }
)
