# FaultLine trial ledger

Generated 2026-10-27T21:23:41Z by `scripts/trial_ledger.py` from controller job records. Full ledger: `2026-10-27-controller-ledger-deterministic.json` (schema 1.0).

Status: complete.

Classification: `deterministic_workflow_rehearsals`. Every recorded attempt reports provider deterministic. These are deterministic workflow rehearsals: the built-in deterministic generator produced every proposal, and no language model was called.

Readiness at start: status `ready`, provider `deterministic`, model `deterministic-checkout-v1`, probe time 2026-10-27T21:23:02.637616+00:00.

| Trial | Job | Outcome | Verified | Attempts | Wall s | Assertions | Tokens (prompt+completion) | Cleanup |
| ---: | --- | --- | --- | ---: | ---: | --- | --- | --- |
| 1 | 19fd54db | verified | yes | 1 | 4.8 | 44/44 | unrecorded | succeeded |
| 2 | 20aa5735 | verified | yes | 1 | 4.8 | 44/44 | unrecorded | succeeded |
| 3 | 09599b17 | verified | yes | 1 | 4.8 | 44/44 | unrecorded | succeeded |
| 4 | e38e347e | verified | yes | 1 | 4.7 | 44/44 | unrecorded | succeeded |
| 5 | 83d1c403 | verified | yes | 1 | 4.9 | 44/44 | unrecorded | succeeded |

## Summary

| Measure | Value |
| --- | --- |
| Trials run | 5 of 5 requested |
| Verified | 5 (100%) |
| Verified on attempt 1 / attempt 2 | 5 / 0 |
| Outcomes | verified 5 |
| Expected failure reproduced | 5 |
| Cleanup confirmed | 5 |
| Deadline exceeded | 0 |
| Attempts (policy rejected) | 5 (0) |
| Wall s median / p95 / min / max | 4.8 / 4.9 / 4.7 / 4.9 (5 known) |
| Prompt tokens | unknown (0 of 5 attempts recorded) |
| Completion tokens | unknown (0 of 5 attempts recorded) |
| Provider / model | `deterministic` / `deterministic-checkout-v1` |

Scope: one registered scenario (`scripted_checkout_repair`); results do not measure other defects. Wall time is the controller-recorded interval from job creation to its final update. p95 uses the nearest-rank method. Token totals appear only when every attempt recorded usage.
