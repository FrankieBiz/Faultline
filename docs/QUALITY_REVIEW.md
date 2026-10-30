# FaultLine quality review — October 27, 2026

**Verdict: the repaired prototype is materially stronger, but the available evidence does not justify calling it a winning entry yet.** The biggest original weaknesses were false verification and unsafe execution, not a shortage of visual effects.

This is a repository-grounded assessment, not an organizer score or a guarantee of finding every possible defect. The review covered backend behavior/contracts, orchestration, patch policy, source provenance, runtime isolation, browser evidence, Inspector behavior, storefront flows, automation, dependencies, documentation, and launch claims.

## Findings and fixes

| Severity | Observed problem | Remediation and evidence |
| --- | --- | --- |
| Critical | The environment-selectable demo runtime imported proposed Python in a host subprocess. Worktrees and AST checks were presented as containment. | Removed that adapter. The explicit Linux runtime uses Bubblewrap namespaces, readonly application/interpreter mounts, private network/PID namespaces, bounded private tmpfs, and an inherited prebound backend listener. Actual fixture/browser execution is tested. |
| Critical | The runtime invented PNG/ZIP bytes, error correlation, and failure assertions. | Replaced with real Chromium screenshots/traces, bounded request logs, actual correlated server logs, measured assertions, and execution provenance. The seven runtime tests validate these artifacts and lifecycle behavior. |
| High | Allowed dependency imports exposed unintended transitive capabilities. Private attributes in class patterns escaped the attribute check. | Exact imported-symbol policy, rejected bare module imports, and private-pattern attribute checks. Adversarial policy regressions verify rejection without executing the rejected code. AST policy is still not a sandbox. |
| High | Chaos Studio announced recovery on a timer before starting the actual job; exported audit packets contained invented tokens, successes, and economic figures. | Removed the simulated healer and fabricated audit UI. The Inspector now renders actual records, proposals, assertions, artifacts, and cleanup. Previews are explicitly authored references. |
| High | Quarantined reset callers could overwrite each other's maintenance lease. Crashed resets could leave permanent ownership. | Exclusive maintenance ownership, released completed reset owners, and startup handling for orphan reset reservations. Cross-connection race and restart tests cover these paths. |
| High | The rehearsal printed verified success for failed jobs, then tested TENOFF, which already worked before repair. | Success now requires verified terminal outcome, failed baseline, passing candidate assertions, and successful cleanup. Six script regressions reject failed/cancelled/interrupted/unclean/false-pass results. |
| High | Startup/reset killed arbitrary processes on fixed ports, removed evidence, overwrote source, and bypassed proper worktree cleanup. | Reset now calls authenticated controller reconciliation through the Inspector. Startup preserves source/history, refuses port collisions, supports alternate ports, installs traps before process creation, and terminates only owned process groups. |
| High | Artifact proxy tried to parse PNG and ZIP downloads as JSON. | Raw byte streaming with content type, inert download headers, and upstream status preserved. Binary-byte regression passes; actual live screenshots decode in the Inspector. |
| Medium | SSE proxy discarded reconnect cursors and mislabeled JSON errors as event streams. Oversized cursors overflowed SQLite integers. | Cursor forwarding, preserved upstream content types, and signed-integer API/database bounds, with regressions. |
| Medium | The Inspector used a known fallback controller credential and accepted cross-site mutation requests. | Server credential is required; launcher generates a private session credential when absent. Proxy rejects cross-origin mutation requests and restricts routes. It remains a local application, not a public multi-user service. |
| Medium | Cancelled/interrupted jobs polled forever; reload did not reliably reattach; reset errors appeared successful. | All terminal states stop polling; reload follows the durable latest job; errors remain visible. Inspector browser tests exercise each behavior. |
| Medium | Frontend rewrites baked the development backend into the build, preventing per-candidate routing. | Runtime API proxy selects each candidate's backend and retains case/request correlation. Proxy test and actual isolated browser runs verify this. |
| Medium | Screenshot failures could still yield an application-level verdict without required evidence. | Screenshot capture failure now classifies the run as infrastructure failure. Focused runner regression passes. |
| Medium | Historical “verified” records could retain fabricated evidence from the old runtime. | New execution records identify `isolated-browser`; legacy records default to `unverified`. The Inspector explicitly labels historical success without provenance as unverified. History is preserved. |
| Medium | The local judge awarded full marks from filenames and source-string presence. | Replaced automatic scoring with an actual optional check runner and explicit unknown judging score. The mock judging material now requires evidence and states limits. |
| Medium | README/submission/storyboard claimed production traffic switching, compliance, saved revenue, live Meta timings, and a 100/100 score without retained support. | Rewrote the materials around verified candidates and actual scope. Prepared truthful submission, storyboard, and launch drafts. |
| Low | Checkout fields remained editable while a purchase was in flight, allowing local cart edits to be erased when that order completed. | Form controls are disabled during submission; the existing single-request guard remains. |
| Low | Fresh-clone instructions omitted dependency setup and specified the wrong Node version. No repository verification workflow existed. | Added locked setup, Node 24+ instructions, browser installation, and a workflow with pinned official action revisions. |

