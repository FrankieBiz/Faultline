# FaultLine — Principal Systems & Security Engineer Overview

**Assessment date:** November 1, 2026. **Reviewed revision:** `d8b84b3f317dc067204a37dc2b6efaecab3e6862`, branch `FrankieBiz/systems-codex-eval`.

**Baseline review method:** implementation review, fresh builds and automated tests, real Linux isolation tests, and two targeted behavioral probes. This is an engineering assessment of the checked-out revision, not a penetration-test certification. No application implementation was changed, no live model inference was requested, and no protected Meta materials or credential files were opened during that original report-only task. No Orca children were launched during the original review.

## Pre-filming remediation and verification — November 1

**Filming decision: ready for the bounded demonstration in the revised [three-minute storyboard](../../docs/VIDEO_STORYBOARD.md).** The original audit below is preserved as the baseline; its open findings must be read alongside this update. The fixture rehearsal and proof are from `b3f5bfe901ac8958e96ba51c7d1cc06ca3a6fc04`; the later generic browser-readiness fix is `7c6deecd164acc25351b86b0e255b5608473a661`. Exact measured results and child-dispatch provenance are retained in the [verification record](../../docs/evidence/2026-11-01-prefilm-verification.json).

At the owner's request, two real `gpt-6.1-sol` high-effort Orca children and two real `claude-opus-5-5` high-effort Orca children implemented and self-verified disjoint changes. The coordinator reviewed the changes, integrated them, and independently ran the final checks and local rehearsal. All four children completed and were released.

| Baseline finding | Adjustment and current boundary |
| --- | --- |
| F1: incomplete crawl approved deployment | Fixed in `80ca294`, with Inspector parity in `b1c0eae`. Only `clean` plus `stop_reason: exhausted` passes. An action/time limit or missing completion reason blocks as `incomplete_crawl`. JSON includes stop reason and action count. A completed crawl is still a bounded smoke signal, not proof of business completeness. |
| F2: proof preceded cleanup | Fixed in `a071c6d`. Schema 3 proof registration and final verified job outcome commit in one SQLite transaction after successful cleanup. Compiler/write/read/finalization failures, cancellation, and simulated crashes are covered by fault-injection tests. Proof binds lifecycle, source, generation, actual execution-limit metadata and provider identity. Schema 2 artifacts remain untouched and are explicitly consistency-only legacy records. |
| F3: route-only scan dispatch | The CLI now also requires a controller-advertised, operator-configured origin. The seeded storefront proxy and backend origins are advertised explicitly; unrelated origins and unsupported generic bindings are refused. Repair still proves the registered scenario's candidate, and does not automatically modify an arbitrary scanned application. |
| F4: host-side trust boundaries | Crawler subprocesses now receive a minimal environment rather than inherited model/control credentials. Broader browser resource/network containment, shared-kernel exposure and artifact custody remain hardening work; no new VM or seccomp guarantee is claimed. |
| Demo claims and dependencies | `e3dc207` distinguishes authored assertions from kernel confinement, limits Apply to the bundled demo store, cites the retained October 31 Meta ledger, labels historical replays, removes the Inspector's external AuraScale presets, and supplies explicit live/retained captions. AuraScale is not required for filming. |

The final browser run also caught a pre-existing intermittent checkout failure that had previously been dismissed as a flake. Instrumentation established a real focus race: after an HTTP error re-enabled the form, the alert's passive effect could steal the next coupon-edit keystroke. `b3f5bfe` moves focus into the same render commit with `useLayoutEffect`; it preserves alert focus and coupon-review behavior. The new regression failed 10/10 before the fix, the child recorded 200/200 passing repetitions after it, and the coordinator's final storefront suite passed both tests. No assertion was weakened and no retry or sleep was added to hide the race.

Fresh coordinator verification on the integrated filming code before the hosted-runtime follow-up:

- `make check`: **1,282 passed** (290 backend/script, 869 orchestrator/CLI, 123 runner), plus lint, format, strict typing, provenance and builds; exit 0.
- `make browser`: **45 passed** (43 Inspector, 2 storefront); exit 0. The earlier storefront failure was investigated and fixed before this final run.
- Required isolation-focused invocation documented below: **14 passed, zero skips**; exit 0. These overlap `make check` and are not additional unique tests.
- Desktop/mobile visual checks of both live Inspector and judge page at 1440/390 px: **no console errors or horizontal overflow**. The actual Inspector job rendered “Verified repair,” 44 checks and the deterministic label. The retained Meta replay completed at its recorded 13.0-second clock.
- The original one-action broken-checkout probe now blocks as incomplete; sufficient exploration reaches and reports the actual HTTP 500.

The full local rehearsal used its own services on ports 8760/9760/3760/4760. Job `3a67d350-afaa-4649-9445-3c1d99dfb5b5` verified **44/44** assertions with confirmed cleanup in a six-second rehearsal. It was explicitly **deterministic fallback, not a Meta trial**. The downloaded schema 3 proof and all **12 listed artifact files** passed offline verification; both recorded executions carried verified 512 MiB/no-swap/64-task/100%-CPU cgroup limits. Bundle checksum: `3d52063e108a9b891ca9ae753ca37a06e96107e01ae514b3897cfe2c642ca20d`.

The same storefront first returned `DEPLOYMENT_BLOCKED` for the seeded HTTP 500. After guarded Apply, an independent request returned HTTP 201, zero discount and the expected 3,998-cent total. Re-gating that same URL returned **`SAFE_TO_DEPLOY`, `stop_reason: exhausted`, 45 elements, 12 actions, four screens**. The store was then reverted, its tracked source was confirmed unchanged, and only this rehearsal's services were stopped. It is deliberately seeded again so recording can begin with the failure.

