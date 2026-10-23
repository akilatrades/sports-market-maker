"""Spread maker pilot settings (RESEARCH_LOG.md, 2026-10-22, spread maker pilot).

Two-sided quotes one cent inside wide spreads, held to settlement. Every
limit here is the pilot's; change them only through a reviewed plan that
states the old value, the new value and why.
"""

from pathlib import Path

# v2 (2026-10-23): pregame only. v1 could quote into a live event, because
# its window counts from Kalshi's expected expiration, not the start.
# v3 (2026-10-23, RESEARCH_LOG.md "Spread maker v3"): quotes from 24 hours
# before expiry, more start times (validated milestone types, per-series
# offsets), 2 contracts an order.
STRATEGY_VERSION = "spread-maker-v3-24h-starts"
# The shared-risk cohort journal lives in STATE; the owner creates ARM_MARKER
# to allow live orders.
STATE = Path("/home/trader/prod-spread-auto")
ARM_MARKER = Path("/etc/market-maker-spread.enabled")

MIN_SPREAD_CENTS = 8
WINDOW_HOURS = (4.0, 24.0)  # hours before the market's expected expiration (v2: 4-7)
PRICE_RANGE_CENTS = (2, 98)  # both of our quotes must lie inside this range
# Sizes and stops: owner's 5-contract amendment (RESEARCH_LOG.md, 2026-10-22,
# "5 contracts per order"; old values 1 contract, 1 net, $25, $5, $15), then
# v3's smaller orders across more markets (2026-10-23; v2: 5 and 5).
CONTRACTS = 2  # largest order; it shrinks to stay inside MAX_NET_PER_MARKET
MAX_NET_PER_MARKET = 2  # held plus resting on one side of a market, contracts
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
MIN_LEAD_MINUTES = 85  # ORDER_LIFETIME_MINUTES + CANCEL_LEAD_MINUTES
# Twice the timer's 10 minutes, so a start learned or moved late is still
# caught before the event.
CANCEL_LEAD_MINUTES = 20
# A milestone's start counts only if it falls within this many hours before
# the market's expected expiration (a tournament's start, days earlier, does
# not count).
MILESTONE_WINDOW_HOURS = 12
START_CACHE_MINUTES = 30  # milestone answers are reused for this long
# Milestone starts are used for events without a ticker time only by
# milestone type, and only for TRUSTED_MILESTONE_TYPES: each matched the
# ticker's start (MILESTONE_AGREE_MINUTES earlier to MILESTONE_LATE_MINUTES
# later) on 95% or more of at least 314 events in the 2026-10-23 scan
# (RESEARCH_LOG.md, "Spread maker, more pregame fills: results"). Live, up
# to MILESTONE_CHECKS ticker-timed events (one per series) are compared each
# pass, and a type seen later than a ticker time is distrusted for
# MILESTONE_TRUST_DAYS. esports_match was late on 51% of events: never trusted.
# (v2 trusted any type after 2 live matches.)
MILESTONE_CHECKS = 4
MILESTONE_AGREE_MINUTES = 15
MILESTONE_LATE_MINUTES = 2
MILESTONE_TRUST_DAYS = 2
TRUSTED_MILESTONE_TYPES = frozenset(
    {
        "baseball_game",
        "basketball_game",
        "cricket_match",
        "hockey_tournament",
        "one_off_milestone",
    }
)
NEVER_TRUSTED_MILESTONE_TYPES = frozenset({"esports_match"})
# Events with neither a ticker time nor a trusted milestone: start = expected
# expiration - the series' usual gap - START_OFFSET_MARGIN_MINUTES. Medians of
# (expiry - start) in the 2026-10-23 scan, for series whose middle half of
# gaps spanned 30 minutes or less.
START_OFFSET_MARGIN_MINUTES = 30
SERIES_START_OFFSET_HOURS = {
    "KXABAGAME": 3.0,  # 137 events
    "KXAHLGAME": 3.0,  # 344 events
    "KXBALGAME": 3.0,  # 37 events
    "KXBRENTD": 7.0,  # 116 events
    "KXCODGAME": 4.0,  # 143 events
    "KXCODTOTALMAPS": 4.0,  # 139 events
    "KXCS2GAME": 4.0,  # 313 events
    "KXDOTA2GAME": 4.0,  # 254 events
    "KXINXDUD": 9.5,  # 98 events
    "KXIPLFOUR": 3.0,  # 54 events
    "KXIPLSIX": 3.0,  # 54 events
    "KXIPLTEAMTOTAL": 3.0,  # 50 events
    "KXMLBF3": 3.0,  # 348 events
    "KXMLBF5SPREAD": 3.0,  # 377 events
    "KXNBAPTSLEADER": 3.0,  # 90 events
    "KXNCAABMENTION": 5.0,  # 101 events
    "KXNCAAHOCKEYGAME": 3.0,  # 299 events
    "KXNCAAMB1HSPREAD": 3.0,  # 298 events
    "KXNCAAMB1HTOTAL": 3.0,  # 307 events
    "KXNCAAMENTION": 5.0,  # 27 events
    "KXNCAAWBGAME": 3.0,  # 374 events
    "KXNCAAWBSPREAD": 3.0,  # 60 events
    "KXNCAAWBTOTAL": 3.0,  # 60 events
    "KXNFLMENTION": 5.0,  # 32 events
    "KXNPBSPREAD": 4.0,  # 266 events
    "KXNZNBLGAME": 3.0,  # 100 events
    "KXOWGAME": 4.0,  # 274 events
    "KXR6GAME": 4.0,  # 271 events
    "KXRLGAME": 4.0,  # 94 events
    "KXVTBGAME": 3.0,  # 140 events
    "KXWBCF5SPREAD": 3.0,  # 42 events
    "KXWBCGAME": 3.0,  # 74 events
    "KXWBCSPREAD": 3.0,  # 48 events
    "KXWNBA1QSPREAD": 3.0,  # 194 events
    "KXWT20MATCH": 4.0,  # 280 events
}
MAX_START_LOOKUPS_PER_PASS = 60  # v2: 30; the 24-hour window holds more events
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