The replacement runtime was also reviewed for bounded response streaming, socket ownership, cancellation, parent connection loss, and cleanup retry. Host-writable socket mounts were eliminated; response limits apply before buffering; supervised processes are reaped; failed cleanup retains ownership for retry. These are implemented safeguards, not a claim of complete sandbox security.

## Verification

Fresh local checks:

- `make check`: 159 backend/script tests, 198 orchestrator tests, 32 runner unit tests; Ruff lint/format, strict mypy, frontend lint/type/build, Inspector type/build, runner build, provenance, and Python distributions passed.
- `make browser`: eight Inspector browser tests passed, including mobile sizing, keyboard focus, reset failure, terminal states, reload, explicit fallback, and legacy records.
- Required isolated-runtime suite: seven tests passed, including actual baseline/healthy browser behavior and real Chromium cancellation/parent-connection cleanup. These seven are already included in the 198 orchestrator tests.
- Two complete controller rehearsals used the explicitly labeled deterministic provider. Both reproduced the expected browser failure, verified 44 candidate assertions, and confirmed cleanup. Example retained job: `6faab2a5-e52a-470b-9858-ab3a70d43cbb`. This is not a live Meta trial.
- Actual desktop (1440 px) and mobile (390 px) Inspector render: no JavaScript errors or horizontal overflow; both registered screenshots decoded correctly.
- The checkout field lock was exercised in a real browser with a deliberately held request; name, coupon, and quantity controls disabled during submission, then the actual TENOFF order completed.
- Node dependency installation audits reported zero known vulnerabilities. Python package audit reported no known vulnerabilities in third-party orchestrator dependencies; the unpublished local project package was outside the advisory database.
- All five protected webinar SHA-256 checks passed. `meta-provided/` was not modified.

Initial verification exposed missing Node dependencies in the fresh worktree; locked installation resolved that. Intermediate checks caught a cross-package TypeScript test configuration issue, one ambiguous Playwright locator, and lint errors in a new script fixture; each was corrected before the final gates. No failed check is being presented as success.

An overlapping startup build invalidated one browser run and three runtime-readiness checks. Building completed before rerunning them; the final eight browser and seven required runtime checks passed. The captured [Inspector image](assets/inspector.png) comes from the completed real local workflow.

## Follow-up review and remediation — October 28, 2026

This pass acted on every gap in the [score assessment](HACKATHON_SCORE_ASSESSMENT.md) that engineering could address. Two separate internal reviews (a correctness review of the full diff and an AI-assisted adversarial containment review with real probes) checked the new work. Their findings were fixed before the final gates below. External review is still outstanding.

| Severity | Observed problem | Remediation and evidence |
| --- | --- | --- |
| High | The trusted HTTP oracle called `response.json()` unconditionally. A wrong candidate that raised a non-`TypeError` exception, hung, or returned an oversized body crashed the oracle, so the job was misreported as an infrastructure error and skipped the second attempt. | Candidate faults now become failed checks with the observed fault. Regression tests cover plain-text 500s, timeouts, and the response cap. |
| High | The second repair attempt received only a gate code such as `verification_failed`, never what failed. | Bounded gate findings (failing assertions with expected/observed values, policy error, rejected diff) are sent as untrusted evidence. Each attempt records `prior_feedback`; the Inspector and replay show it. |
| High | Any configured endpoint was labeled `meta` in evidence. A non-Meta key and URL would have produced records claiming Meta inference. | Provider identity is derived from the endpoint host only. Attempts record `provider`/`model` only from a returned response; the dispatched endpoint is stored separately, so provider errors never count as model output. |
| High | The evaluation harness aborted and lost all results when a candidate failed at import. | Such candidates are rejected with feedback; results are checkpointed after every case and marked incomplete if the run stops. |
| Medium | Candidates could read Bubblewrap's initial environment through `/proc/1/environ`. | `env -i` empties it before Bubblewrap starts; the enforcement probe asserts it. |
| Medium | Uncaught candidate tracebacks reached the backend log as raw multi-line text, so a source line shaped like a correlated JSON event could appear in trusted logs. | Every record, including uncaught tracebacks, is one escaped JSON line. A real isolated test proves a forged event line is not parsed as an event, and fails without the fix. |
| Medium | The system prompt described the seeded defect ("optional-coupon arithmetic failure"), so it did not test unfamiliar defects. | The prompt now states the checkout business contract, never the defect or its fix. |
| Medium | `reasoning_effort` was always sent, and strict `json_schema` output was mandatory. Compatible models without these features could not be evaluated. | `META_REASONING_EFFORT` and `META_RESPONSE_FORMAT` are configurable. The defaults remain the documented Meta settings, and local strict validation is unchanged. |
| Medium | Models miscount unified-diff hunk headers. In a real development run, a semantically correct patch was rejected for a header that declared seven lines for a six-line body. | Like `git apply --recount`, hunk counts are recomputed from the body and a hunk is relocated only to its single exact match. Content is never edited. The strict policy validates the result, and the model's original output is retained. |
| Low | `--unshare-all` silently skips the user namespace where Bubblewrap is setuid. | `--unshare-user` is explicit, and the preflight asserts that the sandbox's user and network namespaces differ from the controller's. |
| Low | Truncated 16-character scope prefixes could collide across installations. A scope that failed to start was blamed on the candidate. | Prefixes use the full installation ID. The scope must be observed active with configured limits before the candidate serves, and infrastructure failures are never recorded as candidate verdicts. |
| Low | Proposal-contract errors all reported `proposal_scope_mismatch`, so a retry could not tell what to correct. | Specific codes now distinguish target, base hash, missing diff, and oversized diff. |