**Keep these filming boundaries:** use the clearly captioned retained Meta clip for Meta generation; this session made no fresh Meta repair trial. Show the local run's actual provider. Do not claim auto-deployment, arbitrary-repository repair, complete exploratory coverage, signed evidence, a VM boundary, or a Meta corpus success rate. F5's mandatory hosted-isolation lane, F6's development dependency advisory, and the remaining F4 hardening are still open production work; they are not silently marked fixed by a successful filming rehearsal.

### Hosted CI follow-up — November 1

The first hosted `Verify` run at `94b99d7` failed in `test_real_node_repository_baseline_repair_and_proof`: Chromium exited before capture with the fixed `No usable sandbox` marker, the runner surfaced `JSONDecodeError`, and the job then misleadingly ended as `artifact_error` because screenshot/trace files were absent. The failure predated the filming changes as well; the earlier `6ddd1f0` Verify run had the same underlying result. This established a browser sandbox startup limitation on the hosted runner, not an artifact-size problem or a failed candidate assertion.

The follow-up change `7c6deec` makes `ProjectRuntime.reconcile` launch the same headless Chromium profile with `chromiumSandbox: true` before advertising runtime readiness. A missing host capability now fails closed with a bounded infrastructure reason before candidate execution or inference. If startup fails later, the runtime owns cleanup and returns an infrastructure failure instead of converting the lost browser process into a missing-artifact verdict. The sandbox flag remains enabled. New red/green regressions cover readiness failure and late spawn, EOF, invalid handshake, and timeout. The safe integration diagnostics record only fixed stderr tags and byte counts.

On Fedora, fresh verification passed `make check` with **1,290 tests** (290 backend/script, 877 orchestrator/CLI, 123 runner), all lint/format/type/provenance/build checks, and `make browser` with **45 tests** (43 Inspector, 2 storefront). The strict isolation subset passed **9 tests, zero skips**, including the real generic Node repair under the sandboxed Chromium profile; this subset overlaps `make check`. These checks were repeated after the hosted-runtime change and are separate from the earlier 44/44 fixture rehearsal.

The hosted CI distinction remains explicit: this preflight discovers the installed runner's sandbox limit and prevents a false repair diagnosis. The current generic integration remains optional on a host that cannot meet its prerequisites, so a green hosted `Verify` may skip that real isolation case. A required, prepared hosted cgroup/Bubblewrap/Chromium lane (F5) is still outstanding. For filming, use the verified Fedora rehearsal and preserve its deterministic-provider caption; do not present the hosted optional skip as successful hosted sandbox execution.

## Original executive decision (baseline)

**FaultLine is a working, carefully constrained repair system with credible kernel containment. It is suitable for a supervised local pilot. Its current deployment verdict and portable proof format need correction before either should independently authorize production changes.**

The strongest engineering is in the separation between patch generation, source policy, isolated execution, external verification, and final resource cleanup. This separation exists in executable code and survived fresh tests. The fixture repair is more than a canned animation: Chromium observes the failure, a candidate runs in Bubblewrap under verified cgroup limits, and independently authored business assertions distinguish a real repair from several symptom-only patches.

The true product boundaries are narrower than parts of the presentation suggest:

- The default demo repairs one registered checkout route. A separate generic project runner supports operator-declared, single-file repairs, but requires explicit reproduction assertions, prepared dependencies, and a compatible offline service.
- URL crawling is heuristic exploration. It does not prove business correctness or complete user-journey coverage. A bounded crawl can currently emit `SAFE_TO_DEPLOY` before reaching a known failing action.
- The controller correctly refuses a successful final job when cleanup fails. However, its evidence bundle is generated earlier and can still say `verified`, with the offline verifier accepting it, after the job becomes `cleanup_failed`.
- The candidate service receives real aggregate kernel limits. The controller, trusted browser, frontend, bridges, parsers, artifact storage, and model client are outside that resource boundary.
- The implementation has useful CI interfaces and workflows. The repository's hosted verification workflow does not require the real isolation tests to execute rather than skip.

| Area | Engineering verdict | Decision implication |
| --- | --- | --- |
| Architecture and code quality | Strong bounded design; substantial tests; growing duplication and monorepo coupling | Continue development without an architectural rewrite |
| Functional repair | Demonstrated on the fixture and a small generic Node integration; broader success depends on the declared oracle | Pilot explicit, reproducible flows; retain normal project CI |
| Bubblewrap and cgroup v2 | Real namespaces, read-only mounts, kernel readback, memory/task enforcement, owned cleanup | Credible local containment; shared-kernel and trusted-process risks remain |
| `gate` | Useful failure detector; deployment label overstates bounded negative evidence | Do not use a green crawl alone as release authorization |
| Evidence | Good corruption detection; incomplete representation of final job guarantees | Consume final job outcome and cleanup state in addition to the bundle |
| CI/CD | Practical machine output and pinned actions; incomplete mandatory isolation coverage | Add a required, prepared Linux isolation lane before expanding reliance |

## Evidence and verification performed

The initial working tree was clean. I read `README.md`, the hackathon brief, project status and handoff, all three requested evaluation reports, the service READMEs, implementation paths named below, and relevant Python and Playwright suites. Existing status documents contain historical counts; fresh output is the basis for this report.

**Environment observed:** Fedora Linux kernel `7.2.13-200.fc44.x86_64`, Python `3.13.16`, Node `v24.21.0`, and uv `0.13.6`.

