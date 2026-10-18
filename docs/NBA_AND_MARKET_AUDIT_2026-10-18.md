# NBA launch and cross-market research audit

**Assessment:** NBA is the best-supported candidate in this repository for a small production execution experiment. Sustainable live profitability is **not established**. Keep the approved limits; do not broaden to other markets just to generate fills. The deployment instructions are in [PROD_NBA_AUTO.md](../deploy/PROD_NBA_AUTO.md).

This audit combines source inspection, reanalysis of historical production-market observations, current public API checks and primary exchange/data-provider documentation. No demo-market liquidity was used as evidence. No account orders were placed by this audit.

## What this strategy does

It is a **one-sided passive NO strategy holding inventory to settlement**, not a continuously hedged two-sided market maker. A good entry can have positive expected value and still lose its entire cost on one outcome. More fills can increase losses if informed traders accept stale quotes.

Estimated edge per NO contract is `1 − P(YES) − NO price − execution fees`. Realized profit is exchange payout minus actual entry cost and fees, including any fair-value settlement reported by the exchange. Cash spent is not itself a realized loss. Portfolio marks and bid markouts differ from settlement P&L. Operating costs must eventually be covered separately.

## NBA: recomputed evidence

The derived historical file contains 4,862 possible NO fills from 151 games in 2025–26. These were preselected by the simulator's fill rule, not accepted in your account. Standard errors and a seeded 5,000-resample bootstrap cluster by game. The intervals below are game-clustered t intervals, without adjustment for all prior strategy exploration.

| Historical subset | Possible fill rows | Games | Mean ¢/contract | 95% interval, ¢ |
|---|---:|---:|---:|---:|
| All sampled NO fills | 4,862 | 151 | +2.04 | −0.20 to +4.27 |
| Original sportsbook veto | 1,647 | 146 | +3.81 | +0.66 to +6.97 |
| Book where covered, model otherwise | 2,578 | 149 | +3.53 | +1.00 to +6.07 |
| Above, 10–90¢ prices and 0–15¢ estimated edge | 2,254 | 148 | +3.60 | +0.87 to +6.32 |
| Two books plus price/edge bounds | 1,033 | 142 | +3.98 | −0.01 to +7.96 |
| Same subset, conservative one-contract fee rounding | 1,033 | 142 | +3.40 | −0.59 to +7.39 |
| Above, positive estimated edge after that fee bound | 747 | 138 | +3.71 | −0.66 to +8.09 |

The last rows are **sensitivity analyses, not a backtest of the complete launch worker**. The file cannot reproduce today's roster gates, all unfilled orders, one-hour expiry, pilot budget, actual queue or current fees. Reusing history to inspect safeguards does not create a new holdout. Bootstrap and t intervals differ around zero; do not choose whichever produces a favorable label.

The original book-filtered regular-season subset averaged +3.78¢ over 133 games. Its playoff subset averaged +4.71¢ over just 12 games, with an interval crossing zero. These support studying the price filter; they do not establish an opening-night or playoff advantage. Opening-week roles differ substantially from established rotations.

The existing model-refresh study provides another warning: gradient boosting improved log loss from 0.30380 to 0.30247 but did not improve profit per quoted opportunity. The hierarchical variant's P&L improvement had t≈1.62. There is no compelling evidence for replacing the four existing marginal models immediately before launch. Prioritize identity, timestamps, role/minutes uncertainty and execution. Prediction accuracy alone is insufficient.

### Fees, fills and business economics

Starting from the conservative two-book estimate of 3.40¢, **additional** deterioration of 1¢, 2¢ or 4¢ gives 2.40¢, 1.40¢ or −0.60¢ per captured contract. These are stress scenarios, not forecasts. Existing historical markout work shows about −1.16¢ in NO midpoint movement five minutes after possible fills. Do not subtract that again from settlement returns: subsequent price changes are already incorporated in final outcomes. Markouts diagnose fill quality and early-exit costs.

Randomly capturing fewer opportunities reduces dollars per quote, not necessarily cents per fill. Actual capture is not random: queue competition can remove good fills and leave adverse ones. Measure net profit both per submitted opportunity and per filled contract, with missed fills, queue position and quote age.

