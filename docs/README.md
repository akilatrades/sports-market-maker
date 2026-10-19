# Documentation

A guide to the project's documents, grouped by what a reader is looking for.
Dated documents are snapshots: they record what was known on that date and
are kept unchanged as part of the record.

## Start here

| Document | What it covers |
|---|---|
| [Project README](../README.md) | Summary, results, architecture and limitations |
| [Research log](../RESEARCH_LOG.md) | Every hypothesis, written before it was tested, with its result |
| [NBA and cross-market audit](NBA_AND_MARKET_AUDIT_2026-10-18.md) | Recomputed historical evidence with game-clustered intervals, multiple-comparison check, market census |
| [Forward-validation protocol](FORWARD_VALIDATION.md) | Pre-registered rules for judging live results: 30 days and 500 settled fills |

## Models and research

| Document | What it covers |
|---|---|
| [NBA prop model](nba-model.md) | Features, distributions, walk-forward validation and market tests |
| [NFL prop model](nfl-model.md) | The NFL counterpart and its results |
| [NBA opening-night sizing review](NBA_OPENING_NIGHT_SIZING_RESEARCH_2026-10-19.md) | Historical sensitivity of pilot budgets and caps |
| [La Liga margin audit](LALIGA_MARGIN_EDGE_AUDIT_2026-10-17.md) | Why a small positive paper result is not yet evidence |
| [Cross-exchange prop watch](CROSS_EXCHANGE_PROP_WATCH.md) | Kalshi versus Polymarket US prop coverage |
| [Polymarket US quote replay](POLYMARKET_US_QUOTE_REPLAY.md) | What archived quotes can and cannot show |
| [Figures](figures/) | Charts used in the README and research log |

## Production engineering and audits

| Document | What it covers |
|---|---|
| [Project map and production audit](PROJECT_MAP_AND_PRODUCTION_AUDIT_2026-10-18.md) | Architecture walkthrough, live-fill reconciliation, open risks |
| [NFL roster guard](NFL_ROSTER_GUARD_2026-10-18.md) | Roster and identity safeguards added after the first live week |
| [Execution readiness, October 17](EXECUTION_READINESS_2026-10-17.md) | Evidence checklist before any real-money order |
| [Kalshi V2 demo rollout](KALSHI_DEMO_V2_ROLLOUT.md) | Demo-environment order and cancel verification |

## Operations (owner-run procedures)

| Document | What it covers |
|---|---|
| [Server deployment](../deploy/README.md) | Always-on trader setup |
| [NBA production worker](../deploy/PROD_NBA_AUTO.md) | Bounded NBA pilot: preflight, activation and handoff |
| [NFL production worker](../deploy/PROD_NFL_AUTO.md) | Bounded NFL pilot |
| [Supervised NFL pilot](../deploy/PROD_NFL_PILOT.md) | The first single-order production test |
| [NBA go/no-go, October 20](TUESDAY_NBA_GO_NO_GO_2026-10-20.md) | Launch conditions for the first NBA night |
| [Account dashboard](../deploy/ACCOUNT_DASHBOARD.md) | Private read-only account view and public P&L snapshots |
| [Public NFL/NBA P&L refresh](../deploy/PUBLIC_PNL_REFRESH.md) | Signed settlement reconciliation, staleness handling and opt-in automatic sanitized publishing |
| [Near-live funded account P&L](../deploy/LIVE_ACCOUNT_PNL.md) | HTTPS-proxied GET-only 30-second account settlement feed for GitHub Pages |
| [NFL worker memory repair](../deploy/NFL_WORKER_MEMORY.md) | Incident note |

## Working notes and archive

| Document | What it covers |
|---|---|
| [Current project state](CURRENT_PROJECT_STATE.md) | Running status notes, updated as evidence arrives |
| [Early README (archived)](ARCHIVED_EARLY_README_2026-10-17.md) | The project's first README, kept for the record; its bankroll examples are superseded |