| Verification | Observed result | What it establishes |
| --- | --- | --- |
| Initial `make check` | Stopped at storefront lint: `eslint: command not found`, Make error 127 | This worktree needed its Node dependencies installed; not an observed application regression |
| `npm ci` in storefront, runner, and Inspector | All three installs completed using existing lockfiles | Prepared this worktree without changing dependency declarations |
| Fresh `make check` | 289 backend/script tests, 799 orchestrator/CLI tests, and 123 runner tests passed: **1,211 total**, no reported skips | Ruff lint/format, strict mypy, fixture/corpus provenance, all three Node checks/builds, and both Python distributions also completed |
| `make browser` | **41 Inspector + 1 storefront tests passed**, exit 0 | Browser UI regressions against built applications; many Inspector tests mock controller responses |
| Required isolation-focused pytest invocation below | **14 passed in 20.20 s**, exit 0, no skips | Includes real Bubblewrap/Chromium fixture execution, actual cgroup memory/task probes, cleanup, log-forgery defenses, and a generic Node service repair |
| Disposable broken-checkout gate probe | One-action budget: exit 0; ten-action budget: exit 1 | Direct evidence of incomplete exploration being promoted to deployment approval |
| Cleanup-failure proof probe | Final job `cleanup_failed`; bundle `verified`; offline consistency check true | Direct evidence of disagreement between final job guarantees and portable proof |
| Storefront `npm audit --json` | Exit 1; 16 moderate affected-package entries, zero high/critical | Dependency hygiene issue described below; separate from the passing build/test result |

The required isolation invocation was:

```bash
FAULTLINE_REQUIRE_ISOLATED_TESTS=1 \
  uv run --project services/repair-orchestrator --python 3.13 --locked pytest \
  services/repair-orchestrator/tests/test_isolated_runtime.py \
  services/repair-orchestrator/tests/test_resource_limits_cgroup.py \
  services/repair-orchestrator/tests/test_project_run.py::test_real_node_repository_baseline_repair_and_proof
```

These 14 tests substantially overlap `make check`; they are not 14 additional unique tests. The generic repair integration uses a **test-double proposer**, not a Meta request. The cleanup-failure probe uses the repository's explicitly simulated runtime with the real worker, SQLite, snapshots, patch policy, and evidence store; it establishes lifecycle semantics, not kernel behavior. No new provider success rate is claimed.

## 1. Code architecture and quality

### Architecture that deserves confidence

The main components have meaningful responsibilities:

| Component | Responsibility and observed strengths | Boundary |
| --- | --- | --- |
| `main.py`, `database.py` | Bearer-authenticated FastAPI control plane, transactional admission, idempotency, durable events and singleton runtime lease | One local controller/serial worker, not a distributed execution scheduler |
| `worker.py` | Bounded lifecycle, cancellation, generation feedback, identity checks, evidence validation and cleanup before final outcome | Trusts the runtime implementation; runtime simulations are test injection |
| `snapshots.py`, `project.py` | Immutable source identity, exact single-file application, source hashes and fresh candidate exports | Demo pinned Git worktrees and generic tracked-source exports use different policies |
| `policy.py` | Bounded exact unified diff plus fixture-specific Python AST restrictions | Policy narrows capabilities; it is not a security sandbox |
| `model_adapter.py` | Structured proposal validation, bounded evidence, explicit provider identity and feedback | Prompt separation reduces instruction confusion; it cannot guarantee model obedience |
| `isolated_runtime.py`, `project_runtime.py` | Kernel namespace execution, aggregate limits, bounded transport and owned cleanup | Host-side verifiers remain trusted and separately exposed |
| `http_regression.py`, browser runner | Independent expectations, observed HTTP/UI behavior, traces and artifact manifests | Finite authored contracts, not general program equivalence |
| `evidence.py`, `proof_bundle.py` | Atomic durable writes, content hashes, bounded artifacts and offline consistency checks | Final lifecycle and containment guarantees are not fully represented in the bundle |

SQLite uses WAL, foreign keys, an in-process reentrant lock, and `BEGIN IMMEDIATE` for cross-connection admission. Job creation, lease reservation, and the first event commit together. A repeated idempotency key returns its original job; changed semantic input conflicts. Transactions do not span awaits or external side effects. Cleanup failure retains quarantine and blocks new jobs. These are useful correctness properties, not merely framework choices. See [database implementation](../../services/repair-orchestrator/app/database.py) and [worker lifecycle](../../services/repair-orchestrator/app/worker.py).

The API uses constant-time Bearer comparison, bounds normal submission bodies, disables schema/docs routes, defaults to loopback, and configures an exact Inspector CORS origin. CORS is not the authentication mechanism. This is a sound local control-plane posture; it is not evidence of tenant isolation, public-service hardening, or a managed secrets system. See [controller construction and authorization](../../services/repair-orchestrator/app/main.py).

The worker checks execution/scenario identity, snapshot generation and digest, runner exit/verdict agreement, duplicate assertion IDs, required assertion coverage, artifact roles and hashes. A runtime cannot return an incomplete assertion list and obtain a green job merely by labeling it passed. The bounded second attempt receives structured rejection findings and starts from the original baseline rather than accumulating partially accepted edits.

### Source policy: distinguish the fixture from generic projects

The fixture policy allows only `apps/buggyshop-backend/app/routes/checkout.py`, with a 16 KiB diff, 32 KiB source/candidate and 100 changed lines. It rejects extra paths, wrong hashes, no-op changes, malformed hunks, NULs, disallowed imports, dynamic/OS capabilities, dunder access, and literal catch-all exception handlers. Python is parsed, never imported by the policy. Hunk recounting repairs derivable metadata and uniquely matching positions while retaining the original proposal; the strict applicability gate still decides acceptance. This is practical defensive engineering. See [patch parser and AST policy](../../services/repair-orchestrator/app/policy.py).