Four contracts at 60¢ reserve $2.64 including the existing 10% buffer. At that price a $50 lifetime submission allowance permits roughly 18 submissions, or 72 contracts if every order fills. Multiplying 72 by the illustrative 3.40¢ yields about **$2.45**, before operating costs and without a guarantee. Unfilled/canceled submissions reduce the experiment further. This is an operational pilot, not yet a scalable income stream. Illustratively, $20 of fixed costs requires about 588 filled contracts at 3.40¢ just to break even; $20 is not a claim about your actual bill.

## Repairs made for opening week

| Finding | Repair |
|---|---|
| Counts could exceed caps after reserve | Shrink quantity until existing caps fit |
| Fee dollars labeled as cents in NBA settlements | Explicit normalization and append-only corrections |
| GitHub projections never automatically reached the server | Sync checked data from one pinned commit; no automatic code update |
| Empty off-days retained old files and broke concatenated dtypes | Explicit empty snapshots; UTC/numeric/boolean schedule types |
| Historical identity and teams could survive transfers | Reject ambiguous names; verify current roster/game; require two fresh books after long gaps/team changes |
| Invalid injury payload could look healthy | Validate structure, IDs and timestamps; stop on ambiguity |
| Stale/future books and ambiguous same-day matches | Reject bad timestamps/keys, retain source timestamps, check game time and intervening injury news |
| Research fee assumption could differ from live charges | Read series/event metadata and bound fees before submission |
| Resting orders could remain for hours | At most one hour; expire before the final two hours |
| NFL isolation could block NBA emergency cancellation | Handle owned KILL cancellations first |
| Separate workers could race on one account | Shared process lock plus existing isolation/ownership checks |
| Missing portfolio lists became empty; cursor loops could hang | Reject malformed pages and repeated cursors |
| Fixed-point balances were ignored | Prefer dollar balance, reject missing values |
| Non-trading cycles lacked explanation | Persist exclusions, candidate counts, skip reasons and decision |
| Insufficient actual-fill diagnostics | Repeated queue readings and observed markouts with explicit missing windows |

Version: `nba-no-v2-opening-audit`. These safeguards and expiry alter the experiment and must be tracked separately. Reserve is not an actual 10% trading fee. Current series metadata on October 18 showed `quadratic`, multiplier 1 for all four NBA props; this currently implies no maker trading fee at the series level. Event overrides are still checked at submission; the conservative charged-fee scenario above remains useful as stress analysis.

This remains a **five-minute polling worker**. It cannot cancel instantly after news and is unsuitable unchanged for latency-sensitive in-play, crypto or announcement trading. Next execution work: sequence-checked market/user-fill streams, reconnect/resnapshot handling, measured cancellation latency, queue depletion, inventory control and pause/heartbeat behavior. Do not replace working order transport with an untested streaming rewrite before Tuesday.

The historical model also uses closing game lines and availability inferred from completed box scores. Those can be more informative than inputs actually available two to six hours before tip. Backtest profitability must therefore be treated as optimistic until contemporaneous features and real execution reproduce it. The new current-roster and injury checks reduce live operational mistakes; they do not retroactively eliminate historical information bias.

## Broad search and multiple comparisons

The saved scan lists **3,047 series**. It reports NO-fill statistics for **2,349**, with **80 nominal passes**. YES and NO alone imply at least **4,698 comparisons**; windows, filters and repeated exploration increase the true search. A selected t≥2 is weak evidence after that search.

Seven selected candidates were re-read at order level and clustered by underlying event. None survived a conservative family-wise adjustment across even that minimum comparison count. This does not prove that every market is efficient. Some series are seasonal, event samples are small, and scans use expected expiration rather than verified event start. Validate contract timing and settlement definitions before accepting unusually large returns.

