# FaultLine technical dossier

This dossier describes the implemented controlled checkout-repair prototype. [Submission copy](DEVPOST_SUBMISSION.md), [video plan](VIDEO_STORYBOARD.md), and [review evidence](QUALITY_REVIEW.md) are maintained separately.

## Defined behavior

The registered scenario is `scripted_checkout_repair`. Two Trail Mugs cost 3998 cents. Missing, null, empty, or whitespace-only coupon input should mean no discount. The seeded implementation instead subtracts `None` and returns HTTP 500. `TENOFF` and `FIFTEEN` must retain integer-cent pricing; unknown coupons must return 400 without creating an order.

The repair target is `apps/buggyshop-backend/app/routes/checkout.py`. Tests, schemas, catalog, order storage, oracle, and reference solutions are outside the allowed edit boundary.

## Workflow and trust boundaries

1. The controller authenticates requests, validates strict contracts, reserves a durable singleton lease, and records idempotent admission.
2. Snapshot preparation verifies the fixture manifest and exports application source from the pinned seed commit.
3. A trusted browser runner reproduces the failing customer journey and captures real screenshots, request logs, and a Playwright trace.
4. The model receives bounded source and failure evidence marked untrusted. A configured provider failure is reported rather than converted to a deterministic success.
5. The patch policy enforces exact paths, source identity, hunk coordinates, 16 KiB diff, 32 KiB source, at most 100 changed lines, syntax, and restricted imports/capabilities.
6. A fresh candidate runs under the isolated runtime. The browser and independent HTTP assertions evaluate it from outside its execution boundary.
7. The worker checks execution identities, exit/verdict consistency, named assertions, evidence roles and hashes, then cleanup. Cleanup failure quarantines admission.

Candidate backends run in a transient systemd user scope with aggregate cgroup v2 limits (512 MiB, no swap, 64 tasks, one CPU, whole-scope OOM kill). The controller reads the limits back from kernel files at every launch, and an OOM/task-limit probe must pass before readiness. A first attempt rejected by any gate returns bounded findings to the model for one more attempt.

Git worktrees manage source isolation. AST policy limits admitted syntax and capabilities. Neither substitutes for process containment. A passing finite suite cannot establish correctness for every possible input.

## Timing and retries

The controller uses monotonic budgets: baseline/preparation 20 seconds, generation 45 seconds, each attempt 75 seconds, verification 20 seconds, work cutoff 170 seconds, overall 180 seconds, and a final 10-second cleanup reserve. At most two attempts are permitted, with adequate remaining budget required for the second. These are limits, not measured latency or an SLA.

## Evidence and failure handling

Reports contain actual observed verdicts and assertions. Artifacts are hashed, bounded, registered, and served as private inert downloads. SSE events support replay cursors. Cancellation and controller restart have distinct terminal states. A job only earns `outcome=verified` when verification and cleanup both succeed.

The deterministic provider is an explicitly identified local workflow check. Hosted Meta evidence must include the recorded provider/model, actual generation usage if supplied, baseline, candidate verification, and cleanup. Unknown token counts remain unknown. The retained Meta controller repairs meet that standard; see their [provenance review](evidence/2026-10-28-meta-replay-review.md). Each bundle digest is a checksum, not a signature.

## Scope

One seeded repair case is implemented in the live demo. A hash-pinned evaluation corpus adds nine unfamiliar defects and eleven candidate patches for the same route ([evaluation](EVALUATION.md)). The Inspector live-checks HTTP rules from `faultline.toml` and any URL entered in it, in two fresh sessions; only a failure matching the registered scenario's route, error, and source can be repaired. Continuous monitoring, external incident ingestion, production traffic switching, pull-request integration, compliance certification, customer impact measurements, and general repair reliability are not claimed.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for the current verification state and [QUALITY_REVIEW.md](QUALITY_REVIEW.md) for concrete findings and remaining competition risks.
