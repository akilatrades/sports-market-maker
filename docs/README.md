# Documentation

The project's documents, grouped by what you are looking for. Dated
documents (with a date in the name) are snapshots of what was known on that
day and are kept unchanged as part of the record.

## Pick your path

| You are | Read, in this order |
|---|---|
| **Hiring or just curious** (5 minutes) | The [README](../README.md), the [case study](PROJECT_BRIEF.md), then the [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/) |
| **A quant** (30 minutes) | The [design decisions](DESIGN_DECISIONS.md), then these research-log entries: [where the edge comes from](../RESEARCH_LOG.md#2026-10-15-where-the-resting-order-profit-comes-from-decomposition-in-sample), [the strategy sweep](../RESEARCH_LOG.md#2026-10-22-strategy-sweep-across-all-scanned-markets-with-profit-factor-results) and its hedging addendum, [the spread pilot plan](../RESEARCH_LOG.md#2026-10-22-spread-maker-pilot-shadow-and-small-live-plan), [what the first live night changed](../RESEARCH_LOG.md#2026-10-23-spread-maker-v2-pregame-only-plan-amendment); then the [forward-validation rules](FORWARD_VALIDATION.md) and the [NBA model](nba-model.md) |
| **An engineer** (30 minutes) | The [operations guide](../deploy/README.md), the [spread maker pilot notes](../deploy/PROD_SPREAD_AUTO.md), [`live/shared_account_risk.py`](../live/shared_account_risk.py), the [project map](PROJECT_MAP_AND_PRODUCTION_AUDIT_2026-10-18.md) and [security](../SECURITY.md) |
| **Joining the project** | [Start here](START_HERE.md), [notes for AI assistants](../CLAUDE.md), [contributing](../CONTRIBUTING.md) |

## Core documents

| Document | What it covers |
|---|---|
| [README](../README.md) | What the project does, results by tier, how it works, limitations |
| [Case study](PROJECT_BRIEF.md) | One page: the question, both strategies, evidence by tier, what is measured now, what is unproven, what is next |
| [Design decisions](DESIGN_DECISIONS.md) | Eight choices that shape what the numbers mean, each with evidence and the alternative |
| [Current project state](CURRENT_PROJECT_STATE.md) | What is live, what the evidence shows so far, what is still unknown |
| [Research log](../RESEARCH_LOG.md) | Every hypothesis, written down before it was tested, with its result |
| [Forward-validation rules](FORWARD_VALIDATION.md) | How live results are judged |
| [Start here](START_HERE.md) | For collaborators: the project in a minute, how a night works, current limits, first projects |
| [Audit matrix](DEEP_AUDIT_MATRIX.md) | Checks across model, trading, data, risk and security |

## Models

| Document | What it covers |
|---|---|
| [NBA prop model](nba-model.md) | Features, outcome distributions, walk-forward validation, market tests |
| [NFL prop model](nfl-model.md) | The NFL counterpart and its results |
| [Figures](figures/) | Charts used in the README and research log |

## Research and audits

| Document | What it covers |
|---|---|
| [NBA statistical audit, Oct 18](NBA_AND_MARKET_AUDIT_2026-10-18.md) | Historical results recomputed with game-clustered intervals and a multiple-comparison check |
| [Model and execution audit, Oct 20](NBA_MODEL_EXECUTION_AUDIT_2026-10-20.md) | Review of the projection math and order handling |
| [Minutes and execution research, Oct 20](NBA_OCT20_MINUTES_AND_EXECUTION_RESEARCH.md) | Late-news context and order-timing research |
| [Opening-night sizing review, Oct 19](NBA_OPENING_NIGHT_SIZING_RESEARCH_2026-10-19.md) | How pilot budgets and caps affect historical results |
| [La Liga margin audit, Oct 17](LALIGA_MARGIN_EDGE_AUDIT_2026-10-17.md) | Why a small positive paper result is not yet evidence |
| [Cross-exchange prop watch](CROSS_EXCHANGE_PROP_WATCH.md) | Kalshi versus Polymarket US player-prop coverage |
| [Polymarket US quote replay](POLYMARKET_US_QUOTE_REPLAY.md) | What archived quotes can and cannot show |

## Live trading

| Document | What it covers |
|---|---|
| [Operations guide](../deploy/README.md) | What runs where, releasing code, going live, stopping, monitoring |
| [Go live / Stop button](../deploy/GO_LIVE_BUTTON.md) | Owner-only GitHub button to switch the bots on or off |
| [NBA production worker](../deploy/PROD_NBA_AUTO.md) | NBA order rules and current limits |
| [NFL production worker](../deploy/PROD_NFL_AUTO.md) | NFL order rules and limits |
| [Spread maker pilot](../deploy/PROD_SPREAD_AUTO.md) | Spread maker rules (v2, pregame only), limits, switching it on and off |
| [Live P&L feed](../deploy/LIVE_ACCOUNT_PNL.md) · [Private fills export](../deploy/PRIVATE_FILL_EXPORT.md) | How verified live results reach the dashboard and the owner's private data |
| [NBA 30-day live validation](NBA_30DAY_LIVE_VALIDATION.md) | Daily checks, stop rules and the live review |
| [NBA live evidence, Oct 21](NBA_OVERNIGHT_AUDIT_2026-10-21.md) | First verified NBA fill and what it does and does not show |
| [Production execution audit, Oct 20](PRODUCTION_EXECUTION_AUDIT_2026-10-20.md) | Order lifecycle checks before the NBA launch |
| [Project map and production audit, Oct 18](PROJECT_MAP_AND_PRODUCTION_AUDIT_2026-10-18.md) | Architecture walkthrough and live-fill reconciliation |
| [Account security checklist](LIVE_ACCOUNT_SECURITY_CHECKLIST.md) | Key handling and account safety |
| [GitHub access and secrets](../deploy/GITHUB_ACCESS.md) | What is public, who can run what, adding a collaborator safely |
| [Contributing](../CONTRIBUTING.md) · [Security](../SECURITY.md) | How changes get in; how the account and server are protected |

## Records

Earlier working notes, kept unchanged as the project's record. Read them for
history, not for how things work now.

| Document | What it covers |
|---|---|
| [Project state notes, to Oct 19](PROJECT_STATE_NOTES_2026-10-19.md) | Running status notes from the build-up to launch |
| [NBA v3 long-resting proposal, Oct 20](NBA_LONG_RESTING_V3_2026-10-20.md) | Superseded by the current NBA rules |
| [Execution improvements v2](EXECUTION_IMPROVEMENTS_V2_2026-10.md) | Earlier execution research |
| [NBA go/no-go, Oct 20](TUESDAY_NBA_GO_NO_GO_2026-10-20.md) | Launch conditions for the first NBA night |
| [Execution readiness, Oct 17](EXECUTION_READINESS_2026-10-17.md) | Checklist before the first real-money order |
| [NFL roster guard, Oct 18](NFL_ROSTER_GUARD_2026-10-18.md) | Roster safeguards added after the first live week |
| [Kalshi demo rollout](KALSHI_DEMO_V2_ROLLOUT.md) | Order and cancel checks in Kalshi's demo environment |
| [Early README](ARCHIVED_EARLY_README_2026-10-17.md) | The first README; its bankroll examples are superseded |