**The generic project policy does not provide that same AST guarantee.** Python receives syntax checking and configured import-delta restrictions. Other languages receive exact scope/size/application checks and runtime execution; `syntax_valid` and `ast_safe` are not universally true. Generic project safety depends much more directly on the sandbox. It would be inaccurate to describe every `faultline run` candidate as having passed the checkout AST allowlist. See [ProjectPatchPolicy](../../services/repair-orchestrator/app/project.py#L240).

### BuggyShop is a credible test fixture, not a production shop

The intentionally seeded route calls `cast(int, discounts.get(coupon_code))`; `cast` performs no runtime conversion. For an absent/blank coupon, the lookup returns `None`, and subtraction raises `TypeError`. The seed remains deliberately broken. Passing tests therefore mean the fixture behaves as specified, not that the seed has become healthy.

Strict Pydantic inputs reject extra fields, non-integer quantities, unknown products, duplicate products, and invalid cart sizes before pricing. Integer-cent expectations, coupon normalization and order readback make the oracle materially stronger than an HTTP-success check. Order storage uses locking and deep copies to avoid accidental cross-test mutation.

Orders are process-local synthetic data. `X-Faultline-Case-Id` selects a caller-provided namespace; it is a test partition, **not authorization**. There is no customer identity, durable commerce database, payment integration, or production transaction guarantee. The intentionally exposed TypeError fingerprint is useful controlled evidence, not a recommended public error contract. See [checkout](../../apps/buggyshop-backend/app/routes/checkout.py), [validation](../../apps/buggyshop-backend/app/schemas.py), [API](../../apps/buggyshop-backend/app/main.py), and [order store](../../apps/buggyshop-backend/app/orders.py).

### Maintainability and distribution constraints

The test investment is substantial and includes negative paths: malformed patches, stale identity, false passes, missing evidence, cancellation, deadlines, restart recovery, resource enforcement and cleanup quarantine. Strict typing is enabled. Neither test count nor successful mypy establishes coverage of every attack path; no coverage percentage or independent escape audit was measured here.

The code is increasingly concentrated: `cli.py` has 2,012 lines, `isolated_runtime.py` 1,480 and `worker.py` 877 at this revision. More consequential than size is semantic duplication: the Inspector ports the Python gate result/prompt logic into TypeScript, and runner contracts mirror Pydantic types manually. Tests pin selected cross-language outputs and snippets, which helps, but changes can still diverge across paths. The bundle discrepancy below is a concrete reason to centralize final verdict semantics before adding more surfaces.

Distribution builds pass, but the orchestrator wheel packages `app/` while depending on checkout-level `shared/`, `fixtures/`, browser assets and pinned Git history. Both Python services also use the top-level package name `app`. The supported delivery is the monorepo with its separate environments; a successful wheel build does not prove an independently installable CLI or that both wheels coexist safely in one environment. See [service packaging](../../services/repair-orchestrator/pyproject.toml) and [runtime boundary](../../services/repair-orchestrator/app/runtime.py), whose opening historical comment also lags the now-implemented browser runtime.

## 2. Functional execution: what actually works

### Three distinct mechanisms

1. **Exploration (`crawl`, `scan`, `gate`).** A deterministic Playwright crawler ranks controls, fills plausible field values, prioritizes shopping actions, follows same-origin navigation and stops on selected failure signals. It catches HTTP 5xx, selected application 400/422 responses, failed requests, uncaught page errors and console errors. The crawl is not an LLM choosing actions. Its default `gate` budget is 25 actions/90 seconds; the underlying standalone crawler defaults differ.
2. **Fixture repair.** The controller admits a registered scenario, exports a pinned seed, reproduces its correlated checkout failure, requests a structured patch or the explicitly labeled deterministic fallback, validates it, and measures a fresh isolated candidate. Successful verification combines the browser journey, 27 HTTP business checks and confirmation evidence; the retained live fixture jobs report 44 assertions. The fixture baseline does not use the generic two-failure admission path.
3. **Generic project repair (`run`).** An operator declares a tracked target and ReproSpec. The runner freezes tracked working-tree bytes, including local edits, launches a fresh isolated service/browser for each baseline, requires two matching completed failures, and only then requests inference. It validates one-file candidates against the declared reproduction and invariant assertions. Original project source is not automatically applied or deployed.

These mechanisms share infrastructure, but they are not interchangeable. A raw crawler breadcrumb list does not automatically become a comprehensive sandbox reproduction or locate a repairable source file. See [crawler](../../tools/browser-runner/src/crawler.ts), [worker admission](../../services/repair-orchestrator/app/worker.py#L404), [project composition](../../services/repair-orchestrator/app/run.py), and [ReproSpec engine](../../services/repair-orchestrator/app/repro.py).

### Verification has meaningful independence, with explicit limits

The fixture's expected catalog prices and order arithmetic are authored outside candidate code. The HTTP oracle checks missing/null/empty/whitespace coupons, normalized codes, mixed carts, quantity limits, invalid input rejection, no stored orders on rejection and successful order readback. It does not import the candidate to compute expected values. The model cannot edit these oracle files through the accepted one-file patch. This catches incorrect repairs that merely stop the original 500. See [HTTP regression oracle](../../services/repair-orchestrator/app/http_regression.py) and [browser assertions](../../tools/browser-runner/src/assertions.ts).

That does not establish correctness for arbitrary inputs or production concurrency. A test-aware patch can still overfit finite assertions. Generic projects receive the assertions their operator declared, not an automatic application-specific equivalent of the fixture's 27 checks. Their snapshot can include ordinary tracked tests/configuration; those files are not accepted patch targets, but they are not necessarily hidden from candidate code.

`setup_command` and `test_command` generated by `init` are metadata; the project runtime does not automatically execute the project's entire unit-test suite or install its dependencies. “Verified candidate” therefore means passing the declared sandbox oracle, with the controller's evidence and cleanup conditions. Normal repository tests remain necessary.

Two fresh baseline failures are a useful flakiness filter, not a proof of determinism. Generic candidate verification is one new execution of the declared oracle. Live HTTP checks use fresh clients but do not reset the external service's database; repeated mutating requests can affect the target twice. The standalone gate is one crawl, not a two-session reproducibility test.

### Confirmed finding F1 — High: bounded exploration is promoted to deployment approval

**Observed:** `crawler.ts` returns `status: "clean"` when the action budget runs out or its crawl deadline expires, as well as when exploration is exhausted. `gate_result` treats any clean report as exit 0 / `SAFE_TO_DEPLOY`. The gate JSON omits the crawler's `stop_reason`, making downstream interpretation harder. Selector/click exceptions can also be skipped while exploration continues. See [crawler stop conditions](../../tools/browser-runner/src/crawler.ts#L992) and [gate decision](../../services/repair-orchestrator/app/cli_crawl.py#L543).

I served a disposable loopback page with one required email input followed by a button whose POST always returns HTTP 500. The same server and page produced:

| Command parameters | Observed result |
| --- | --- |
| `faultline gate URL --max-actions 1 --json` | Exit **0**, `SAFE_TO_DEPLOY`; two elements discovered, only the fill action performed |
| `faultline gate URL --max-actions 10 --json` | Exit **1**, `DEPLOYMENT_BLOCKED`; HTTP 500 on POST `/api/checkout` after the second action |

This is an assurance defect in the release verdict, not a fabricated runner result: the runner accurately found no error in the portion it exercised. Actual runner launch/transport errors fail closed. **Recommended correction:** preserve stop reason and attempted/skipped coverage, distinguish incomplete/inconclusive exploration from a completed required journey, and bind release approval to explicit business assertions. An exploratory clean result can remain useful without independently authorizing deployment.

### Confirmed finding F2 — High for proof consumers: portable proof precedes final cleanup

`RepairWorker._save_bundle` runs after verification passes, before `run_job` performs final cleanup. The compiler sets bundle status from the verification report; it does not include final cleanup, final job outcome, execution resource-limit records, or explicit runtime/provider identity. `tools/verify_bundle.py` validates checksums and the recorded pass fields, not the final controller lifecycle. See [bundle creation](../../services/repair-orchestrator/app/worker.py#L369), [finalization](../../services/repair-orchestrator/app/worker.py#L756), [proof schema](../../services/repair-orchestrator/app/proof_bundle.py#L47), and [offline verifier](../../tools/verify_bundle.py).

Using the existing `harness` fixture with `runtime.cleanup_failed = True`, I ran the real worker and exported its listed artifacts:

```json
{
  "job_outcome": "cleanup_failed",
  "cleanup": "failed",
  "bundle_status": "verified",
  "offline_verifier_consistent": true,
  "lease_quarantined": true
}
```

The controller remains correctly blocked, and apply requires a verified final job with successful cleanup. This is **not a demonstrated controller apply bypass**. It is a significant inconsistency for consumers treating the portable bundle as the final job authority. A separate, tested fixture behavior also allows a bundle compilation exception to be logged while the demo job remains verified; generic project runs require the bundle.

**Recommended correction:** distinguish a verification result from a finalized job, and emit a final checksummed lifecycle envelope after cleanup that binds outcome, runtime kind, kernel-limit observations, source/generation identity, model provenance and artifact manifest. Keep the current explicit statement that checksums detect inconsistency rather than authenticate a provider or defeat a forger who can rewrite and rehash everything.

### Finding F3 — Medium: scan-to-repair binding is route-only

`plan_repair` matches a crawler failure to the controller's registered `METHOD /path`; dispatch then sends the scenario ID, not the crawled origin, source identity or breadcrumb reproduction. A separate site failing at the same path can therefore select the seeded scenario. The sandbox then proves the registered application's repair, not necessarily the scanned site's repair. This is evident in [repair planning and dispatch](../../services/repair-orchestrator/app/cli_crawl.py#L268); it was not exercised against another user's running stack in this review.

The live invariant path has stronger binding checks, including configured origin/fingerprint rules. The CLI scan should similarly bind origin/project identity and recheck the original target before implying that its discovered incident has been resolved. Until then, treat scan dispatch as launching an existing scenario, not automatic localization and repair of an arbitrary pasted website.

### Generalization and retained model evidence

The three earlier reports are prompts for investigation, not authoritative source audits. Their concerns about narrow scope, oracle drift and deployment trust remain valid. Several assertions need correction:

| Earlier evaluation claim or concern | Repository-grounded assessment |
| --- | --- |
| Missing machine-readable CLI/exit contracts | Already implemented: gate JSON/Markdown/agent/CI formats, check JSON and project-run JSON/outcome codes |
| Crawling necessarily requires Bubblewrap/cgroups | False for `gate`/`crawl`; true for isolated repair. `check` still imposes prerequisite presence even without repair |
| No adversarial resource evidence | Real memory-hog, task-hog, environment, kernel-limit and cleanup tests exist and passed here |
| Generic concern that tmpfs itself is unsafe | Not a finding without a mechanism; concrete tmpfs and aggregate bounds are analyzed below |
| Meta evidence consists only of isolated historical replays | Stale: an October 31 ledger records three controller trials, all verified on attempt one; this review made no new model calls |
| Every repair gets the strict checkout AST restrictions | Incorrect for generic project repairs |

The [October 31 Meta ledger](../../docs/evidence/2026-10-31-controller-ledger-meta.md) records **3/3** fixture repairs, 44/44 assertions each, cleanup succeeded, and 10.5-second median wall time. These are retained controller records, not provider-signed attestations or a broad benchmark. The [evaluation record](../../docs/EVALUATION.md) reports DeepSeek's 18/20 over ten authored variants of the same route, with 27 HTTP checks. Its longer provider budgets also differ from the controller default. A full Meta corpus result is not retained there. Neither 3/3 nor 18/20 establishes an arbitrary-repository repair success rate.

The [judge report](eval-panel/report_deepseek_judge.md), [developer report](eval-panel/report_deepseek_user.md), and [systems report](eval-panel/report_llama_systems.md) contain little source-level evidence, and both DeepSeek files end mid-section. Their scores are opinions about a supplied summary, not a measured security grade. I do not adopt their blanket “best practices” or “limited testing” conclusions without a specific code path and evidence.

## 3. Linux Bubblewrap and cgroup v2 isolation

### Threat model and what the boundary actually protects

Assume the candidate code is malicious or broken. The local operator, controller, configured project commands/contracts, installed dependencies, Bubblewrap, systemd, interpreters and kernel remain trusted. The purpose is to prevent ordinary candidate code from modifying host source, inheriting controller/model credentials, reaching arbitrary host networking, or consuming unlimited candidate-service memory/tasks/CPU. It does not make an untrusted multi-tenant public code-execution service safe by itself.

The fixture profile uses `--unshare-all` plus explicit `--unshare-user`, `--die-with-parent`, `--new-session`, `--clearenv` and `--cap-drop ALL`. The explicit user flag is significant: the implementation does not rely on the best-effort behavior of the aggregate flag. Namespace preflight checks that user/network namespace identities differ from the controller's. See [sandbox argv](../../services/repair-orchestrator/app/isolated_runtime.py#L551) and [preflight](../../services/repair-orchestrator/app/isolated_runtime.py#L765).

| Control | Implementation | Precise guarantee/limit |
| --- | --- | --- |
| Filesystem | Read-only application snapshot, interpreter/packages, `/usr` and existing library directories; read-only root, `/dev`, `/proc` | Prevents ordinary writes to mounted source/runtime; `/usr` is a broad trusted tool surface, not a minimal image |
| Private writable storage | Fixture `/tmp` 16 MiB and `/run` 1 MiB tmpfs | Bounded writable scratch; does not impose a retention quota on host-side evidence |
| Generic project scratch | Overrides `/tmp` with 256 MiB tmpfs and copies source there; dependencies mounted read-only | Dev tools may write ephemeral build files; limits and startup assumptions can exclude large applications |
| Environment | Candidate allowlist; only manager addresses go to `systemd-run`, followed by `env -i` before Bubblewrap | Avoids inherited API/control keys, including exposure through Bubblewrap's initial `/proc/1/environ` |
| Network | Private candidate network namespace; inherited abstract Unix listener/relay | Candidate serves trusted verifier traffic without general external connectivity; the intentional socket crosses the boundary |
| Process ownership | Liveness-pipe supervisor, owned process groups, namespace lifetime and scope cleanup | Cancellation/controller death triggers child teardown; failed confirmation quarantines admission |
| Secondary limits | Fixture launcher sets nofile/core/CPU/address-space/process rlimits | Additional fixture defense; generic project launcher does not apply the same rlimits |

Generic snapshots exclude hidden path components, certain credential extensions/names and protected materials, but **the filename filter is not secret discovery**. Ordinary tracked files with other names can still enter the sandbox; an accidentally committed credential can also enter the allowed model target. This review did not inspect actual secrets or demonstrate a leak. The safe operating assumption is an operator-owned, reviewed export, not “arbitrary repository files are automatically secret-free.” See [source path filtering and export](../../services/repair-orchestrator/app/project.py#L23) and [project launcher](../../services/repair-orchestrator/app/project_launcher.py).

### cgroup enforcement is real

Each required candidate launch is placed in an installation/generation-named `systemd-run --user --scope` with:

| Kernel field | Required production value | Interpretation |
| --- | --- | --- |
| `memory.max` | 536,870,912 bytes | 512 MiB aggregate memory limit |
| `memory.swap.max` | 0 | No cgroup swap allowance |
| `pids.max` | 64 | Processes and threads count toward the aggregate task cap |
| `cpu.max` | Quota/period equivalent to 100% | Approximately one CPU of aggregate scheduling bandwidth, not CPU affinity or a wall-clock deadline |
| `memory.oom.group` | 1 | Whole-cgroup OOM treatment |

The runtime reads these values back from cgroup v2 files, validates exact values or equivalent CPU ratios, checks an active scope and supervised process membership, and rejects unverifiable launches. The fixture path rechecks after service readiness. Generic project launches verify scope/membership before the health poll. See [limit parsing and membership](../../services/repair-orchestrator/app/isolated_runtime.py#L194) and [scope verification](../../services/repair-orchestrator/app/isolated_runtime.py#L690).

Preflight goes beyond configuration readback. A 64 MiB/16-task probe scope attempts a 256 MiB child allocation and a 64-thread burst without protective rlimits. Acceptance requires SIGKILL plus that scope's own OOM counters and a task-limit event. The probe uses a different OOM policy so its parent survives to report. Actual production-scope memory and task exhaustion are also tested. **These controls were freshly exercised successfully in this review.** CPU bandwidth is configured/read back, but CPU-throttling effectiveness is not empirically benchmarked by this probe.

Missing tools/delegation or failed enforcement block required runtime readiness. The fixture has an explicit `FAULTLINE_AGGREGATE_LIMITS=disabled` escape hatch, recorded as unverified/disabled rather than secretly claiming quotas. Generic `ProjectRuntime` forces required mode. Thus “always kernel-limited” is accurate only for required, verified execution records; consumers must inspect mode and verification rather than assume them from a green business report.

### Residual exposure and finding F4 — Medium: trusted host processes need their own protection

The following are concrete boundaries, not demonstrated namespace escapes:

- **Shared kernel and syscall surface.** No seccomp filter is supplied to Bubblewrap. Kernel/systemd/Bubblewrap vulnerabilities and resource channels outside the configured controllers remain relevant. There is no disk-I/O bandwidth control, VM boundary or whole-host workload quota.
- **Trusted browser/parser exposure.** HTTPX, uvicorn bridges, Node/Chromium and artifact handling parse candidate-influenced bytes outside the candidate cgroup. In generic projects, the candidate supplies JavaScript/HTML. The project driver explicitly enables Chromium sandboxing, blocks service workers, rejects cross-origin routed requests and closes WebSockets; that is useful defense. It does not put browser CPU/memory or traces into the 512 MiB candidate scope. The fixture/crawler browser launch calls do not explicitly enable `chromiumSandbox` as the generic driver does; audit effective browser process isolation before broad hostile-page use. See [project browser driver](../../services/repair-orchestrator/app/repro_browser.mjs), [fixture oracle launch](../../tools/browser-runner/src/oracle.ts#L536), and [crawler launch](../../tools/browser-runner/src/crawler.ts#L835).
- **Crawler environment differs from isolated repair.** `crawler_service.run_crawl` uses `subprocess.Popen` without a minimal `env`, so its Node runner inherits the caller/controller environment. The isolated runtime deliberately supplies a sanitized environment. This expands the impact of a compromised crawl process; normal page JavaScript reading environment variables was not demonstrated. Use a minimal environment and a separate constrained browser worker for untrusted URLs. See [crawl subprocess](../../services/repair-orchestrator/app/crawler_service.py#L151).
- **Exploration is host-network activity.** Same-origin navigation heuristics are not a network isolation boundary. The standalone crawler has no equivalent of the project driver's origin-routing guard. A remote page can load subresources or invoke requests. Authenticated crawl/probe capabilities intentionally reach operator-selected HTTP targets; exposing controller submission to untrusted users would create a materially different SSRF/host-network threat model.
- **Socket trust is local.** The abstract listener is created in the host network namespace and inherited across the boundary. Random UUID naming prevents casual collisions, not authorized-peer enforcement; there is no peer-credential check in these paths. Other local processes are outside the isolation promise.
- **Evidence custody.** Text/JSON redaction handles configured secrets and selected headers. PNGs and ZIP traces are opaque bytes, not comprehensively scrubbed personal-data archives. Artifact byte caps help per item; accumulated job history still needs an operational retention policy. A downloadable trace should be reviewed before publication.

The right response is targeted hardening of these host-side trust boundaries, not the earlier report's unsupported suggestion that bounded tmpfs is inherently a vulnerability. No kernel escape was attempted or established by this assessment.

## 4. CLI ergonomics and CI/CD readiness

### Command semantics engineers must understand

| Command | Actual behavior | Integration consequence |
| --- | --- | --- |
| `init` | Detects stack/manifests and writes schema-1 `faultline.toml`; does not execute setup or infer a repair target | Review generated command and initial health assertion; scaffold is not a ready repair contract |
| `gate URL` | Runs one heuristic crawl; JSON, Markdown, agent and CI output; 0 clean, 1 defect/runner error, 2 invalid input, 130 interruption | Convenient preview smoke gate; F1 limits its deployment assurance |
| `run [scenario]` | Local durable project worker with isolated service/browser sessions; JSON result; `--detect` avoids inference | Requires explicit tracked target, oracle, offline dependencies and real sandbox readiness |
| `check` | Validates config, then checks declared HTTP invariants in two fresh sessions; 0 all checks/prerequisites pass, 1 failure, argparse usage 2 | Stronger semantic gate when business assertions are supplied; requires sandbox tool presence even without `--repair` |
| `check --repair` | Reproduces an eligible failure again in isolation and proposes a candidate; does not apply source | A repaired sandbox candidate does not turn the failed live check into exit 0 |
| `scan` | Crawl plus offer to dispatch an admitted route scenario and stream its controller job | Requires running engine for repair; F3 limits linkage to the scanned incident |
| `listen`, `diff`, `apply` | Operate on controller jobs; apply is guarded local fixture delivery | Standalone `.faultline/runs` history is not automatically the Inspector/controller history |

Project `run` has deliberately richer exit codes: verified **0**; detected **10**; no failure **11**; unresolved/invalid/unavailable/unexpected **20**; model error **21**; infrastructure/artifact/timeout **30**; cleanup failure **31**; cancellation/interruption **130**. “No failure” being nonzero makes sense for a command whose purpose is producing a repair, but it surprises callers treating `run --detect` as a generic green CI gate. See [outcome mapping](../../services/repair-orchestrator/app/cli.py#L755).

Ergonomics are otherwise thoughtful: TTY-aware color, `NO_COLOR`, plain logs, explicit port controls, clear provider labeling and actionable machine results. The names still conceal different execution models. `doctor` reports tool presence with `runtime_ready: null`; that is deliberately unverified, even though `init`'s next-step wording says to use it to verify containment. Repair preflight is the authority. The existence of Node and cgroup files is not evidence of delegated, enforced scopes.

Setup remains a real boundary. The supported repair host needs Linux namespaces, Bubblewrap and a working systemd user manager/delegated cgroup v2 controls, plus prepared Python/Node dependencies and Chromium. Root `node_modules` and `.venv` mounts, a fixed one-service loopback profile, 256 MiB project scratch and 512 MiB aggregate memory do not automatically accommodate remote databases, payment APIs, authentication providers, multi-service stacks, workspace symlinks or arbitrary package-manager layouts. Recognition by `init` is not execution certification for every recognized framework. No macOS/Windows/WSL portability was tested here.

### Finding F5 — Medium: hosted CI does not require isolation evidence

There are already three useful workflows:

- [Verify](../../.github/workflows/check.yml) installs dependencies and Chromium, uses full Git history, runs `make check` and `make browser`, and uploads browser failure artifacts. Actions are pinned to commit SHAs, permissions are read-only, and the job is time bounded.
- [FaultLine PR gate](../../.github/workflows/faultline-ci.yml) tests a deterministic HTTP service in both passing/failing directions and uploads result JSON. It installs diagnostic sandbox prerequisites but explicitly does not claim delegated enforcement.
- [Pre-flight gate](../../.github/workflows/faultline-gate.yml) checks a configured preview URL, writes a Markdown step summary and propagates failure. With no preview variable, it self-tests healthy/broken fixture servers. That proves gate plumbing, not the application's preview deployment.

The primary hosted check does **not** invoke `make integration` or set `FAULTLINE_REQUIRE_ISOLATED_TESTS=1`. The isolation tests explicitly skip on unsuitable machines unless required. A green hosted build can therefore coexist with unexecuted isolation regressions, even though this workstation passed them. Add a required prepared Linux lane covering the 13 existing isolation-focused cases and the generic Node integration, with missing isolation treated as failure. Keep the ordinary hosted smoke lane for broad contributor accessibility.

The workflows do not prove repository branch-protection settings, a required-check policy or a deployment job's `needs` relationship. Those settings were not queried. The preview variable must also identify the actual revision under review; a static configured URL alone does not bind evidence to a PR commit. The gate workflow currently emits a summary rather than retaining a structured gate artifact on every run. There is no first-class SARIF/JUnit export or automatic PR-comment publisher in the inspected CLI paths; JSON/Markdown already provide useful integration foundations.

### Finding F6 — Medium: dependency audit is outside the green verification signal

Dependency installation reported storefront audit findings. A fresh `npm audit --json` returned **16 moderate affected-package entries**, all in the ESLint/TypeScript lint dependency chain through `minimatch`, and no high/critical entries. This is not 16 distinct demonstrated runtime exploits. Inspector and runner installs reported zero audit findings at installation time. No Python dependency audit or complete software-bill-of-materials review was performed.

The linked [minimatch advisory](https://github.com/advisories/GHSA-g3hv-75wg-m249), retrieved November 1, 2026, describes denial of service from attacker-controlled glob patterns. Runtime exploitability in FaultLine was not established. Treat this as a dependency/CI hygiene finding and review a compatible update; do not follow the audit tool's suggested forced major-version changes blindly. The current `make check` does not gate on these audit results, so its success must not be described as a clean dependency-security audit.

## Recommended delivery order and acceptance criteria

| Priority | Change | Evidence required before closing |
| --- | --- | --- |
| P1 | Correct gate assurance and expose exploration completion | The same two-action broken fixture must not receive deployment approval when only one action or an insufficient time budget is allowed; required journey/assertion coverage is machine-readable |
| P1 | Finalize portable evidence after cleanup | A cleanup-failed job cannot export a bundle that independently claims finalized verified status; offline verification checks the final lifecycle envelope |
| P2 | Bind scan dispatch to the actual project/incident | Two different origins sharing a failing route cannot be represented as one resolved incident without identity binding and original-target remeasurement |
| P2 | Require real sandbox integration in CI | An unsuitable runner fails the isolation lane; real fixture and generic service execution plus OOM/task/cleanup probes pass |
| P2 | Minimize and constrain host-side browser workers | Tests prove no controller/model credentials in crawler worker environment and cover browser resource exhaustion, forbidden network paths and owned teardown |
| P2 | Review dependency and export custody | Compatible lint-dependency remediation is verified; source-export and artifact-retention policies explicitly account for credentials and trace contents |
| P3 | Reduce contract duplication and onboarding ambiguity | Shared/generated verdict contracts, precise `doctor`/`run` semantics, and a tested distribution/runtime support matrix |

Keep the current single-file policy, external assertions, explicit deterministic labeling, required project quotas and cleanup quarantine. Expand supported applications only alongside independent oracles and negative tests for the new boundary. Repeat the Meta corpus evaluation before publishing broader model-effectiveness claims.

**Release posture:** retain the working local demo and supervised candidate workflow. Use the current crawler as additional smoke coverage, keep normal business CI mandatory, and require the final controller outcome plus successful cleanup when consuming repair evidence. The main engineering risk is overinterpreting a successful bounded observation as a complete deployment or security guarantee.
