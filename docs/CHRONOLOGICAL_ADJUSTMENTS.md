# Chronological adjustments

Updated October 28, 2026. This is a dated record of what changed after the [score assessment](HACKATHON_SCORE_ASSESSMENT.md) and what each change actually does. Claims here are limited to what the repository and recorded evidence show.

The only score on record is the October 27 provisional assessment of commit `925507a`: **55/100**. No reassessment has been performed. An earlier revision of this file reported 70/100 and 93/100. Those figures were self-assigned, and the 70 was attributed to a commit whose author had declined to score it. They have been removed.

## October 27: baseline

- `925507a` replaced simulated repair paths with isolated browser verification.
- `9a14c63` documented the 55/100 assessment and the evidence that would justify reassessment.

## October 28, morning: assessment remediation (`c1b5466`)

- **Repair loop.** A rejected first attempt sends bounded gate findings to the second. The prompt states the checkout contract rather than the defect. Miscounted hunk headers are recounted without altering content. Proposal errors have specific codes. Provider identity comes from the endpoint host and is recorded only from actual responses.
- **Oracle.** Candidate crashes, hangs, and oversized responses are failed checks, not infrastructure errors.
- **Containment.** Aggregate cgroup v2 limits are verified from kernel files at every launch and proven by an OOM/task-limit probe before readiness. Other fixes: an explicit user namespace, an emptied `/proc/1/environ`, JSON-only backend logs, and full-length scope prefixes.
- **Evaluation.** A hash-pinned corpus of ten defects and eleven candidate patches, an isolated evaluation harness, a trial ledger, and a static checksummed replay export.
- **Verification at the time.** 220 backend/script, 301 orchestrator, and 32 runner tests; 13 real isolation tests; 9 browser tests.

## October 28, midday: further additions from a parallel session

- **`f4655ac`** added a ddmin payload minimizer, an AST analyzer, and a proof bundle compiler, wired into repair jobs.
- **`4165471`** added the offline bundle verifier `tools/verify_bundle.py` and Inspector badges.
- **`80a29f2`** added 18 schema contract tests, `scripts/demo-chaos.sh`, a probe prompt clarification, an `.env` loader in `scripts/evaluate.sh` that no longer overrides explicit environment variables, and new impact content.
- **`a168307`** added the first version of this file.

## October 28, afternoon: audit and correction

An audit compared those additions against the code and recorded evidence. The schema contract tests, the probe prompt, and the `.env` handling are sound and were kept. The remaining problems were corrected:

| Finding | Correction |
| --- | --- |
| The minimizer in repair jobs never replayed anything against the backend. Its oracle was a hardcoded predicate, and because real observations carry no request body, it always started from a hardcoded payload containing `"session_id": "simulated-trace-header-12345"`. The result was saved as evidence, shown as "ddmin 1-minimal", and sent to the model. | Removed from repair jobs, the prompt, and the Inspector. The generic ddmin library remains, documented as not wired into jobs. |
| The AST analyzer had no `try`/`except` handling, despite claims that it rejected catch-all handlers. Its "defect guarded" flag recognized only the known coupon fix and was displayed but never enforced. | Analyzer removed. The patch policy now enforces a real rule: bare `except`, `except Exception`, and `except BaseException` are rejected before execution, with tests. |
| The evidence store does not accept the bundle's roles. Every save failed and was swallowed by `except Exception: pass`, so no real job ever produced a bundle. | Bundle roles registered with size budgets. Compilation faults are logged, and evidence write failures surface like any other artifact error. A test verifies a real job's bundle against its stored artifacts. |
| The bundle was described as cryptographic and tamper-evident. Its digest covered only the artifact count, the verifier skipped missing artifacts, and it printed "CRYPTOGRAPHICALLY AUTHENTIC". The summary hardcoded "Verified Green", "Zero Regressions", and "Cryptographically Signed". | The digest now covers every recorded field and every artifact's id, role, size, and hash. The verifier locates artifacts by id, fails on missing or mismatched files, and states that the digest is a checksum, not a signature. The summary reports recorded values only. |
| `scripts/demo-chaos.sh` printed unconditional successes ("Playwright journey PASSED", "27 of 27 checks passed", "cgroup v2 limits verified") without running them, then built and "verified" a fabricated bundle. | Rebuilt to print only measurements from that run: the enforcement probe, the isolated evaluation of the registered defect and selected patches, and the session limits. |
| The impact document added a firsthand incident, four interviews, and a 34.3x time trial. The interviews are dated October 24–27 but praise the minimizer, bundle verifier, and cgroup limits, which did not exist until October 28. The trial describes querying an SQLite database that BuggyShop does not have, and credits Llama 3.2 with a 14.5-second repair. The only recorded Llama 3.2 run attempted one case, timed out, and repaired nothing. | Removed pending the owner's confirmation. If any of it is genuine, it is recoverable from commit `80a29f2` and should be restored with real dates and records. |
| The submission draft repeated these claims, plus local Llama 3.2 support as an achievement. | Rewritten to claims backed by the repository and recorded evidence. |

## Status of the assessment's problems

| Problem | Status | Evidence |
| --- | --- | --- |
| No aggregate resource quota | Resolved | Kernel read-back per launch, enforcement probe, real memory/task hog tests |
| Evaluation limited to one fixture defect | Resolved for one route | [EVALUATION.md](EVALUATION.md): authored corpus; gates rejected 6 of 6 wrong repairs |
| Benefit not measured | Partly resolved | Gate value measured on the corpus; no time or user study exists |
| Successful runs were deterministic; no live Meta repair | **Open** | No Meta-hosted run. A non-Meta model (DeepSeek, labeled) verified 18 of 20 holdout runs. The one local Llama 3.2 run failed |
| Firsthand relevance and user validation | **Open** | Needs the owner's account and real conversations ([IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md)) |
| Independent containment review | Partly resolved | Internal AI-assisted adversarial review with fixes; external review outstanding |
| No shareable experience | Partly resolved | Static replay export and reviewed example; not yet published |
| No final video | **Open** | — |
