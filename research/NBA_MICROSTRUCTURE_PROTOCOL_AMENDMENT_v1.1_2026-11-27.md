# NBA Microstructure Protocol, amendment v1.1

**Written:** 2026-11-27 UTC, before the cohort starts (2026-11-28 00:00 UTC)
and before any cohort data exists.
**Amends:** `NBA_MICROSTRUCTURE_PROSPECTIVE_PROTOCOL_2026-11.md`
(`nba-microstructure-prospective-v1`). Everything not named here is unchanged:
hypotheses, features, targets, sampling, bootstrap, Holm adjustment,
coverage gates and decision rules.
**Protocol ID:** `nba-microstructure-prospective-v1.1`

## Why amend

1. **Coverage.** GitHub's timed starts fire rarely in this repository (the
   paper tests' schedules have run hours apart, and the 15-minute collector
   had not run once 30 minutes after it was merged). A 30-day cohort from
   12-minute runs at random times would likely fail the coverage gate.
2. **Retention.** Workflow artifacts expire after 14 days; the cohort is 30.
3. **Scope.** "Top 5 markets per series by volume" picks the busiest books.
   The open research questions (queue position, the cost of resting orders,
   the ladder "first hour" effect) are about thinner books in the last hours
   before tip-off.

## Changes

**Collection (replaces "Scheduled collection cadence" and "Scope cap"):**
- Runs continuously on the project's always-on research server
  (`pm-recorder`, the crypto recorder's server), as the `nba-collector`
  service, from a read-only copy of this public repository. Public endpoints
  only; no keys; no order endpoint.
- Every market in the four series from **7 hours before tip-off to 3 hours
  after** (tip-off = occurrence time minus 3 hours), nearest tip-off first,
  at most 400 per series.
- One cycle a minute (books every cycle, public trades every cycle), at most
  10 requests a second, up to 8 in parallel. When a cycle takes longer than
  a minute, the next starts at once; the observed gap is recorded per row.
- One JSONL file per UTC day. Each finished day is gzipped and pushed to the
  `recordings` branch of the recorder's repository (folder `nba/`) by the
  server's daily publish job. That copy is the durable record and the
  analysis input; the GitHub-artifact collector stays as a backup only.

**Analysis scope:** the primary analysis uses pre-game observations only
(7 to 0 hours before tip-off), as v1 implied. In-game rows (0 to 3 hours
after tip-off) are collected for later, separately pre-registered work and
are **not** part of this protocol's primary or secondary tests.

**Provenance:** the collector commit is the one the server checked out; the
setup script prints it, and the daily upload records it in the commit
message.

## What does not change

Hypotheses 1-4, the 5-minute primary and 15-minute secondary targets, one
observation per market per 5-minute bin, event-clustered bootstrap with
2,000 resamples, Holm adjustment over the two primary features, all four
coverage gates, the "candidate association" definition and every decision
rule.
