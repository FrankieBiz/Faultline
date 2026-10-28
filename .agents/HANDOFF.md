# Agent handoff state

Updated October 27, 2026. Branch: `FrankieBiz/hackathon-full-codebase-review`.

## Objective and completed changes

Full adversarial project review requested by Frankie, including correctness, UI, hackathon credibility, and virality. See `docs/QUALITY_REVIEW.md` for findings, evidence, and remaining work.

Removed unsafe host-executing LocalDemoRuntime and fabricated browser artifacts/UI audit reports. Added explicit `FAULTLINE_RUNTIME=isolated` Bubblewrap runtime, real Chromium/HTTP verification, correlated logs, bounded responses/tmpfs, supervised owned processes, and cleanup retry. Candidate execution records identify `runtime_kind=isolated-browser`; legacy records remain unverified. Fixed import/pattern policy gaps, reset concurrency/restart recovery, SSE cursor bounds, binary/SSE proxy handling, runtime storefront routing, and terminal UI states.

Replaced timer-driven marketing UI with measured evidence Inspector and clearly authored scenario references. Removed unused simulated healer, hardcoded metrics, nonexistent integration snippets, fabricated competition scores, and misleading compliance/deployment claims. Rewrote readme/submission/video/launch documents. Setup/start/reset/rehearsal scripts now preserve evidence and source and avoid killing unrelated processes. Added regression tests and a pinned GitHub verification workflow.

## Settled decisions

- Backend scenario/contracts from the earlier handoff remain authoritative: `scripted_checkout_repair`, two Trail Mugs, integer cents, TENOFF/FIFTEEN, strict quantities/inputs. Live checkout stays byte-identical to the seed.
- A verified candidate is not a production deployment. Worktrees and AST policy are not process containment.
- Missing credentials select the explicitly identified deterministic provider. Never describe these runs as Meta inference; configured provider errors never silently fall back.
- Runtime is Linux/Bubblewrap, with per-process resource limits, not a VM or aggregate cgroup quota. External review remains appropriate before broader exposure.
- Protected `meta-provided/` was untouched and all five hashes were checked.

## Verification and current environment

`make check` passed: 159 backend/script tests, 198 orchestrator tests, 32 runner unit tests; lint/type/build/provenance passed. Eight Inspector browser tests passed. Seven required isolated-runtime tests passed (already included in 198). Controller rehearsals verified actual failed baseline, 44 candidate assertions, and cleanup using the deterministic provider. Live Meta validation is pending private credential configuration.

Other existing demo services on 3000/4000/8000/9000 belonged to an earlier session and were preserved. This review uses 13000/14000/18000/19000 for its own demo. Do not kill unrelated port owners. Startup supports `BUGGYSHOP_PORT`, `INSPECTOR_PORT`, `BUGGYSHOP_API_PORT`, and `FAULTLINE_PORT`. Use `FAULTLINE_INSPECTOR_URL` for rehearsal/reset with alternate ports.

## Avoid repeated dead ends

- Never re-enable host candidate execution or fabricate PNG/ZIP/HTTP evidence to satisfy worker gates.
- Runtime scratch belongs beneath the snapshot-owned runtime tree. Filesystem Unix sockets exceeded Linux's pathname limit there; inherited prebound abstract sockets solve it without writable host mounts.
- Do not build `.next` while another worker exercises that exact production build; a concurrent build caused a transient frontend readiness failure. Build first, then run browser/runtime checks.
- NodeNext runner type checks cannot import Next source across package module boundaries directly. Cross-package proxy tests use Playwright JS; UI browser tests use the DOM lib.
- The separate frontend model wrote its proposal to `/tmp` and was stopped after the proposal was integrated/tested. Runtime proposal was independently reviewed and integrated; no worker commits were made.

## Next evidence needed

Private Meta credentials, repeated live trials, holdout/generalization cases, confirmed firsthand problem evidence/user feedback, final demo recording, and reviewed public replay. No social message, deployment, video publication, or hackathon submission was sent.

## Long-term research notebook — October 27, 2026

Completed an expanded `docs/LONG_TERM_RESEARCH_AND_IDEAS.md` at the owner's request for extensive research and brainstorming. It replaces the earlier short blueprint with repository-grounded strategy, detailed technical proposals, 120 catalog ideas, 12 experiments, phased evidence gates, economics assumptions, and a dated register of 46 primary web sources. Proposed experiments are not implemented or claimed as executed. No extra research models were called.

The current official Cerebral Valley page lists a $100 Fireworks offer, while `docs/HACKATHON_BRIEF.md` says $25. The notebook records the discrepancy without changing protected sources or claiming personal account credits. Existing architecture and scope decisions above remain applicable.

Delivery verification for the research task: document structure/local links/contents anchors and `git diff --check` passed. Fresh `make check` passed with 159 backend/script tests, 198 orchestrator tests, and 32 runner unit tests, plus lint/type/build/provenance and Python distributions. The first check stopped at missing frontend dependencies; locked `npm ci` installs, Chromium availability, and prerequisite frontend/runner builds resolved the environment gap before the successful rerun. No application source was changed for this task.