| Historical NO scan | Fill rows / events | Mean ¢/possible fill | Mean ¢/placed row, including no fills | Assessment |
|---|---:|---:|---:|---|
| NWSL spreads | 145 / 39 | +14.04 | +4.05 | Small event sample; timing/rules audit needed |
| NCAA men's first-half spreads | 223 / 116 | +16.35 | +5.00 | Historical screen; none open in the current census |
| NASCAR winner | 940 / 73 | +4.00 | +2.82 | Correlated driver exposure; needs future races |
| ITF tennis | 1,168 / 554 | +4.62 | +2.24 | Later baseline performance deteriorated |
| LaLiga spreads | 835 / 223 | +4.31 | +1.29 | Worth a separate match-level model |
| Bitcoin threshold sample | 12 / 6 | −8.98 | −3.48 | Tiny; does not test 15-minute crypto |
| CPI | 45 / 8 | −0.83 | −0.29 | Few independent releases; no established edge |

Multiple quotes, thresholds and players may share one outcome. First-possible-fill-per-ticker diagnostics and input hashes are in [results.json](../outputs/launch_audit_20261018/results.json). Deduplicating tickers still does not reproduce queue position or a funding-constrained portfolio.

### Later paper observations, October 16–18

These infer fills from **public production prints**, not demo orders or account executions. Report sized dollar profit and contract-weighted returns; equal-row averages can reverse the conclusion.

| Series/rule | Independent events | Paper P&L | Weighted ¢/contract |
|---|---:|---:|---:|
| ITF baseline | 89 | −$78.63 | −3.61 |
| ITF exploratory NO-price filter | 45 | +$15.20 | +3.02 |
| LaLiga spreads | 8 | +$16.62 | +14.21 |
| Liga MX spreads | 8 | −$31.32 | −11.03 |
| NASCAR winner | 2 | +$1.82 | +0.86 |
| NASCAR top 10 | 1 | −$15.07 | −3.52 |
| UFC method of victory | 13 | −$33.62 | −14.55 |

NASCAR top 10's equal-row average is +4.14¢, yet its sized portfolio lost money. LaLiga's apparent profit still spans only eight matches. The ITF price filter is exploratory; its observations are not automatically independent of prior selection. These results argue against deploying a generic NO strategy across categories.

## Current liquidity and research priorities

The public production census sampled up to 600 open markets in each of 22 named series. [Its snapshot](../outputs/launch_audit_20261018/production_liquidity.json) includes timestamp, pagination coverage, prices, volumes and fee metadata. Volume is **contracts**, not dollars or available executable depth. A median spread is not attainable round-trip profit. Open markets can already be in play or near resolution.

| Area | October 18 production snapshot | Decision |
|---|---|---|
| NBA props | 312 two-sided markets; median spreads about 10.5–20¢ across stats | Primary bounded trial; exact fresh book coverage first |
| NBA / NHL winners | 74 / 92 two-sided; 6¢ / 4¢ median spreads | Need separate fair values; NHL historical NO mean +1.02¢ has t≈0.50 |
| MLB winners | Two open markets; about 4.84m 24h contracts; 1.5¢ spread | Liquidity exists, but historical generic NO mean −7.85¢, t≈−2.98 |
| LaLiga / NWSL spreads | 39 / 7 two-sided; 3¢ / 25¢ spreads | Research contemporaneous handicap/score distributions |
| ITF tennis | 112 two-sided; 30.5¢ median spread | Later losses, injury/retirement rules and sparse depth matter |
| NASCAR | 37 open contracts, only six two-sided | Aggregate race volume is not necessarily accessible pre-race liquidity |
| Chicago / LA daily highs | 8 / 4 two-sided; about 1¢ spread | Promising research domain; needs calibrated station distributions |
| BTC / ETH 15-minute | One interval each; about 162k / 11k contracts; 1¢ spread | Requires a different streaming/reference-index execution design |
| CPI / Fed / payrolls | Quotes available; very different spreads; few independent releases | Need vintage-correct, release-specific models |

