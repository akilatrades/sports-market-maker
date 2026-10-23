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
# offsets), tightened after two reviews the same day, then 5 contracts an
# order with a $120 open cap ("5 contracts and higher caps").
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
# v3 "5 contracts and higher caps" (2026-10-23; the first v3 draft had 2 and
# 2, $60 and $10; v2: 5, 5, $60, $10).
CONTRACTS = 5  # largest order; it shrinks to stay inside MAX_NET_PER_MARKET
MAX_NET_PER_MARKET = 5  # held plus resting on one side of a market, contracts
MAX_ACTIVE_COST = 120.00  # resting orders plus held contracts at cost, dollars
DAILY_LOSS_STOP = 15.00  # own realized loss, New York day, dollars
CUMULATIVE_LOSS_STOP = 40.00  # own realized loss since launch, dollars
MAX_ORDERS_PER_PASS = 20
# v3: 1,500 (owner, 2026-10-23; v1-v2: 300). Each quote is re-posted at
# least hourly, so 300 would run out by early morning with ~30 markets quoted.
MAX_SUBMISSIONS_PER_DAY = 1500
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
# one_off_milestone was dropped after review: its late cases (8 of 381, all
# KXNCAABBGAME) are in a series without an offset below to catch them.
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
    }
)
NEVER_TRUSTED_MILESTONE_TYPES = frozenset({"esports_match"})
# Offset start: expected expiration - the series' gap - START_OFFSET_MARGIN_MINUTES.
# An event without a ticker time takes the EARLIER of this and any trusted
# milestone, and the earliest start ever seen for it is kept. Gaps are the
# larger of the median and the 99th percentile of (expiry - start) in the
# 2026-10-23 scan, rounded up to 15 minutes, for series whose middle half of
# gaps spanned 30 minutes or less (research.spread_start_window final;
# outputs/research/spread_v3_final.json). The first v3 draft used medians
# (KXNBAPTSLEADER 3.0, KXRLGAME 4.0, KXNCAAWBSPREAD/TOTAL 3.0) and also
# listed KXBRENTD, KXINXDUD, KXNCAAMENTION and KXNFLMENTION.
START_OFFSET_MARGIN_MINUTES = 30
SERIES_START_OFFSET_HOURS = {
    "KXABAGAME": 3.0,
    "KXAHLGAME": 3.0,
    "KXBALGAME": 3.0,
    "KXCODGAME": 4.0,
    "KXCODTOTALMAPS": 4.0,
    "KXCS2GAME": 4.0,
    "KXDOTA2GAME": 4.0,
    "KXIPLFOUR": 3.0,
    "KXIPLSIX": 3.0,
    "KXIPLTEAMTOTAL": 3.0,
    "KXMLBF3": 3.0,
    "KXMLBF5SPREAD": 3.0,
    "KXNBAPTSLEADER": 6.0,
    "KXNCAABMENTION": 5.0,
    "KXNCAAHOCKEYGAME": 3.0,
    "KXNCAAMB1HSPREAD": 3.0,
    "KXNCAAMB1HTOTAL": 3.0,
    "KXNCAAWBGAME": 3.0,
    "KXNCAAWBSPREAD": 3.5,
    "KXNCAAWBTOTAL": 3.5,
    "KXNPBSPREAD": 4.0,
    "KXNZNBLGAME": 3.0,
    "KXOWGAME": 4.0,
    "KXR6GAME": 4.0,
    "KXRLGAME": 5.75,
    "KXVTBGAME": 3.0,
    "KXWBCF5SPREAD": 3.0,
    "KXWBCGAME": 3.0,
    "KXWBCSPREAD": 3.0,
    "KXWNBA1QSPREAD": 3.0,
    "KXWT20MATCH": 4.0,
}
# Untimed events in series with no offset are read for milestones only in
# these series: in the 2026-10-23 scan, no other such series ever had a
# trusted-type milestone (4,422 of 11,263 events would only use up reads).
# Second review, 2026-10-23 (before: every untimed event was read).
MILESTONE_ONLY_SERIES = frozenset({"KXBIG3GAME"})
# Live check of the offsets: when a ticker-timed event in an offset series
# shows expiry - start larger than its gap + START_OFFSET_MARGIN_MINUTES (the
# estimate would come after the real start), that series' offset is not used
# for OFFSET_SUSPEND_DAYS. Second review, 2026-10-23 (before: no check).
OFFSET_SUSPEND_DAYS = 2
# Never quoted (owner, 2026-10-23): daily financial series whose "start" is a
# session open while the underlying futures trade overnight, so a pregame
# rule protects nothing. They stay in SERIES so the record shows the sweep.
NO_START_SERIES = frozenset({"KXBRENTD", "KXINXDUD", "KXTNOTED"})
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