New capabilities: aggregate cgroup v2 limits for every candidate backend, verified from kernel files and proven by an enforcement probe before readiness; a hash-pinned evaluation corpus and harness; a trial ledger for repeated controller jobs; and a static, checksummed read-only replay export. See [EVALUATION.md](EVALUATION.md) and [IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md).

Residual risks accepted for now: no seccomp filter; the candidate's abstract listener is reachable from other local processes that know its random name; trusted parsers outside the sandbox read candidate-influenced bytes; the CPU quota is configured and read back but not probed.

### Audit of later additions — October 28, 2026

A parallel session added a payload minimizer, an AST analyzer, an evidence bundle, a terminal walkthrough, and new impact content. An audit found fabricated evidence and unsupported claims among them. In repair jobs the minimizer used a hardcoded oracle and payload. The walkthrough printed successes it never measured. The bundle claimed cryptographic authenticity and was never actually saved. The impact interviews predate the features they describe. These were corrected or removed, and a real catch-all-exception rule was added to the patch policy. Details are in [CHRONOLOGICAL_ADJUSTMENTS.md](CHRONOLOGICAL_ADJUSTMENTS.md).

## Retained Meta evidence review — October 28, 2026

The [replay provenance review](evidence/2026-10-28-meta-replay-review.md) checked a retained controller-recorded `meta` / `muse-spark-1.3` repair: failed baseline, 44 passing candidate assertions, successful cleanup, 16 matching replay checksums, and a consistent evidence bundle. No fresh Meta call was made during this review. This supersedes earlier statements that no recorded Meta repair existed; it does not establish Meta holdout performance or repeated-run reliability. Both retained ZIP traces contain workstation paths. They are now publicly served by GitHub Pages and need the owner's decision. The historical score below is unchanged.

## Harsh provisional judging assessment

The [standalone score assessment](HACKATHON_SCORE_ASSESSMENT.md) explains each awarded score, the missing evidence, and what would justify reassessment.

These are my evidence-limited estimates, not official results. The rubric weights are preserved from the provided webinar material; the official pages were rechecked October 27, 2026 ([Meta](https://dev.meta.ai/events/global-hackathon), [Cerebral Valley](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon)).

| Criterion | Estimate | Why points are still missing |
| --- | --- | --- |
| Impact | 14/30 | Clear transactional problem, but no confirmed firsthand incident, user feedback, adoption, or measured benefit. |
| Meta AI tooling | 8/25 | Substantive adapter and verification architecture; no live Meta run is certified in this workspace. The successful current runs are deterministic. |
| Technical depth | 16/20 | Real contained execution, durable lifecycle, independent checks, and evidence. Per-process resource limits do not provide an aggregate cgroup quota; broader isolation review and unfamiliar defects remain. |
| Demo | 17/25 | The core loop works and the UI now shows its evidence. A strong final recording, public experience, and repeated live Meta reliability evidence are still missing. |
| Total | **55/100** | A defensible prototype; insufficient evidence for a frontier repair platform. |

## Highest-value remaining work

Written October 27. Status as of October 28: aggregate limits (item 6) and an unfamiliar-defect corpus (item 2) are implemented, and two retained Meta controller repairs exist, though not a repeated series (item 1). Static replays are published on GitHub Pages (item 5). External review, repeated Meta trials, impact evidence, and the recording remain open.

1. **Live Meta evidence.** Configure the credential privately and retain repeated real attempts, including failures, actual usage, browser artifacts, and cleanup. Provider identity must remain visible.
2. **Generalization.** Keep the controlled demo, but add independent holdout defects or a second actual scenario with protected assertions. A model repairing a known one-line fixture does not establish general repair ability.
3. **Firsthand impact.** Record the builder's actual experience and interview intended users. Replace hypothetical downtime economics with evidence or clearly labeled assumptions.
4. **A compelling recording.** Open with the actual failure, show the actual diff and passed candidate, and let viewers inspect the evidence. Use the updated storyboard. Do not reinstate a fake timer to shorten the story.
5. **A shareable public experience.** Provide a reviewed read-only replay or separately hardened execution service. No public deployment or social publishing is part of this review.
6. **Stronger containment before broad exposure.** Add aggregate resource accounting and external review before accepting arbitrary projects or untrusted public jobs. The current namespace profile is not a VM.

[Launch drafts](LAUNCH.md) and [submission text](DEVPOST_SUBMISSION.md) are ready for further evidence. Winning and virality are outcomes to earn, not labels to display in the product.
