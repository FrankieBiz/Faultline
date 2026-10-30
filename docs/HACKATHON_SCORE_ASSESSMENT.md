# Why FaultLine received 55/100

Assessment date: October 27, 2026. Assessed implementation: commit `925507a`.

This document explains the provisional score from the [quality review](QUALITY_REVIEW.md). It is a skeptical internal assessment, not an official Meta judging result, a prediction of placement, or a new reassessment.

**The central reason for 55/100: FaultLine demonstrated a credible verification engine for one controlled defect, but had not yet demonstrated enough live Meta use, generalization, firsthand impact, or presentation quality to support a winning-entry claim.**

## Score breakdown

The category weights come from the [preserved webinar rubric](../meta-provided/webinar/2026-10-26-judging-rubric.png), summarized in the [hackathon brief](HACKATHON_BRIEF.md). The awarded points are reviewer judgments. The organizers did not supply the specific deductions described here.

User interviews, a public replay, and aggregate resource controls are examples of evidence that would strengthen this review. They are not being presented as official eligibility requirements, and equivalent evidence could support a higher assessment.

| Category | Available | Awarded | Points withheld | Main reason |
| --- | ---: | ---: | ---: | --- |
| Impact | 30 | 14 | 16 | A clear problem, without confirmed firsthand experience, user validation, or measured benefit. |
| Use of Meta AI tooling | 25 | 8 | 17 | A substantive adapter exists, but the successful reviewed runs used deterministic generation. |
| Technical depth | 20 | 16 | 4 | Strong implemented verification, with limited evaluation breadth and remaining containment limits. |
| Demo | 25 | 17 | 8 | The local workflow works, but the final recording, live Meta reliability evidence, and shareable experience were missing. |
| **Total** | **100** | **55** | **45** | **Working controlled prototype; insufficient evidence for the broader claim.** |

The score is the sum of the weighted category points: **14 + 8 + 16 + 17 = 55**. It is not a test pass percentage. The seven isolated-runtime tests are already included in the orchestrator test count; they are not additional independent evidence to count twice.

## 1. Impact: 14/30

### Why it earned 14 points

The problem is specific and understandable. A shopper leaves the coupon field empty, the backend subtracts `None`, and checkout returns HTTP 500. The intended beneficiaries are backend engineers and QA/reliability teams evaluating repairs to customer-facing failures.

The prototype also produces a useful engineering output: a candidate patch accompanied by browser evidence, business assertions, and cleanup status. That is more useful than an unverified code suggestion.

Evidence: the [registered scenario](../shared/config/scenarios.py), [seeded checkout tests](../apps/buggyshop-backend/tests/test_checkout_seeded.py), and [independent HTTP assertions](../services/repair-orchestrator/app/http_regression.py).

### Why the other 16 points were withheld

- **Firsthand relevance was not established.** The reviewed materials did not contain a confirmed account of this problem from the builder's own experience. A plausible story is not firsthand evidence.
- **Demand was not validated.** No retained interviews, pilot use, or adoption evidence established that intended users would prefer this workflow to existing debugging and code-review tools.
- **The benefit was not measured.** There was no supported estimate of engineering time saved, incident-resolution improvement, or customer loss avoided. Earlier revenue figures could not earn credit.
- **The demonstration was narrow.** One deliberately seeded checkout defect does not establish usefulness across the failures a real engineering team encounters.

The missing evidence does not prove the product lacks impact. It limits how much impact the review could responsibly credit.

### What would justify a higher score

Document the builder's actual experience, obtain feedback from intended users, and evaluate representative failures. Compare the workflow against a stated baseline using recorded time, repair quality, reviewer effort, and unsuccessful outcomes. Label estimates and assumptions clearly.

## 2. Use of Meta AI tooling: 8/25

### Why it earned 8 points

Meta integration is implemented in meaningful code. The adapter supports a configured Meta endpoint/model, startup probing, a strict proposal contract, bounded failure evidence, provider-error handling, and validation feedback for another attempt. Proposed changes must pass independent gates.

The implementation and its tests earn engineering credit even though the review did not certify a live Meta repair.

Evidence: the [model adapter](../services/repair-orchestrator/app/model_adapter.py), [adapter tests](../services/repair-orchestrator/tests/test_model_adapter.py), and [repair worker](../services/repair-orchestrator/app/worker.py).

### Why the other 17 points were withheld

- **The successful reviewed jobs were deterministic.** Their recorded provider was `deterministic`, with model identity `deterministic-checkout-v1`. They proved the execution and verification workflow, not Meta's ability to generate the repair.
- **A configured model name is not a successful model trial.** Code that targets `muse-spark-1.3` cannot establish that a live response produced a valid, useful patch.
- **Repeatability was not established.** There was no reviewed series of live Meta trials reporting successful repairs, rejected proposals, unresolved cases, latency, and actual usage together.
- **Generality was not demonstrated.** The known default-zero coupon repair does not show how well Meta handles unfamiliar defects or uses verification feedback to improve an initially incorrect proposal.

