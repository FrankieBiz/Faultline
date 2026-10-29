# FaultLine judge walkthrough: findings and repair checklist

Audit performed October 28, 2026 against this checkout, using headless Chromium and independent code reviews. The goal is a clear, credible judge journey from a seeded checkout failure to a verified, isolated candidate.

## Fix before judging

- [x] **Launch URL rejects actions.** On the documented alternate Inspector port, `http://127.0.0.1:4101` displayed readiness but a live repair POST returned 403, `Same-origin request required`. The same action at `http://localhost:4101` was accepted. Preserve cross-site protection while making the launcher URL work, and display actionable proxy errors instead of a generic HTTP status. Verify both hostnames and rejection of cross-site requests.
- [x] **Coupon preview differs from the order.** Apply `TENOFF` to one Trail Mug, edit the field to `FIFTEEN` without applying, then place the order: the preview remains $18.00 but the order is submitted at $17.00. Keep preview and submitted coupon consistent.
- [x] **Make the judge journey discoverable.** Link the Inspector to the storefront and guide the judge through reproducing the checkout failure, running repair, and inspecting evidence. Explain prominently that the candidate is verified in isolation, the store remains seeded, and no production deployment occurs.
- [x] **Make results scannable.** Lead with the failure, candidate, verification coverage, and a clear evidence action. Collapse long assertion, artifact, and event details where appropriate. Replace the successful terminal-state wording `Event stream closed` with language that does not look like a failure.
- [x] **De-emphasize authored previews.** Their scripted scenarios and fix are correctly labeled but expanded alongside real results. Collapse or separate them so judges understand which evidence came from the live run.
- [x] **Reconcile Meta claims with evidence.** The README says no live Meta trial has been recorded, while `docs/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/job.json` records a verified `muse-spark-1.3` attempt. Verify provenance before updating claims; a recorded controller trial and a broader Meta evaluation are different things. Check replay archives before any publication and do not claim their contents are sensitive without evidence.
- [x] **Remove unfinished submission text.** `docs/DEVPOST_SUBMISSION.md` contains an instruction to add the builder's firsthand account. Replace or remove the instruction without inventing user research, personal experience, or impact.
- [x] **Make earlier evidence discoverable.** The Inspector requests only the latest job; a later run hides a prior Meta result. Provide a simple history or selection affordance, with clear provider and outcome labels.

## Verification and remaining uncertainty

- Before changes, `make check` passed after setup: 239 backend tests, 316 orchestrator tests, and 32 runner unit tests; four isolation-related tests were skipped. `make browser` passed nine mocked Inspector browser tests.
- A live deterministic run reproduced HTTP 500, passed 44 candidate assertions, and reported successful cleanup in 5.4 seconds. All 14 displayed artifact URLs returned HTTP 200. The three authored preview controls worked at mobile width without horizontal overflow.
- Follow-up exposed a separate cancellation cleanup failure: an owned systemd scope remained active after its processes exited. After the scope-stop fix, reset cleared the earlier quarantine, two live cancellations completed, and a subsequent live repair passed 44 assertions. The cause of the earlier stack exit itself remains unconfirmed.
- No live Meta call was made during this audit. Avoid presenting deterministic output as Meta inference.
- The retained Meta replay's checksums and evidence bundle match, but two preserved trace archives contain workstation source paths; review them before further sharing. See `docs/evidence/2026-10-28-meta-replay-review.md`.
