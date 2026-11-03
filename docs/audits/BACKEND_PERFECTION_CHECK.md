# FaultLine backend perfection check

Date: 2026-11-02. Audited revision: `0288183daf11d92197c5a70b40a07a6725db26a1`.

Follow-up, 2026-11-03: **P01, P02, P03, and P05 have been remediated**, with regression tests and [verification evidence](../evidence/2026-11-03-backend-security-hardening.json). The report below preserves the original audit observations; at that point P04, P06, P07, and P08 remained open.

Follow-up, 2026-11-03 (later): commit `26b032e` fixes **P04** (scope release in `finally`; independent cleanup of every owned resource) and **P07** (whole-root snapshot allowlist), each with regression tests, and **partly** fixes **P06** (project-mode browser scope and bounded artifacts; the fixture-path frontend and runner remain unscoped). No probe re-run for these three has been recorded: `probes/backend_perfection_edges.py` now stops at `snapshot_nonapplication_file` because the P07 fix rejects its planted file. **P08 is resolved by the build dependency and required CI integration changes documented below.** See the [adversarial judging debate](ADVERSARIAL_JUDGING_DEBATE.md#objection-33-your-own-audit-found-eight-backend-isolation-bugs-are-p01p07-really-fixed).

Follow-up, 2026-11-03 (latest): commit `a49c70f` updates the edge probe to record the P07 rejection instead of crashing on it, and its [machine-readable record](../evidence/2026-11-03-backend-perfection-edges.json) now confirms **P04** (`runtime.stop_timeout.scope_release_attempted: true`) and **P07** (`snapshot.extra_file_admitted: false`, `snapshot_nonapplication_file`) by re-run, alongside the P02/P03 persistence and cancellation and P05 policy probes. The extended probe also confirms **P08** (`build.P08.resolved: true`): parallel tests wait for frontend, runner, and Inspector builds, and the integration recipe forces required isolation and selects all four integration files. This uses build markers and command interception; the full integration suite is a separate verification. **P06 remains partly fixed.**

Before publication, the audit branch incorporated `c9ed4e850c4288f8754e6078a9dffb28de01ef39`, an independently completed Inspector fix. The audited backend/orchestrator files and Makefile remained unchanged.

The current checks pass, but the backend execution stack does not meet an unconditional isolation or cleanup guarantee. This review records **eight findings: two High, four Medium, and two Low**. Most urgently, the supported browser fallback still sends WebRTC traffic outside the permitted application origin, and a persistence failure immediately before cleanup prevents teardown from being attempted. No host code execution or kernel escape was demonstrated.

This is an audit and reproducible evidence package. Application code and permanent acceptance tests were not changed. Findings remain open. The probes characterize behavior; their exit status is not a security verdict.

## Scope and evidence

Reviewed `isolated_runtime.py`, `isolated_backend.py`, `process_supervisor.py`, `policy.py`, `snapshots.py`, `worker.py`, `repro.py`, `repro_browser.mjs`, `project_runtime.py`, relevant project configuration/export code, test fixtures, the Makefile, and CI workflows. Backend checks cover fixture validation and storage; the deeper adversarial review concentrates on the requested runtime, parsing, harness, and lifecycle boundaries.

The threat model includes candidate Python/project code and JavaScript served by a project. The controller installation, operator configuration, dependencies, and kernel are trusted initially. A separately labeled snapshot-integrity probe assumes host-side mutation. Lifecycle probes use the existing simulated runtime with real SQLite, policy, evidence, and disposable Git exports; they do not establish that a particular live backend leaked. The WebRTC probe uses the real production driver and installed Chromium, with only temporary loopback HTTP/UDP listeners. No credential files or model endpoints were accessed. No resource-exhaustion attack was attempted.

Machine-readable observations: [verification and probe results](../evidence/2026-11-02-backend-perfection-check.json).

| Verification | Observed result |
| --- | --- |
| Initial `make check` | Exit 2: Python lint, format, types, and provenance passed; frontend failed with `eslint: command not found`. This clean worktree lacked Node dependencies. |
| Locked dependency setup | `npm --prefix <project> ci` succeeded for storefront, browser runner, and Inspector. Lockfiles unchanged. |
| Full `make check`, after setup | **Exit 0**. Ruff and formatting passed; mypy checked 38 backend/shared and 57 orchestrator files; fixture and evaluation provenance passed; storefront, runner, and Inspector built; both Python distributions built. |
| Backend and root pytest, inside `make check` | **324 passed, 23 skipped**, 13.65 s. Skips were optional PowerShell/native Windows coverage on Linux. |
| Orchestrator pytest, inside `make check` | **1,146 passed**, 84.93 s; no skips. |
| Browser-runner checks, inside `make check` | **134 passed**, 57.7 s, plus typecheck/build. |
| Full `make check`, after incorporating the Inspector fix | **Exit 0** again. Runner: **134 passed**, 57.1 s; backend/root: **324 passed, 23 skipped**, 12.11 s; orchestrator: **1,146 passed**, 81.43 s. Lint, format, types, provenance, all application builds, and Python distributions passed. |
| Required isolation/repro/project suite | **49 passed**, 24.14 s; `FAULTLINE_REQUIRE_ISOLATED_TESTS=1`, so unavailable isolation/browser prerequisites would fail. These tests overlap the orchestrator total. |
| Independent backend enforcement preflight | Passed. The 64 MiB probe scope recorded `oom=1`, `oom_kill=1`, child exit `-9`; its 16-task scope recorded `max=1`, allowing 13 probe threads. Environment check passed. |
| Additional audit probes | Confirmed findings below. Both probe files passed Ruff lint and formatting. |

The successful full check still printed Node's cosmetic `NO_COLOR`/`FORCE_COLOR` warning. It was not warning-free output. `make browser` and `make evaluate` are separate targets and were not run in this audit. No native Windows/macOS/WSL result is claimed.

## Findings

| ID | Severity | Finding | Evidence |
| --- | --- | --- | --- |
| P01 | High | Chromium fallback bypasses the WebRTC egress restriction | Reproduced twice with real browser |
| P02 | High | Cleanup-state persistence faults prevent resource teardown | Fault injection with real worker/export paths |
| P03 | Medium | Cancellation arriving during worker cleanup escapes finalization | Controlled cancellation probe |
| P04 | Medium | Backend stop timeout skips independent cgroup release | Fault injection and source trace |
| P05 | Medium | Catch-all policy misses non-assignment bindings and enclosing suppression | AST and full patch validation probes |
| P06 | Medium | Candidate quotas do not bound host browser work or artifact production | Live cgroup observation and source trace |
| P07 | Low | Fixture snapshot identity does not cover the entire mounted tree | Synthetic extra-file probe |
| P08 | Low | Resolved: CI requires all four integration files; tests depend on frontend builds | Makefile/workflow review |

### P01 — Browser fallback retains a network-policy hole

Code: [`repro_browser.mjs:8`](../../services/repair-orchestrator/app/repro_browser.mjs#L8), fallback at line 18, HTTP origin routing at line 27; host launch at [`project_runtime.py:365`](../../services/repair-orchestrator/app/project_runtime.py#L365). Coverage: [`test_repro_browser.py`](../../services/repair-orchestrator/tests/test_repro_browser.py).

The preferred `channel: 'chromium'` launch and its fallback both request Chromium sandboxing and the same WebRTC flags. Nevertheless, forcing only the preferred launch to fail causes the unchanged driver to use a real fallback browser that sends STUN UDP to a separate host loopback port. The origin router does not prevent that traffic.

Observed in two independent runs: preferred browser **0 UDP bytes**; forced fallback **20 UDP bytes**. Both navigations completed and both pages reported `rtc-started`. This is a demonstrated origin-boundary violation; no inference about arbitrary UDP payload control, Internet reachability, or data exfiltration is needed. The preferred result establishes only this probe's outcome for the installed build, not complete network isolation.

The existing fallback test substitutes a fake Playwright module and checks option values. The real WebRTC regression runs the normal launch path; it does not force a usable fallback. Thus all 49 required tests pass while the fallback leak remains.

Recommendation: fail closed when the preferred browser is unavailable until the fallback passes equivalent live network tests; ultimately enforce browser egress below application routing. Acceptance: independently observe zero listener hits for both real launch paths, including UDP, redirects, subresources, and WebSockets. This narrows the earlier systems audit's S-02: the preferred profile improved, but fallback behavior remains unsafe.

### P02 — Database writes can prevent cleanup from starting

Code: [`worker.py:871`](../../services/repair-orchestrator/app/worker.py#L871), outer supervision at line 225. Coverage: [`test_worker_lifecycle.py:88`](../../services/repair-orchestrator/tests/test_worker_lifecycle.py#L88).

`run_job()` writes the cleanup transition and `cleanup_status=in_progress` before entering the teardown `try`. Injecting `sqlite3.OperationalError` independently at either write causes the method to raise before calling runtime or snapshot cleanup. The normal workflow had already prepared and activated the simulated runtime, and real snapshot/worktree directories remained. The probe then restored the database methods and explicitly removed its owned resources.

Dispatcher supervision now catches such exceptions and quarantines admission; that is a real improvement over the earlier code audit's F02. It does not dispose of the already active generation. The direct `run_job()` probe itself leaves the lease unquarantined; the dispatcher supplies quarantine in the normal background path. No verified proof is published, and the active lease still blocks ordinary replacement admission.

Impact: a storage failure can leave candidate/helper resources running until reset, restart, or explicit cleanup, even though teardown does not require successfully recording a stage first.

Recommendation: put actual disposal in a `finally` boundary that survives persistence failures, using ownership identifiers captured before work begins. Persist cleanup attempts and quarantine on a best-effort basis. Add fault cases specifically at the two cleanup-entry writes, asserting teardown was attempted and admission remains blocked when confirmation is unavailable.

### P03 — Late cancellation interrupts cleanup and terminal bookkeeping

Code: [`worker.py:846`](../../services/repair-orchestrator/app/worker.py#L846), cleanup at lines 874–931, shutdown at line 191.

Cancellation during `_workflow()` is classified before cleanup. Cancellation first delivered while `runtime.cleanup()` is awaited takes a different path: the cleanup handler catches `Exception`, which does not catch `asyncio.CancelledError`. A controlled probe cancelled at that await and observed a job left at `cleanup`, `cleanup_status=in_progress`, `outcome=null`, with no quarantine flag. The active lease remains held, so this is not demonstrated concurrent admission or false GREEN.

This can occur when shutdown arrives after work has already entered cleanup; a repeated shutdown cancellation adds another exposure. `stop()` suppresses the propagated cancellation and can return without cleanup confirmation. `ProjectRuntime._session()` has a more careful shield-and-await pattern at lines 391–397, but that does not protect every worker cleanup path.

Recommendation: own and await cleanup independently of incoming job cancellation, including repeated cancellation; withhold a successful terminal state and persist quarantine if confirmation fails. Test first cancellation in cleanup, a second cancellation during shielded teardown, and shutdown concurrent with finalization.

### P04 — A process-stop failure bypasses scope and handle cleanup

Code: [`isolated_runtime.py:1069`](../../services/repair-orchestrator/app/isolated_runtime.py#L1069), session release at line 1103, generation cleanup at line 1452; [`project_runtime.py:332`](../../services/repair-orchestrator/app/project_runtime.py#L332).

`_stop_backend()` awaits `backend.process.stop()` before `release_scope()`. A controlled stop timeout confirmed that scope release was never attempted. `_release_session()` similarly closes listener/client handles only after stopping succeeds. Generation cleanup stops runner/frontend sequentially before reaching the backend, bridge, sockets, or directory: an early failure skips independent later resources.

The fixture generation stays registered, so its ownership is recoverable. One-shot `backend_session()` resources live only in a local variable and are not registered in `generations`; recovery is weaker there. Project sessions retain their registry entry on teardown error, but an early browser-stop error can still bypass bridge closure before the backend-release `finally` executes.

Recommendation: attempt independent cleanup actions even when one fails, retain every unconfirmed ownership record, and use the cgroup kill/release path as an independent backstop. Close releasable local handles in `finally`. Add stop-timeout tests asserting that scope release and socket/client cleanup were attempted. This confirms availability edges already identified in the earlier systems audit rather than demonstrating a new namespace escape.

### P05 — Catch-all policy still has binding and control-flow gaps

Code: [`policy.py:265`](../../services/repair-orchestrator/app/policy.py#L265), trusted-name resolution at line 316, re-raise check at line 323. Coverage: [`test_policy.py:313`](../../services/repair-orchestrator/tests/test_policy.py#L313).

Alias tracking handles ordinary assignment, annotated assignment, assignment expressions, and matching tuple/list unpacking. It does not account for every binding form. These examples both return `(True, True, None)` from `validate_ast()`:

```python
for ValueError in [Exception]:
    try:
        1 / 0
    except ValueError:
        pass
```

```python
def f(ValueError=Exception):
    try:
        1 / 0
    except ValueError:
        pass
f()
```

Appending the second example to the existing source also passed the full byte-bounded, exact-diff `PatchPolicy.validate()` gate. No candidate execution was needed to establish admission. A third admitted shape re-raises inside `except Exception`, then suppresses the exception with an enclosing `finally: return`.

Recommendation: conservatively account for parameter, loop, comprehension, pattern, definition, and other bindings that shadow trusted exception names; reject unproven handler types. Decide explicitly whether enclosing exception suppression belongs to the policy contract and test it. Ordinary alias rejection and compiler-level syntax checks introduced after the previous audit are working. This is a residual policy-filter defect, not a sandbox bypass or proof of a false business-verification result.

### P06 — Host browser execution remains outside candidate accounting

Code: [`project_runtime.py:365`](../../services/repair-orchestrator/app/project_runtime.py#L365), [`repro_browser.mjs:67`](../../services/repair-orchestrator/app/repro_browser.mjs#L67), serialization limit at line 84, and [`isolated_runtime.py:1268`](../../services/repair-orchestrator/app/isolated_runtime.py#L1268).

Both live browser probes observed the driver in the controller's cgroup, outside the named FaultLine candidate scope. Candidate-served JavaScript therefore causes work in host helpers outside the candidate's verified 512 MiB/64-task/one-CPU scope. The enclosing host environment may have its own limits; FaultLine does not verify a browser/job-wide budget here.

The driver builds text/screenshot measurements and JSON-serializes them before checking its one-MiB measurement limit. Traces/screenshots are also produced before final artifact size checks. Those checks bound accepted evidence, not peak generation memory or disk use. HTTP bodies through the production UDS bridge have a separate streaming cap and should not be conflated with this problem.

Recommendation: place browser/frontend/helper trees in separately budgeted job scopes and bound temporary artifact storage during production. Test bounded hostile DOM/script workloads and trace growth. No memory/disk exhaustion was performed in this review. This reconfirms earlier systems finding S-05.

### P07 — Snapshot verification hashes less than the mounted root

Code: [`isolated_runtime.py:1108`](../../services/repair-orchestrator/app/isolated_runtime.py#L1108), verification at line 1149, whole-root bind at line 602; export construction in [`snapshots.py`](../../services/repair-orchestrator/app/snapshots.py).

Adding an innocuous `unhashed-extra.txt` at an otherwise valid fixture snapshot root did not change `_verify_snapshot()`'s outcome. It hashes the backend application subtree and target, while `_sandbox()` mounts the entire snapshot root. `_verify_application()` used by backend-only sessions performs a stricter whole-tree file allowlist.

This requires mutation or misuse on the trusted host side. The normal snapshot manager exports only approved application files, and the candidate's mount is read-only; this is not a demonstrated candidate-controlled file disclosure. Recommendation: apply the whole-tree allowlist before mounting, or mount exactly the attested subtree. Test extra root/sibling files and unusual filesystem objects.

### P08 — Required coverage and build ordering gaps (resolved)

Code: [`Makefile:12`](../../Makefile#L12), integration target at line 17; [Verify workflow](../../.github/workflows/check.yml), [PR gate](../../.github/workflows/faultline-ci.yml).

Resolved, 2026-11-03: `Makefile` now encodes the dependency edge `test: frontend runner inspector`, so `make -j check` waits for all three builds before starting Python tests. Previously these targets were sibling prerequisites of `check`, which only established ordering for serial make.

`make integration` sets `FAULTLINE_REQUIRE_ISOLATED_TESTS=1` and explicitly runs all four required files: `test_isolated_runtime.py`, `test_resource_limits_cgroup.py`, `test_repro_browser.py`, and `test_project_run.py`. Missing isolation/browser prerequisites therefore fail the required tests instead of silently skipping them.

The Verify workflow installs bubblewrap prerequisites on Ubuntu and runs `make integration` after `make check` and `make browser`, with `FAULTLINE_REQUIRE_ISOLATED_TESTS: 1` in the integration step environment. The PR gate also sets this variable at job scope. Installing bubblewrap alone does not establish delegated cgroup readiness; the required integration tests enforce live runtime prerequisites. Native platform checks remain separate.

Verification: `make check` exited 0 (134 runner tests passed; backend/root: 328 passed, 23 skipped; orchestrator: 1,356 passed, 3 skipped; all builds passed). `make integration` exited 0 with **77 passed, no skips** across the four required files. A temporary harness retaining the Makefile dependency graph reproduced tests starting before build completion under `make -j8 check` before the fix and passed after the dependency edge was added.

## Controls and edge cases that held

- **Isolation:** the actual bubblewrap profile and required integration suite passed. Source review confirms explicit user/all namespace separation, dropped capabilities, cleared environment, read-only source/interpreter/dependencies/root, and bounded writable tmpfs. The backend receives an owned listening FD instead of writable host socket storage. No missing-prerequisite host-execution fallback was found in these reviewed paths.
- **Resource admission:** required mode reads back live kernel limits and membership, probes memory/task enforcement, and withholds readiness on failure. Disabled mode is explicit and unverified; project runtime requires limits. Scope removal is targeted and checked for absence, including failed and empty active units. CPU quota is configured/read back, not behaviorally stress-probed.
- **Patch containment:** exact file headers, no extra files/rename/mode metadata, byte and changed-line bounds, hunk coordinates/counts, seeded context, no-op detection, stale base rejection, AST parse/compile, import-symbol restrictions, private attribute/pattern checks, and staged-index path checks remain meaningful controls. Recounting only repairs derivable metadata; Git independently checks and applies the bounded patch to a fresh seed.
- **AST resource edge:** a 1,200-link alias chain on one source line raises `RecursionError` from the direct `validate_ast()` helper. Its 12,436-byte full patch is rejected by `PatchPolicy.validate()`, which catches that error. This fails closed. The helper and public wrapper have different error contracts, and the wrapper classifies the result as `syntax_valid=false` even though the source is syntactically valid.
- **Reproduction:** unique ordered step IDs, earlier measured assertion sources, bounded step counts/timeouts, relative service paths, exactly one assertion matcher, explicit-null versus omitted-body handling, and boolean-versus-number comparisons are tested. Two fresh sessions must reproduce the same failure before generic project repair. Errors, timeouts, nondeterminism, fingerprint mismatch, and cleanup failure cannot authorize repair through `ReproEngine`.
- **Regex execution:** matching now runs in a disposable interpreter with a 250 ms deadline and kill/reap handling. The earlier synchronous matching defect is not present in the reviewed path. This review did not exhaust regex compilation/resource cases or every process-creation cancellation interleaving.
- **Transport and evidence:** UDS responses are capped while streaming and compressed responses are rejected before body decoding. Reports and evidence are checked for execution identity, verdict/exit agreement, required roles, size, containment, and checksum. Generic project evidence is checked by the worker before successful publication. Final proof registration is transactional and follows confirmed cleanup; injected failures covered by the suite do not manufacture GREEN.
- **Supervision:** normal worker death and scan/claim/finish persistence faults now block admission via health/quarantine. Existing tests cover cancellation during work, queued cancellation, restart, serial dispatch, artifact failures, and final-proof rollback. These improvements do not close P02/P03.
- **Deadlines:** `_bounded()` cancels then gathers an operation; a synthetic coroutine that delays acknowledging cancellation kept a 10 ms call pending after another 50 ms. This preserves task ownership but requires cooperative cancellation. Synchronous SQLite/filesystem work also cannot be preempted by an asyncio timeout. Stage/overall budgets are not independent hard process deadlines for arbitrary trusted implementations.
- **Supervisor boundary:** liveness EOF and ordinary real-Chromium cancellation passed. Process-group supervision alone does not prove cleanup of detached host descendants, direct supervisor signal death, or adoption/reaping of grandchildren. Those earlier systems-audit findings were not comprehensively rerun here; candidate PID namespaces/cgroups provide additional backstops absent from host helpers.
- **Host assumptions:** local abstract UDS/loopback peers are not a tenant-authentication boundary; no seccomp/VM isolation is claimed. Live dependency directories are trusted mounts outside source snapshot identity. Same-installation competing startup owners, port reservation races, slow body streaming, storage retention, and native-platform lifecycle guarantees remain areas described by the earlier audits, not closed by this passing suite.

## Reproduce and extend

Run from the repository root after normal dependency/browser setup:

```bash
make check
FAULTLINE_REQUIRE_ISOLATED_TESTS=1 uv run --project services/repair-orchestrator --python 3.13 --locked pytest \
  services/repair-orchestrator/tests/test_isolated_runtime.py \
  services/repair-orchestrator/tests/test_resource_limits_cgroup.py \
  services/repair-orchestrator/tests/test_repro_browser.py \
  services/repair-orchestrator/tests/test_project_run.py
uv run --project services/repair-orchestrator --python 3.13 --locked python docs/audits/probes/backend_perfection_edges.py
uv run --project services/repair-orchestrator --python 3.13 --locked python docs/audits/probes/backend_perfection_browser.py
```

The [edge probe](probes/backend_perfection_edges.py) uses temporary Git exports and existing simulated-runtime support, restores injected methods, and cleans its own exports. It never executes the AST sample candidates. The [browser probe](probes/backend_perfection_browser.py) wraps only browser selection to force the production fallback; it uses the actual driver, page execution, and loopback listeners and stops its managed processes. Expected observed defects are reported as data, so these scripts should be converted into failing acceptance tests when fixes are implemented.

Recommended implementation order: close P01; make cleanup independent of database availability and incoming cancellation (P02–P04); close P05 and require those regressions in CI; then establish job-wide accounting and attest the complete mount contents. Preserve the existing independent oracle, immutable evidence, and quarantine protections throughout.

Earlier context: [systems audit](SYSTEMS_AUDIT_CODEX.md) and [code audit](CODE_AUDIT_CODEX.md). Their findings describe earlier revisions; this report distinguishes mitigated paths, residual variants, and controls verified at the revision above.
