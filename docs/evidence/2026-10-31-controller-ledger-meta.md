# FaultLine trial ledger

Generated 2026-10-31T13:28:18Z by `scripts/trial_ledger.py` from controller job records. Full ledger: `2026-10-31-controller-ledger-meta.json` (schema 1.0).

Status: complete.

Classification: `meta_model_trials`. All 3 provider responses came from provider meta. These are live Meta model trials on one controlled scenario.

Readiness at start: status `ready`, provider `meta`, model `muse-spark-1.3`, probe time 2026-10-31T00:54:27.389010+00:00.

| Trial | Job | Outcome | Verified | Attempts | Wall s | Assertions | Tokens (prompt+completion) | Cleanup |
| ---: | --- | --- | --- | ---: | ---: | --- | --- | --- |
| 1 | 165e0b18 | verified | yes | 1 | 10.5 | 44/44 | 1580+1303 | succeeded |
| 2 | 196cc3b6 | verified | yes | 1 | 12.6 | 44/44 | 1580+1856 | succeeded |
| 3 | 5fb3c393 | verified | yes | 1 | 10.4 | 44/44 | 1573+1825 | succeeded |

## Summary

| Measure | Value |
| --- | --- |
| Trials run | 3 of 3 requested |
| Verified | 3 (100%) |
| Verified on attempt 1 / attempt 2 | 3 / 0 |
| Outcomes | verified 3 |
| Expected failure reproduced | 3 |
| Cleanup confirmed | 3 |
| Deadline exceeded | 0 |
| Attempts (policy rejected) | 3 (0) |
| Wall s median / p95 / min / max | 10.5 / 12.6 / 10.4 / 12.6 (3 known) |
| Prompt tokens | 4733 (3 of 3 attempts recorded) |
| Completion tokens | 4984 (3 of 3 attempts recorded) |
| Provider / model | `meta` / `muse-spark-1.3` |

Scope: one registered scenario (`scripted_checkout_repair`); results do not measure other defects. Wall time is the controller-recorded interval from job creation to its final update. p95 uses the nearest-rank method. Token totals appear only when every attempt recorded usage.
