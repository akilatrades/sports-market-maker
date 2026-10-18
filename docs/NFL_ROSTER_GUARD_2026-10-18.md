# NFL roster safety — October 18, 2026

The NFL trader must not treat an absent `injury_status` as healthy or use a
sportsbook line as a substitute for an unverified player identity.

## New checks

1. Obtain **current ESPN team rosters** using read-only team roster endpoints.
   Refresh the VPS cache every 20 minutes; on errors or stale cache, no new
   NFL orders may be submitted. Cache is stored outside GitHub.
2. Match the **full Kalshi NFL event ticker** to the exact away/home pairing
   and Eastern game date in the saved nflverse schedule. Validate player
   membership against exactly one of the two teams. Zero or two matches
   are blocked. The team risk limit uses the verified team, not a ticker slice.
3. Reject inactive, injury-reserve, questionable, doubtful and out statuses
   on the ESPN roster and the weekly nflverse injury report. If injury-data
   retrieval is more than 48 hours old, block all new NFL orders.
4. Require a finite timestamped model probability. A bookmaker line alone
   does **not** authorize an NFL order.
5. NFL projections now build upcoming-player candidates from the verified
   roster and historical GSIS player records, so players missing recent
   games and transfers with earlier history can be included. Ambiguous
   player identities or no historical statistics remain excluded.

## Limits that still matter

ESPN rosters and nflverse injury reports are **not** equivalent to the final
official inactive list published about 90 minutes before kickoff. The trading
rule currently posts 2–6 hours before kickoff, so late scratches remain
possible. An automatic re-check and cancellation of previously resting NFL
orders on newly reported inactives has NOT been built in this change; do not
mistake preventing new orders for protecting old resting orders.

This is a *fail-closed* safety improvement and can reduce candidate counts to
zero if sources fail, records disagree or identifiers cannot be joined. It
does not improve expected profit, fix the historically negative NFL model
comparison, or validate actual fills.

## Rollout

GitHub's code is not the running DigitalOcean deployment. After PR tests,
operator must verify a fresh ESPN roster fetch, model refresh, order counts,
and preserved orders/ledger on VPS **before** deploying. Never automate
production trading from a repository merge. Keep the Demo pilot caps until
positive post-settlement execution evidence exists.

Data-source caveat: ESPN's public site API is an unofficial data interface
and may change; loss of access must mean skip, not reuse stale data.