**Weather:** use a distribution for the exact settlement station and day, calibrated by forecast horizon and season. A point forecast is not a probability. NOAA provides probabilistic temperatures, while its climate-day convention and quality-controlled daily summaries can differ from naive hourly maxima. Archive forecasts as issued and compare with the exact settlement source; cluster nearby stations by date. A one-cent spread leaves little room for forecast error and fees. Zero weather fills in the old generic scanner are a coverage limitation, not proof of no opportunity. Sources: [NWS probabilities](https://www.weather.gov/mfl/Probabilistic), [observations versus climate summaries](https://www.weather.gov/lot/weather_observations_faq).

**Macro:** forecast the precise release statistic, including first-release versus revision rules. CME publishes expectations, but copying a consensus is not independent edge. Evaluate separate release dates and prevent post-release data leaking into historical quotes. A five-minute poller should not compete on announcement latency. Source: [CME release calendar](https://www.cmegroup.com/education/events/economic-releases-calendar).

**Polymarket US:** the existing strict prop watcher found zero qualifying NBA/NFL matches in its scanned catalog and produced no executable opportunities. This does not describe every market or venue. US documentation exposes BBO, depth and reference data. A material change takes effect **October 19 at 1 p.m. Eastern**: the lowest maker-volume tier, below $10m prior-month volume, gets no maker rebate. Assume no rebate for this pilot on Tuesday. A midpoint gap is not arbitrage: compare opposing executable asks, depth, fees, identical settlement and the risk that just one leg fills. Sources: [data guide](https://docs.polymarket.us/data-guide/overview), [fee schedule](https://docs.polymarket.us/fees).

**Ladders and incentives:** screen logically nested lines for crossed prices, but verify exact player/game/stat and participation rules, fees, sufficient depth and both-leg execution. A displayed crossing alone is not risk-free. Kalshi's component-liquidity incentive has eligibility and scoring conditions; credits are distributed monthly and live-event eligibility depends on timing. Exclude unearned incentives from base edge. Source: [program terms overview](https://help.kalshi.com/en/articles/17184676-sports-prop-combo-market-component-legs-liquidity-incentive-program).

Politics, entertainment and long-horizon contracts are lower priority here. The repository has no independently validated model for them; capital lockup and settlement interpretation add distinct problems. Adding categories without fair values would increase breadth without demonstrated edge.

## What must be proven next

1. **Operation:** signed production reads reconcile, ownership is known, inputs are fresh, fees understood and estimated net edge positive. A GitHub source check does not prove the Droplet is deployed or armed.
2. **Execution:** accepted order IDs, actual exchange fill IDs, partial quantities, maker status, queue history and cancellations. Keep attempted/accepted/filled/settled counts separate. Public prints are not your fills.
3. **Economics:** actual net settlement profit, weighted and per-opportunity returns, independent-game uncertainty, drawdown, markouts and concentration. Include subscriptions/server costs and realistic capture.
4. **Cohorts:** separate NBA from NFL and retain version labels. Keep the existing 30-day/500-settled-fill protocol and coverage gates, but acknowledge the small lifetime allowance is unlikely to reach it. Fragmented fills from one event are not independent evidence.
5. **Expansion:** freeze rules before new chronological holdouts. Research LaLiga/NWSL pricing and calibrated weather next. Crypto, macro and cross-venue trading need their own execution design, not a copy of this worker.

## Reproduction and primary sources

- `python -m research.nba_launch_audit` recomputes the game/event-clustered historical audit. Output includes every input's SHA-256. Historical input snapshot: `8a3b7dd27d77848200dea99f18ca58715c27a866`; paper dates are shown above. Later input changes may legitimately change results.
- `python -m research.nba_source_smoke` reads real schedule/roster/injury/market/fee sources and screens nested ladders. No authentication or orders.
- `python -m research.market_opportunity_audit` refreshes bounded production liquidity, without inferring edge or trading.
- Owner-side `python -m live.prod_nba_auto --preflight --sync-inputs` performs signed GET-only readiness checks. No journal reset or exchange write.
- PR CI runs the full producer against freshly downloaded box scores and real open markets, plus offline regression tests. No demo-fill gate is required.

Technical documentation checked October 18: [V2 orders](https://docs.kalshi.com/api-reference/orders/create-order-v2), [balance units](https://docs.kalshi.com/api-reference/portfolio/get-balance), [settlement units](https://docs.kalshi.com/api-reference/portfolio/get-settlements), [series fees](https://docs.kalshi.com/api-reference/market/get-series), [event overrides](https://docs.kalshi.com/api-reference/events/get-event), [rounding](https://docs.kalshi.com/getting_started/fee_rounding), [fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf), [queues](https://docs.kalshi.com/api-reference/orders/get-order-queue-position). Runtime checks remain necessary as schedules, markets and fees change.
