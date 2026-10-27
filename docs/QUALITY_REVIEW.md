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

## Harsh provisional judging assessment

These are my evidence-limited estimates, not official results. The rubric weights are preserved from the provided webinar material; the official pages were rechecked October 27, 2026 ([Meta](https://dev.meta.ai/events/global-hackathon), [Cerebral Valley](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon)).

| Criterion | Estimate | Why points are still missing |
| --- | --- | --- |
| Impact | 14/30 | Clear transactional problem, but no confirmed firsthand incident, user feedback, adoption, or measured benefit. |
| Meta AI tooling | 8/25 | Substantive adapter and verification architecture; no live Meta run is certified in this workspace. The successful current runs are deterministic. |
| Technical depth | 16/20 | Real contained execution, durable lifecycle, independent checks, and evidence. Per-process resource limits do not provide an aggregate cgroup quota; broader isolation review and unfamiliar defects remain. |
| Demo | 17/25 | The core loop works and the UI now shows its evidence. A strong final recording, public experience, and repeated live Meta reliability evidence are still missing. |
| Total | **55/100** | A defensible prototype; insufficient evidence for a frontier repair platform. |

## Highest-value remaining work

1. **Live Meta evidence.** Configure the credential privately and retain repeated real attempts, including failures, actual usage, browser artifacts, and cleanup. Provider identity must remain visible.
2. **Generalization.** Keep the controlled demo, but add independent holdout defects or a second actual scenario with protected assertions. A model repairing a known one-line fixture does not establish general repair ability.
3. **Firsthand impact.** Record the builder's actual experience and interview intended users. Replace hypothetical downtime economics with evidence or clearly labeled assumptions.
4. **A compelling recording.** Open with the actual failure, show the actual diff and passed candidate, and let viewers inspect the evidence. Use the updated storyboard. Do not reinstate a fake timer to shorten the story.
5. **A shareable public experience.** Provide a reviewed read-only replay or separately hardened execution service. No public deployment or social publishing is part of this review.
6. **Stronger containment before broad exposure.** Add aggregate resource accounting and external review before accepting arbitrary projects or untrusted public jobs. The current namespace profile is not a VM.

[Launch drafts](LAUNCH.md) and [submission text](DEVPOST_SUBMISSION.md) are ready for further evidence. Winning and virality are outcomes to earn, not labels to display in the product.