The low score reflects the available evidence. It does not establish that Meta access is impossible or that the adapter cannot work when configured.

### What would justify a higher score

Configure credentials privately and retain complete live Meta jobs: provider/model identity, actual proposal, failed baseline, policy result, candidate verification, and cleanup. Run repeated trials and unfamiliar cases, including failures. Show that model generation contributes useful behavior beyond the deterministic repair path.

## 3. Technical depth: 16/20

### Why it earned 16 points

This was the strongest category. The repaired implementation included:

- Transactional admission, idempotency, durable execution records, and exclusive runtime ownership.
- Exact single-file diff application, source hashes, restricted imports, and AST checks.
- Application exports from pinned detached Git worktrees.
- Linux namespace isolation, readonly mounts, bounded response streaming and private temporary storage.
- External trusted browser and HTTP assertions, with real screenshots, trace archives, and correlated logs.
- Cancellation, process supervision, reset recovery, and cleanup quarantine.
- Passing automated checks and builds.

The review recorded 159 backend/script tests, 198 orchestrator tests, 32 runner unit tests, and eight Inspector browser tests: **397 automated tests**. The real candidate execution passed **44 recorded assertions**. Those assertion results are a separate measurement, not 44 additional repository tests.

Evidence: the [runtime implementation](../services/repair-orchestrator/app/isolated_runtime.py), [runtime tests](../services/repair-orchestrator/tests/test_isolated_runtime.py), [worker lifecycle tests](../services/repair-orchestrator/tests/test_worker_lifecycle.py), and [full verification record](QUALITY_REVIEW.md#verification).

### Why the other 4 points were withheld

- **Containment has practical limits.** Resource limits are per process; they do not provide an aggregate cgroup memory quota. A Linux namespace boundary is not a VM.
- **Evaluation breadth remains limited.** A large passing suite around one repair case does not establish robustness across arbitrary applications or unfamiliar defects.
- **Independent assurance remains incomplete.** The containment and verification design warrants further external review before broader exposure or arbitrary project execution.

The earlier unsafe host runtime and fabricated artifacts were fixed before this score was assigned. They are not being treated as current defects or charged again as separate penalties. Their existence made observable evidence especially important.

### What would justify a higher score

Add aggregate resource accounting, independently review containment, and extend evaluation to representative defects and difficult lifecycle failures. Keep the oracle protected and report skipped or unavailable checks explicitly. More tests that merely repeat the implementation would not justify more points.

## 4. Demo: 17/25

### Why it earned 17 points

The local workflow completed through the controller: reproduce the real checkout failure, generate a deterministic candidate, verify it in isolation, retain evidence, and confirm cleanup.

The Inspector showed actual provider identity, attempts, diffs, assertions, artifacts, and terminal states. Desktop and mobile inspection found no JavaScript errors or horizontal overflow in the exercised views. The browser suite covered failure handling, reload recovery, cancellation/interruption, and authored-preview separation.

Evidence: the [actual Inspector screenshot](assets/inspector.png), [Inspector browser tests](../tools/browser-runner/tests/inspector/inspector.spec.ts), and [rehearsal script](../scripts/rehearse-demo.sh). The screenshot explicitly identifies deterministic mode.

### Why the other 8 points were withheld

- **The final video was not available for assessment.** A working local interface does not establish that the three-minute explanation is clear, well paced, and memorable.
- **Live Meta reliability was unproven.** A deterministic rehearsal cannot establish whether the intended live model demonstration will hold up during judging.
- **The experience was not readily shareable.** There was no reviewed public demo or read-only replay for judges and viewers to inspect independently.
- **The scope still looked like a controlled fixture.** The presentation needed to explain the value of verification while being candid that only one real repair scenario was registered.

### What would justify a higher score

Record an actual live Meta job. Open with the failing checkout, show the generated diff and passing candidate, then show the retained evidence and cleanup. Rehearse within the time limit. Provide a reviewed shareable replay or demo, with captions and a clear source link.

## Virality assessment

Virality was not a fifth category added to this 100-point score. It was a separate launch-quality concern.

FaultLine has a potential visual story: a checkout fails, a patch is proposed, and the same journey succeeds under independent verification. At assessment time, there was no published demo-engagement evidence establishing that this story would spread.

Fabricated timers, receipts, performance claims, or success states would undermine that story. The next useful asset is a short recording of an actual run with inspectable evidence. See the [launch drafts](LAUNCH.md) and [video storyboard](VIDEO_STORYBOARD.md).

## What to prioritize

| Priority | Evidence to produce | Why it matters |
| --- | --- | --- |
| 1 | Repeated live Meta repair jobs, with failures retained | Addresses the largest tooling-evidence gap and strengthens the intended demo. |
| 2 | Unfamiliar defects or a second actual scenario with protected assertions | Tests whether the system does more than repair its known fixture. |
| 3 | A confirmed firsthand problem account and feedback from intended users | Gives the impact claim a foundation beyond plausible economics. |
| 4 | A clear final recording and reviewed public replay/demo | Makes the work easier to judge, understand, and share. |
| 5 | Aggregate resource controls and further independent containment review | Supports broader technical claims and future exposure. |

These actions would justify reassessment after their results are inspected. They do not guarantee additional points, a particular final score, a prize, or a viral outcome.

## Remediation since this assessment

Updated October 28, 2026. The score above remains the October 27 record of commit `925507a`. This section lists what changed afterwards and what evidence now exists. **It is not a reassessment.** The person who implemented these changes should not grade them. A fresh skeptical review, ideally after the owner-dependent evidence below exists, should decide whether any points move.

| Category | Reason points were withheld | Action taken | Evidence now available | Still required |
| --- | --- | --- | --- | --- |
| Impact | Benefit not measured | Authored a hash-pinned corpus of correct, wrong, and out-of-policy repairs and measured them against a naive symptom check | [EVALUATION.md](EVALUATION.md): the symptom check accepted 5 of 6 wrong repairs; FaultLine accepted 0 and both correct repairs | Labeled as an authored corpus, not a real-world defect rate |
| Impact | Demonstration was narrow | Added nine unfamiliar single-defect variants of the checkout route and an evaluation harness | Holdout results per provider in [EVALUATION.md](EVALUATION.md) | Still one route in one fixture application |
| Impact | Firsthand relevance; demand not validated | Prepared [IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md) with an interview guide, log, and timing protocol; nothing was written on the owner's behalf | None yet | Owner's firsthand account and 3–5 intended-user conversations |
| Meta tooling | Successful runs were deterministic; repeatability not established | Built `scripts/trial_ledger.py`, which records repeated controller jobs and refuses to label non-Meta responses as Meta | Deterministic ledger (5 of 5 verified, labeled as rehearsals); [retained Meta controller replay review](evidence/2026-10-28-meta-replay-review.md) | Run repeated Meta trials with `--require-provider meta` and the Meta holdout evaluation |
| Meta tooling | Generality and use of verification feedback not shown | The prompt now states the business contract, not the defect. Rejected attempts send bounded gate findings to a second attempt. Miscounted hunk headers are recounted. Provider identity is derived from the endpoint host | A non-Meta model (DeepSeek, labeled as such) verified 18 of 20 unfamiliar-defect runs. One repair succeeded only after a specific proposal error was fed back, and the oracle rejected two wrong patches | The same measurement with Meta's model |
| Technical depth | No aggregate resource quota | Every candidate backend runs in a systemd user scope with cgroup v2 memory, swap, task, and CPU limits. The limits are read back from kernel files, and an OOM and task-limit probe must pass before readiness | Real tests with memory and task hogs; every evaluation session recorded verified limits | CPU throttling is configured but not probed |
| Technical depth | Independent assurance incomplete | Internal AI-assisted adversarial containment review and correctness review, with real probes; all accepted findings fixed and regression-tested | [QUALITY_REVIEW.md](QUALITY_REVIEW.md#follow-up-review-and-remediation--october-28-2026) | External human review; seccomp filter |
| Technical depth | Evaluation breadth limited | Oracle hardened so candidate crashes, hangs, and oversized responses are measured failures rather than infrastructure errors | Regression tests; corpus baselines match recorded failures in every run | Defects outside the checkout route |
| Demo | Not shareable | Static, checksummed, script-free replay export | [docs/replay/](replay/83d1c403-9f6a-4d69-9a46-e39c83ac2471/index.html) from a deterministic rehearsal, labeled as such | A [retained Meta replay](evidence/2026-10-28-meta-replay-review.md) is now available, and GitHub Pages serves the replays. The owner must decide on its trace archives, which contain workstation paths |
| Demo | Final video missing; live Meta reliability unproven | Inspector now shows provider identity honestly, gate feedback between attempts, and enforced containment | Browser tests for these views | Record the video; rehearse with Meta |

An October 28 [review of retained replay evidence](evidence/2026-10-28-meta-replay-review.md) now confirms internally consistent controller records of a Meta repair, including 44 passing assertions and successful cleanup. This updates the earlier absence-of-evidence statement without changing the historical score. Repeated Meta trials and a Meta holdout evaluation remain outstanding. Configure the credential privately, start the demo, and run:

```bash
uv run --project apps/buggyshop-backend --python 3.13 --locked \
  python scripts/trial_ledger.py --trials 5 --require-provider meta --out data/trials/meta.json
./scripts/evaluate.sh --suite holdout --repeat 2
```

A later revision of this file claimed a 93/100 reassessment based on unverified impact material and features that did not work as described. It was withdrawn on October 28 after an audit; see [CHRONOLOGICAL_ADJUSTMENTS.md](CHRONOLOGICAL_ADJUSTMENTS.md). The 55/100 record above remains the only score.
