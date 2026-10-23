"""Spread maker pilot settings (RESEARCH_LOG.md, 2026-10-22, spread maker pilot).

Two-sided quotes one cent inside wide spreads, held to settlement. Every
limit here is the pilot's; change them only through a reviewed plan that
states the old value, the new value and why.
"""

from pathlib import Path

# v2 (2026-10-23): pregame only. v1 could quote into a live event, because
# its window counts from Kalshi's expected expiration, not the start.
STRATEGY_VERSION = "spread-maker-v2-pregame"
# The shared-risk cohort journal lives in STATE; the owner creates ARM_MARKER
# to allow live orders.
STATE = Path("/home/trader/prod-spread-auto")
ARM_MARKER = Path("/etc/market-maker-spread.enabled")

MIN_SPREAD_CENTS = 8
WINDOW_HOURS = (4.0, 7.0)  # hours before the market's expected expiration
PRICE_RANGE_CENTS = (2, 98)  # both of our quotes must lie inside this range
# Sizes and stops: owner's 5-contract amendment (RESEARCH_LOG.md, 2026-10-22,
# "5 contracts per order"). Old values: 1 contract, 1 net, $25, $5, $15.
CONTRACTS = 5  # largest order; it shrinks to stay inside MAX_NET_PER_MARKET
MAX_NET_PER_MARKET = 5  # held plus resting on one side of a market, contracts
MAX_ACTIVE_COST = 60.00  # resting orders plus held contracts at cost, dollars
DAILY_LOSS_STOP = 10.00  # own realized loss, New York day, dollars
CUMULATIVE_LOSS_STOP = 40.00  # own realized loss since launch, dollars
MAX_ORDERS_PER_PASS = 20
MAX_SUBMISSIONS_PER_DAY = 300
ORDER_LIFETIME_MINUTES = 65  # orders expire on the exchange even if the bot stops
# No new order after this many seconds from process start (lock waits count).
# Checked again just before each order is journaled; from there one order's
# signed calls take at most about 80 s, inside systemd's 240 s limit.
PASS_DEADLINE_SECONDS = 110
SHADOW_REPOST_MINUTES = 60  # shadow: one quote per market and side per hour

# Pregame only (RESEARCH_LOG.md, 2026-10-23, "Spread maker v2: pregame only").
# New rules, no old values: v1 had no start-time check. A market is quoted
# only when its event's start time is known (written in the event ticker, in
# New York time, or from Kalshi's milestones) and at least MIN_LEAD_MINUTES
# away, so a 65-minute order expires at least CANCEL_LEAD_MINUTES before the
# start; any resting quote that close to the start is cancelled.
MIN_LEAD_MINUTES = 75  # ORDER_LIFETIME_MINUTES + CANCEL_LEAD_MINUTES
CANCEL_LEAD_MINUTES = 10
# A milestone's start counts only if it falls within this many hours before
# the market's expected expiration (a tournament's start, days earlier, does
# not count).
MILESTONE_WINDOW_HOURS = 12
START_CACHE_MINUTES = 30  # milestone answers are reused for this long
# Milestone starts are trusted only while they match the start written in
# event tickers: up to MILESTONE_CHECKS such events are compared each pass
# (cached as above), at least one must match and none may be further off
# than MILESTONE_AGREE_MINUTES.
MILESTONE_CHECKS = 3
MILESTONE_AGREE_MINUTES = 15
MAX_START_LOOKUPS_PER_PASS = 30
START_LOOKUP_SECONDS = 45  # no milestone read after this, from process start

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
# None is in SERIES; kept as a guard against a future edit. KXNCAAFSPREAD,
# which is in SERIES, turned out to pay a maker fee too (live fills, 22 Oct);
# the owner chose to keep it (RESEARCH_LOG.md). Fees count in realized P&L.
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
