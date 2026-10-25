# Account reconciliation: private capture before journal repair

Manual cash-outs can appear as unowned fills on markets owned by a bot. A financial CSV reconciliation explains their economics, but hashed exports cannot supply the original exchange IDs needed by production ownership checks.

`tools/account_reconciliation_snapshot.py` adds two deliberately limited operations:

- `capture` uses the existing signed client with a hard GET allowlist to read fully paginated positions, resting orders, fills and settlements. It reads journals before and after, and compares position/order boundary reads. Changing inputs, partial pagination and repeated cursors fail the capture. The capture is a bounded interval, not an atomic exchange transaction.
- `plan` reads a capture no more than five minutes old and identifies fills whose order IDs are absent from accepted bot ownership. Identical duplicates are removed; conflicting copies are rejected. Candidates are review items, never automatically treated as legitimate manual cash-outs.

Both write a new mode-0600 file without overwriting an existing path. Full IDs and financial records stay in that private file. Only a fixed status, error class and zero-action claims reach stdout. No credentials are loaded from files or included in results. The capture uses credentials already supplied by an authorized server runner; this change does not install that runner or grant access to root-owned settings.

Private server usage, after the reviewed tool is available in a trusted checkout and a signed-read environment is supplied by the operator:

```bash
python -m tools.account_reconciliation_snapshot capture --out /private/new-account-snapshot.json
python -m tools.account_reconciliation_snapshot plan --snapshot /private/new-account-snapshot.json --out /private/new-review-plan.json
```

Do not run these commands in public CI with account credentials. Do not print or upload their output files to a public artifact or repository. No automated private transfer is installed by this change.

## Remaining repair gates

1. Obtain a fresh signed capture on the server without exposing credentials or raw identifiers in public job logs.
2. Match every proposed manual fill against the owner's activity evidence: timestamp, side, quantity, prices, fees and exact exchange identities. A fill on a bot-owned ticker alone is insufficient evidence.
3. Replay owned entries and approved manual closes, including YES/NO netting and precise fees. Match authenticated settlement revenue and current positions. Explain all resting orders across all cohorts.
4. Design and test an explicit external-close journal event. Do not forge a bot intent/acceptance for a manual order, remove unrecognized fills, or relax the ownership guard.
5. Revalidate fresh state under the shared lock before any append. Preserve journal backups and make reconciliation idempotent and auditable. Apply only the independently verified records.
6. Run account-wide reconciliation while trading remains unarmed. A separate decision governs funded restart.

The new tool always reports `safe_to_resume: false`; it does not claim position reconciliation or economic replay has passed. The existing production ownership behavior is unchanged. Current bots may still be failing that guard. Neither a passing unit test nor this diagnostic PR means they have resumed.

Validation: eight targeted offline tests cover review-only behavior, stale/partial data, conflicting/duplicate fills, unowned orders, private non-overwriting output, cursor failures and changing account reads. No account call is made by these tests.
