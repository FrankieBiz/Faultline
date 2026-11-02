# FaultLine architecture and code quality audit

Audit date: November 2, 2026. Source revision: `23ea6f6c7e61723ffac6a28a7af79a61878a0a14`. Report-only updates from `main` were incorporated before committing; audited application code remained unchanged. This report records an independent source review and local execution; recommendations are not implemented by this commit.

## Assessment

The repair pipeline has substantial, tested safeguards: transactional admission, exact diff application, bounded model requests, separate trusted oracles, process supervision, kernel limit verification, and proof publication after cleanup. The seeded missing-coupon exception is an intentional fixture, not an accidental production defect.

Passing the existing checks does not cover several important failure modes. The highest-priority problems are synchronous regex evaluation defeating controller deadlines and an unsupervised worker task that can die while readiness continues to advertise availability. Delivery also needs stronger source identity checks and serialization. Several smaller contract mismatches are demonstrable despite strict mypy passing.

There are **16 findings: 2 High, 9 Medium, 5 Low; no Critical finding established**. Severity reflects impact and the conditions needed to trigger it, not the number of lines involved. This is not a sandbox-escape certification or a claim that the listed findings are exhaustive.

## Scope and method

| Area | Reviewed responsibilities |
| --- | --- |
| `apps/buggyshop-backend` | FastAPI middleware and routes, checkout validation, catalog copies, namespace order storage, healthy/seeded tests |
| `services/repair-orchestrator/app` | API/lifespan, SQLite transactions and leases, worker stages, deadlines/cancellation, snapshots, runtime supervision and cleanup, delivery, evidence/proof compilation |
| CLI | Root `faultline` shell launcher; `cli.py`, `cli_check.py`, `cli_crawl.py`, `cli_init.py`, `cli_demo.py`, project runner composition |
| Parsing and contracts | Unified diffs, AST/import policy, ReproSpec/assertions, Pydantic contracts, TOML loaders, provider proposal decoding |
| Tests and tooling | Backend/root/orchestrator pytest suites, simulated versus real runtime boundaries, Makefile, package build configuration and CI verification workflow |
| Adjacent service code | Evaluation loop, public live-demo admission/accounting, retained minimizer library |

`faultline` is a root executable file, not a `faultline/` Python package. Most CLI implementation is in the orchestrator's `app` package. Frontend and browser-runner builds were used as integration prerequisites; their UI and JavaScript implementation were not comprehensively audited here.

Findings below distinguish **reproduced** behavior from **source-traced** risks. Focused probes used temporary directories, in-memory or temporary SQLite databases, mock HTTP transports, synthetic secret strings, and bounded child processes. They did not modify application source, contact a model provider, or inspect credential files. No new permanent tests were added: this task produces a report, not implementation changes.

## Verification record

Commands ran with the repository's locked Python 3.13 environments, using CPython 3.13.16 and pytest 9.1.1.

| Command | Observed result |
| --- | --- |
| `make lint` | Exit 0. Both Ruff checks passed; format checks reported 52 backend/shared/root files and 57 orchestrator files already formatted. |
| `make typecheck` | Exit 0. `Success: no issues found in 38 source files`, then `56 source files`. |
| Initial `make test`, before runner build | Exit 2 at Make level: first pytest invocation had **3 failed, 321 passed, 23 skipped in 10.00s**. All three failures were platform browser smoke tests reporting `runner_unavailable` because `tools/browser-runner/dist/cli.js` was absent. The orchestrator suite was not reached. |
| `npm --prefix tools/browser-runner ci` and `npm --prefix tools/browser-runner run build` | Exit 0. Installed six packages; TypeScript runner build succeeded. |
| Second `make test`, after runner build | Exit 0. Backend/root: **324 passed, 23 skipped in 12.03s**. Orchestrator: **1004 passed, 4 skipped in 67.33s**. Four skipped cases needed the full storefront runtime. |
| `make build` | Exit 0. Both Python source distributions and wheels built successfully. See F08 for the separate installed-package import failure. |
| `npm --prefix apps/buggyshop-frontend ci` and `npm --prefix apps/buggyshop-frontend run build` | Exit 0. Optimized Next.js build succeeded. Install also reported **16 moderate npm vulnerabilities**; these are untriaged package-manager diagnostics outside this Python audit, not 16 independently verified findings. |
| Final `make test`, after runner and storefront builds | Exit 0. Backend/root: **324 passed, 23 skipped in 11.50s**. Orchestrator: **1008 passed in 72.45s**. Total: **1,332 passed, 23 skipped**. All four previously skipped orchestrator integration cases executed successfully. |

The final skips are 21 optional PowerShell bootstrap cases and two native Windows demo/process-tree cases on Fedora. The real Node-project repair/proof test and the full fixture runtime/cgroup tests passed. No claim is made about Windows/PowerShell behavior from this Linux run.

The initial failure exposes a reproducibility issue in the developer entry point: [`Makefile:33`](../../Makefile#L33) defines `test` without runner/frontend prerequisites even though platform smoke tests require a compiled runner. `make check` establishes the intended build order. Prefer either an explicit `test` preflight with a clear setup error, or separate unit and integration targets; do not silently interpret unavailable integration machinery as test coverage.

## Findings index

| ID | Severity | Finding | Evidence |
| --- | --- | --- | --- |
| F01 | High | Regex assertions can block the event loop beyond all async deadlines | Reproduced |
| F02 | High | A single uncaught persistence fault can permanently stop the worker without changing readiness | Reproduced + source trace |
| F03 | Medium | Startup reconciliation lacks exclusive controller ownership of the data directory | Reproduced |
| F04 | Medium | Delivery does not bind writes to verified source hashes and can overwrite intervening edits | Reproduced |
| F05 | Medium | Live HTTP probes silently discard declared request headers | Reproduced |
| F06 | Medium | Assertion clipping before redaction exposes partial secret values | Reproduced with synthetic data |
| F07 | Medium | Catch-all AST policy is bypassed by ordinary exception aliases | Reproduced |
| F08 | Medium | Orchestrator wheels build but omit required repository-local packages | Reproduced |
| F09 | Medium | Divergent config loaders permit malformed input to escape as uncaught exceptions | Reproduced |
| F10 | Medium | Synchronous storage operations block the shared async control plane | Reproduced + source trace |
| F11 | Medium | Project dependency mounts are not part of the immutable execution identity | Source-traced |
| F12 | Low | CLI prints incorrect sandbox limits from the actual readiness response | Reproduced |
| F13 | Low | Canonical schema accepts attempt counts that persistence rejects; diagnostic types drift | Reproduced + source trace |
| F14 | Low | Minimizer iteration budget and reported call count are incorrect | Reproduced; dormant library |
| F15 | Low | Storage retention and linear scans create avoidable growth costs | Source-traced; workload-dependent |
| F16 | Low | Large CLI/controller modules, duplicate adapters, and stale contracts increase maintenance risk | Source-traced |

### F01 — High: regex assertions defeat async deadlines

References: [`repro.py:156`](../../services/repair-orchestrator/app/repro.py#L156), [`repro.py:280`](../../services/repair-orchestrator/app/repro.py#L280), [`repro.py:347`](../../services/repair-orchestrator/app/repro.py#L347).

`AssertionCheck` checks only whether a regex compiles. `evaluate_assertion()` calls Python `re.search()` synchronously on measured, potentially untrusted service text. Both the step timeout and overall timeout use `asyncio.timeout`; neither can interrupt synchronous work that does not yield. The regex executes in the trusted controller, outside candidate cgroups.

**Reproduction:** a session returned `"a" * 30 + "!"`; its assertion used `(a+)+$`. With a 1 ms spec timeout and an additional 10 ms `asyncio.wait_for`, the child still ran after 800 ms and had to be terminated by the probe's external subprocess timeout. The input is much smaller than the live response cap. An ordinary operator-authored pathological pattern plus a service response is enough; arbitrary source execution is unnecessary.

**Impact:** a live check can stop health responses, cancellation handling, and job progress in that controller process. Advertised deadlines do not bound this operation.

**Recommendation:** use a bounded, non-backtracking matcher with a documented supported syntax, or evaluate patterns in a separately supervised process with a hard deadline. Moving `re.search` to a thread alone does not provide a reliable cancellation boundary. Add a process-bounded regression that verifies timeout, controller responsiveness, and cleanup while a pathological assertion is evaluated.

### F02 — High: worker failure is neither supervised nor reflected in readiness

References: [`worker.py:158`](../../services/repair-orchestrator/app/worker.py#L158), [`worker.py:184`](../../services/repair-orchestrator/app/worker.py#L184), [`worker.py:779`](../../services/repair-orchestrator/app/worker.py#L779), [`worker.py:826`](../../services/repair-orchestrator/app/worker.py#L826), [`main.py:358`](../../services/repair-orchestrator/app/main.py#L358).

`start()` creates one task for `_loop()`. Its scan of `unfinished_jobs()` and dispatch to `run_job()` have no outer failure handler or task monitor. `claim_job()` and multiple cleanup/finalization database operations also sit outside the workflow's exception classification. SQLite lock/disk errors or invalid persisted records can therefore end the task. `/readiness` considers runtime readiness, probe availability, and quarantine, but not whether the worker task is alive.

**Reproduction:** injecting one `sqlite3.OperationalError` from `unfinished_jobs()` left `_loop`'s task `done=True` with that exception. Source inspection confirms no restart or readiness invalidation. A failure before admission can leave the next accepted job queued indefinitely; a failure during work can leave its lease held. Shutdown can also re-raise the task's exception before subsequent lifespan resource closures execute.

**Recommendation:** make worker liveness an explicit controller health condition, reject submissions when its task has failed, and supervise failure with a deliberate recovery policy. Retry only known transient database operations; ambiguous runtime/cleanup failures should preserve quarantine and require reconciliation. Ensure model/database closure runs even if `worker.stop()` raises. Test scan failure, claim failure, cleanup persistence failure, readiness, and admission after task death.

### F03 — Medium: a second controller can reconcile away a live job

References: [`main.py:236`](../../services/repair-orchestrator/app/main.py#L236), [`worker.py:888`](../../services/repair-orchestrator/app/worker.py#L888), [`isolated_runtime.py:877`](../../services/repair-orchestrator/app/isolated_runtime.py#L877), [`run.py:88`](../../services/repair-orchestrator/app/run.py#L88).

Startup assumes that every unfinished job in the shared SQLite database belongs to a dead controller. There is no process-level ownership lock in the HTTP controller lifespan. Transactional job admission prevents concurrent claims; it does not establish that the previous controller is dead. The standalone project runner already uses `.run.lock`, demonstrating an existing approach, but the API does not share that protection.

**Reproduction:** connection A created and claimed a job in a temporary database. A worker using connection B, with a ready no-resource runtime, called `reconcile()`. A's job became `interrupted` and its lease owner became `None` even though A was still alive. With a real runtime, installation-wide leftover-scope cleanup also targets that installation's scopes.

**Impact condition:** two controllers or a controller and a project runner use the same data directory. The normal one-controller deployment avoids this; `workers=1` in one Uvicorn invocation does not prevent a second invocation on another port or during restart overlap.

**Recommendation:** acquire one common, nonblocking installation lock before opening/reconciling persistent state, hold it for the entire controller lifetime, and use the same ownership mechanism in all runner entry points. Test concurrent startup and restart overlap across actual processes, including lock release after owner death.

### F04 — Medium: delivery loses provenance and can overwrite local edits

References: [`cli.py:486`](../../services/repair-orchestrator/app/cli.py#L486), [`cli.py:569`](../../services/repair-orchestrator/app/cli.py#L569), [`live_store.py:62`](../../services/repair-orchestrator/app/live_store.py#L62), [`live_store.py:94`](../../services/repair-orchestrator/app/live_store.py#L94), [`main.py:569`](../../services/repair-orchestrator/app/main.py#L569).

The CLI delivery helper checks a job's terminal outcome, extracts its diff, then validates the diff against the file currently on disk. It does not supply the verified base hash to the policy or compare the resulting bytes with the verified target hash. Exact hunk coordinates reject shifted lines, but unchanged line coordinates do not establish whole-file identity.

**Reproduction:** changing the seeded file's earlier `unit_price_cents` expression to `1`, without changing line count, still allowed the verified coupon diff to apply. The helper returned success while the delivered hash differed from the attempt's recorded target hash. Separately, injecting an editor change after `original_source` was read and before validation completed caused the later `write_text()` to discard that edit.

The API's `live_store.apply()` adds a seeded-file check, but that check is separate from the write. CLI and API operations share no mutation lock, use a single backup filename, and write source directly rather than by durable atomic replacement. Marker persistence happens after the source write and can fail independently. Initial source/backup I/O is outside the helper's `try`, and rollback I/O can itself raise.

**Recommendation:** use one delivery service for CLI and API, validate baseline and candidate hashes against the verified attempt, serialize apply/revert operations with a file lock, and recheck the expected source immediately before replacement. Use unique backups and a flushed temporary file plus atomic rename. A cooperative lock cannot stop arbitrary editor writes: detect conflicts where possible and document that residual boundary. Treat marker/write failures as recoverable delivery states. Test divergent same-line bases, intervening writes, concurrent revert, and storage failures using temporary files.

### F05 — Medium: HTTP live checks discard ReproSpec headers

References: [`repro.py:99`](../../services/repair-orchestrator/app/repro.py#L99), [`probes.py:287`](../../services/repair-orchestrator/app/probes.py#L287), [`repro.py:470`](../../services/repair-orchestrator/app/repro.py#L470).

`RequestStep.headers` is a declared part of the reproduction. `HttpProbeSession.perform()` constructs correlation, Accept, and optional Content-Type headers but never merges `step.headers`. The Playwright adapter uses the declared headers, so the same reproduction means different requests in live HTTP admission and sandbox verification.

**Reproduction:** a mock transport receiving a `RequestStep(headers={"X-Audit-Marker": "sentinel"})` observed no `x-audit-marker` header.

**Impact:** tenant, API-version, authorization, or content-negotiation scenarios can report failures for the wrong reason or check an unintended response branch. In particular, live admission can differ from the repair oracle.

**Recommendation:** define header precedence once, reserve the controller's correlation header explicitly, and apply the remaining declared headers consistently across transports. Verify actual received headers, body semantics, and reserved-header handling rather than only mocking return values.

### F06 — Medium: clipping before redaction leaks secret fragments

References: [`probes.py:491`](../../services/repair-orchestrator/app/probes.py#L491), [`evidence.py:50`](../../services/repair-orchestrator/app/evidence.py#L50), [`main.py:435`](../../services/repair-orchestrator/app/main.py#L435).

Assertion summaries call `redact(item.expected[:240])` and `redact(item.observed[:240])`. If clipping splits a configured secret, exact replacement no longer recognizes it. The response-excerpt path in the same function correctly redacts before clipping.

**Reproduction:** observed text consisting of 230 `x` characters followed by the synthetic secret `SYNTHETIC_SECRET_VALUE` retained the suffix `SYNTHETIC_` in the API-visible assertion summary. No real credential was used. These summaries are returned to authenticated operators and persisted in live check records.

**Recommendation:** consistently apply `redact(value)[:limit]`, including header-style redaction, before any presentation truncation. Test every cut position inside synthetic secrets in expected/observed values. Review binary trace handling separately: `EvidenceStore` does not redact ZIP/PNG contents, so the text-redaction contract should not be described as covering every artifact byte.

### F07 — Medium: catch-all rejection is spelling-based; syntax status is also too optimistic

References: [`policy.py:259`](../../services/repair-orchestrator/app/policy.py#L259), [`policy.py:267`](../../services/repair-orchestrator/app/policy.py#L267), [`project.py:272`](../../services/repair-orchestrator/app/project.py#L272), [`test_policy.py:107`](../../services/repair-orchestrator/tests/test_policy.py#L107).

`_catches_everything()` rejects only bare handlers and names literally spelled `Exception` or `BaseException`. Ordinary assignments are not tracked.

**Reproduction:** `validate_ast("AnyError = Exception\ntry:\n    1 / 0\nexcept AnyError:\n    pass\n")` returned `(True, True, None)`. The claimed ban on catch-all suppression is therefore bypassed without forbidden imports or dunder access. This does not establish a namespace escape or a way to pass independent business assertions.

A separate lower-impact correctness gap is that `ast.parse()` accepts constructs that compilation rejects: `validate_ast("return 1\n")` also returned `(True, True, None)`, while `compile(..., "exec")` raised `SyntaxError: 'return' outside function`. Project Python validation also relies on `ast.parse`. Later isolated startup catches such candidates, but policy metadata incorrectly reports valid syntax and wastes an attempt.

**Recommendation:** prefer a constrained set of allowed handler expressions or conservatively track/reject aliases of catch-all exception classes, with tests for assignments, tuples, and exception-group handlers. Add a bounded compile-without-execution check for compiler-level syntax. Keep the policy's documented role limited to filtering; retain isolation and behavioral verification as independent controls.

### F08 — Medium: a successful wheel build is not a usable package

References: [`orchestrator pyproject.toml:20`](../../services/repair-orchestrator/pyproject.toml#L20), [`orchestrator pyproject.toml:26`](../../services/repair-orchestrator/pyproject.toml#L26), [`database.py:21`](../../services/repair-orchestrator/app/database.py#L21), [`snapshots.py:93`](../../services/repair-orchestrator/app/snapshots.py#L93), [`backend pyproject.toml:23`](../../apps/buggyshop-backend/pyproject.toml#L23).

The orchestrator wheel contains only `app`, although normal imports require `shared`, and fixture execution also requires `fixtures` and repository assets. Editable installs and pytest add the repository root to the import path, masking the omission. Both backend and orchestrator also publish the generic top-level package name `app`, creating collisions if installed into one environment.

**Reproduction:** after `make build`, ZIP inspection found no `shared/` or `fixtures/` entries in the orchestrator wheel. Importing `app.project` from that wheel in a child with repository source paths removed failed with `ModuleNotFoundError: No module named 'shared'`. This probe retained installed third-party dependencies, so it was not caused by missing Pydantic or HTTPX.

**Recommendation:** explicitly choose the support boundary. If these are installable distributions, package shared contracts/config as a dependency, use unique package namespaces, and resolve required fixture/assets through explicit resource roots. Add a clean-wheel import/CLI smoke test outside the checkout. If the product is intentionally checkout-only, state that clearly and avoid treating wheel construction as distribution validation. Keep backend and orchestrator environments separate until package namespaces are resolved.

### F09 — Medium: config validation differs by entry point and can raise uncaught exceptions

References: [`project.py:89`](../../services/repair-orchestrator/app/project.py#L89), [`project.py:101`](../../services/repair-orchestrator/app/project.py#L101), [`cli_check.py:114`](../../services/repair-orchestrator/app/cli_check.py#L114), [`probes.py:699`](../../services/repair-orchestrator/app/probes.py#L699), [`cli.py:1782`](../../services/repair-orchestrator/app/cli.py#L1782).

There are three overlapping config interpretations: strict `Configuration` validation for `check`, manual `load_project()` for `run`/controller repair, and tolerant `load_project_config()` for dashboard invariants. The manual loader indexes unvalidated scenario entries and nested rule structures. It also bypasses some checks performed by `validate_config`, such as unknown top-level fields and exact integer configuration checks.

**Reproduction:** a valid minimal project/repair config with `[[scenarios]]` containing a title but no `id` caused `load_project()` to raise `KeyError('id')`. `cmd_run` catches OSError/ValueError/RuntimeError, not KeyError or TypeError, so this malformed operator input escapes the intended controlled diagnostic path.

**Recommendation:** validate one typed TOML document and normalize scenario forms before selection. Make tolerant dashboard loading an explicit diagnostic view over that parser. Convert shape errors to a dedicated configuration error with field locations, rather than broadly catching programming errors. Parametrize the same malformed-document corpus across CLI check, CLI run, and controller startup.

### F10 — Medium: synchronous storage work stalls async control and cancellation

References: [`database.py:69`](../../services/repair-orchestrator/app/database.py#L69), [`database.py:158`](../../services/repair-orchestrator/app/database.py#L158), [`main.py:435`](../../services/repair-orchestrator/app/main.py#L435), [`main.py:569`](../../services/repair-orchestrator/app/main.py#L569), [`evidence.py:104`](../../services/repair-orchestrator/app/evidence.py#L104), [`project.py:322`](../../services/repair-orchestrator/app/project.py#L322).

Async routes and the serial worker call synchronous SQLite operations, filesystem traversal, hashing, and fsync directly on the event loop. SQLite's busy timeout is five seconds. The `RLock` also waits synchronously if a thread owns the shared connection. A finalization transaction intentionally spans evidence writes, further extending potential contention. Stage timeouts cannot preempt those synchronous spans.

**Reproduction:** holding a write transaction on one temporary connection and attempting a second connection's write from an async task delayed a 10 ms scheduled callback to **151 ms**, with the probe's busy timeout shortened to 150 ms. Production configuration allows a five-second wait per contention incident. This is a demonstrated scheduling effect, not a throughput benchmark.

**Recommendation:** move complete synchronous transactions and bounded evidence operations behind an owned DB/I/O executor or a suitable async storage adapter. Preserve transaction boundaries and wait for actual completion on cancellation: naive `to_thread()` fire-and-forget would create new cleanup races. Add a responsiveness test under writer contention and deliberately slow artifact persistence, checking cancellation and health latency.

### F11 — Medium: dependencies can change while source identity remains constant

References: [`project.py:322`](../../services/repair-orchestrator/app/project.py#L322), [`project.py:407`](../../services/repair-orchestrator/app/project.py#L407), [`project_runtime.py:123`](../../services/repair-orchestrator/app/project_runtime.py#L123), [`project_launcher.py:36`](../../services/repair-orchestrator/app/project_launcher.py#L36), [`proof_bundle.py:178`](../../services/repair-orchestrator/app/proof_bundle.py#L178).

Project execution hashes exported tracked files, but mounts `project_root/node_modules` and `.venv` directly from the operator's live checkout. Read-only binds prevent candidate writes; they do not freeze host-side changes. Node/Python toolchain directories are also mounted without their own recorded content identity. Lockfile source bytes alone do not prove the installed dependency tree matches them.

**Impact condition:** an install or another process changes dependencies between the two baseline sessions and verification. Identical `candidate_snapshot_sha256` values can then describe executions with different effective code. This is a reproducibility/evidence gap; no dependency mutation or sandbox escape was attempted in this audit.

**Recommendation:** provision dependencies from an immutable, content-addressed environment used for every measurement, and include dependency/toolchain identity in execution records and proof bundles. If that is deferred, document source identity as covering tracked exports only, serialize cooperating install/run operations, and detect dependency drift before each execution. Add a test that changes a mounted dependency between measurements and expects rejection or a distinct identity.

### F12 — Low: sandbox limits are rendered from obsolete response keys

References: [`cli.py:386`](../../services/repair-orchestrator/app/cli.py#L386), [`isolated_runtime.py:508`](../../services/repair-orchestrator/app/isolated_runtime.py#L508), [`test_cli.py:290`](../../services/repair-orchestrator/tests/test_cli.py#L290).

The runtime response nests configured values under `configured` using `memory_max_bytes`, `tasks_max`, and `cpu_quota_percent`. The CLI reads top-level `memory_bytes`, `pids_max`, `cpu_quota_us`, and `cpu_period_us`. Its test supplies the obsolete shape and asserts only the heading/model.

**Reproduction:** feeding an actual `IsolatedRuntime().resource_limits_status` into `cmd_status()` printed `Sandbox Limits: Memory=0 MiB, Tasks=None, CPU=0/100000` for the default configured profile of 512 MiB, 64 tasks, 100% CPU.

**Recommendation:** define a typed readiness response shared by API and CLI; render configured values and enforcement status separately. Contract-test the CLI against the runtime's real response, including disabled/unavailable limits.

### F13 — Low: schema and persistence constraints do not fully agree

References: [`models.py:150`](../../shared/contracts/models.py#L150), [`database.py:101`](../../services/repair-orchestrator/app/database.py#L101), [`models.py:166`](../../shared/contracts/models.py#L166), [`probes.py:160`](../../services/repair-orchestrator/app/probes.py#L160), [`api.py:42`](../../services/repair-orchestrator/app/api.py#L42).

`RepairAttempt.attempt_number` has only `ge=1`, while SQLite constrains it to 1–2. Constructing an attempt numbered 3 succeeds in Pydantic but persistence rejects it. Existing worker paths generate at most two attempts, which limits current impact.

Other seams weaken the intended canonical-contract guarantee: `validation_result` and several public response models use `dict[str, Any]`; `PatchValidationResult` can represent internally contradictory booleans; probe/crawl request models inherit Pydantic coercion while `ContractModel` is strict. For example, a numeric string can enter some public integer fields even though canonical wire contracts describe strict scalar handling. These are contract/typing inconsistencies, not evidence that every response path is unsafe.

**Recommendation:** align the attempt bound with persistence, introduce typed validation/readiness records, and deliberately choose strictness for each public endpoint. Encode only stable cross-field invariants in validators. Add contract boundary tests rather than relying on mypy to check values hidden inside `Any`.

### F14 — Low: minimizer budget is not an oracle-call bound

References: [`minimizer.py:63`](../../services/repair-orchestrator/app/minimizer.py#L63), [`minimizer.py:76`](../../services/repair-orchestrator/app/minimizer.py#L76), [`minimizer.py:117`](../../services/repair-orchestrator/app/minimizer.py#L117), [`minimizer.py:153`](../../services/repair-orchestrator/app/minimizer.py#L153).

The iteration check occurs only at the outer dictionary loop. Inner subset/complement calls can overshoot it, and list minimization ignores the budget and does not increment the returned count. An early return for a single dictionary key also prevents minimizing a list stored under that key. Empty candidates are not considered, so the advertised minimality must be scoped to the algorithm actually run.

**Reproduction:** `max_iterations=1` with `{"items": list(range(12)), "required": True}` and an oracle requiring both keys and at least six items made **25 oracle calls**, while reporting `iterations=1`. A single-key `items` payload with an always-true oracle returned all 12 items without entering list minimization.

**Recommendation:** route every oracle invocation through a shared budget/deadline counter, include list work in the count, and expose whether minimization stopped due to budget. Define whether empty payloads/lists are permitted. Add tests for exact call bounds and single-key list payloads before wiring this library into live repair. It currently has no production caller; its module documents that limitation.

### F15 — Low: persistent history and fixture storage lack retention budgets

References: [`orders.py:27`](../../apps/buggyshop-backend/app/orders.py#L27), [`main.py:108`](../../apps/buggyshop-backend/app/main.py#L108), [`database.py:213`](../../services/repair-orchestrator/app/database.py#L213), [`live_demo.py:223`](../../services/repair-orchestrator/app/live_demo.py#L223), [`live_demo.py:229`](../../services/repair-orchestrator/app/live_demo.py#L229), [`live_demo.py:289`](../../services/repair-orchestrator/app/live_demo.py#L289).

Backend order creation scans the namespace's list for duplicate IDs; reads copy the entire list under a global lock, and single-order lookup copies that list before scanning it. Repeated inserts into one namespace cost O(n²) cumulatively, and namespaces/orders are never evicted. This is acceptable for a short synthetic fixture but not a general persistent shop backend.

Orchestrator history/artifacts/checks have no general retention policy. `unfinished_jobs()` scans by state without a state index on each worker poll. The public live service retains finished `runs` in memory and re-reads/parses its entire JSONL ledger for daily capacity and aggregates. Daily admission caps bound new work, not lifetime history.

**Recommendation:** retain the fixture's isolation and defensive copies, but add namespace lifecycle cleanup and keyed order lookup if it becomes long-lived. For the controller, define age/byte retention and preserve referenced proof artifacts consistently; add a state index only after measuring history-size costs. Store live accounting in indexed persistent records, or maintain a validated append-aware summary and evict finished in-memory runs. Add scale tests based on realistic retained history; no large-load benchmark was run here.

### F16 — Low: module boundaries and stale contracts encourage further drift

References: [`cli.py:1`](../../services/repair-orchestrator/app/cli.py#L1), [`live_store.py:16`](../../services/repair-orchestrator/app/live_store.py#L16), [`repro.py:414`](../../services/repair-orchestrator/app/repro.py#L414), [`project_runtime.py:56`](../../services/repair-orchestrator/app/project_runtime.py#L56), [`runtime.py:1`](../../services/repair-orchestrator/app/runtime.py#L1), [`PROJECT_RUNNER.md:90`](../PROJECT_RUNNER.md#L90).

`cli.py` is 2,114 lines, mixing transport, diagnostics, delivery, rendering, event streaming, and command parsing. `worker.py` is 934 lines and `isolated_runtime.py` 1,480. The server's `live_store` imports the CLI to perform business mutations, creating the wrong dependency direction. Header and readiness drift in F05/F12 are concrete consequences of duplicate wire interpretations and untyped dictionaries.

Python `PlaywrightSession` is exercised in tests but not used by the production project runtime, which uses `BrowserSession` plus `repro_browser.mjs`. It is a retained adapter, not proof of coverage of the production driver. `runtime.py` still claims the repository does not contain its runtime profile or browser CLI, despite both now existing. `HEALTHY_FILE` in `cli.py` has only test consumers. Reserved `repair.context` and setup/test commands are documented as inactive; their inactivity is intentional, not a newly discovered missing feature.

**Recommendation:** first extract delivery and typed API transport from the CLI, then group command implementations by concern while preserving parser behavior. Share assertion/reproduction decisions rather than duplicating them across worker/adapters. Remove or explicitly support retained adapters/constants; update stale module documentation. Avoid a broad rewrite before the correctness regressions are captured in tests.

## Test quality and architectural strengths

The suite is substantive. [`test_worker_lifecycle.py`](../../services/repair-orchestrator/tests/test_worker_lifecycle.py), [`test_database.py`](../../services/repair-orchestrator/tests/test_database.py), and [`test_policy.py`](../../services/repair-orchestrator/tests/test_policy.py) exercise cancellation, admission, cleanup/quarantine, malformed patches, and evidence failure cases. Backend tests explicitly distinguish healthy and seeded behavior and verify namespace isolation and concurrent storage writes. Tests are configured with strict markers/config and warnings as errors.

The test harness is also explicit about simulations: [`tests/conftest.py`](../../services/repair-orchestrator/tests/conftest.py) injects a runtime and can execute trusted fixture probes outside the sandbox. Those tests validate controller behavior, not containment. Real runtime/project/cgroup tests provide separate coverage; they must be counted separately from simulations. A green aggregate count is not evidence that every real-runtime test executed.

Useful safeguards to preserve during refactoring:

- SQLite `BEGIN IMMEDIATE` admission and atomic event allocation; no transaction spans an `await`.
- Exact single-file diff parsing, byte/line bounds, source hashes, and fresh staged exports for the fixture.
- Fail-closed runtime startup, bounded UDS responses, explicit resource intent, and supervised process cleanup.
- Model transport bounds, strict proposal decoding, provider identity derived from the endpoint, and explicit fallback labeling.
- Two independent project baseline sessions before repair, required assertion manifests, execution identity checks, and retained failed attempts.
- Artifact checksums/containment and transactional final proof registration only after confirmed cleanup. Bundle digests are correctly described as checksums rather than signatures.

The gaps found here explain why more test volume alone would not solve the problems: the CLI status test uses the wrong response shape; the header tests do not compare live and isolated transport semantics; regex tests establish functional matching without an external hard deadline; source delivery lacks conflict-injection coverage; build tests stop before isolated wheel imports.

CI's [`check.yml`](../../.github/workflows/check.yml) runs `make check` and `make browser`, but does not invoke `make integration` with `FAULTLINE_REQUIRE_ISOLATED_TESTS=1`. A prepared integration job should make required containment tests fail on unavailable machinery rather than silently skip. Keep ordinary cross-platform checks separate from a Linux runner that can actually enforce cgroups and namespaces.

## Recommended implementation order

1. Capture F01/F02 with bounded fault-injection tests; fix deadline containment and worker health/admission before adding features.
2. Add installation ownership and delivery identity/conflict handling (F03/F04), including actual multi-process tests.
3. Fix transport/redaction parity and policy gaps (F05–F07), using synthetic secrets and independent observed requests.
4. Consolidate config and wire contracts, correct the CLI display, and add wheel smoke tests (F08/F09/F12/F13).
5. Address event-loop I/O and dependency identity as deliberate execution-boundary changes (F10/F11), preserving cancellation and evidence guarantees.
6. Bound retained-library work and history growth, then make narrow module extractions (F14–F16).

No live hosted-model inference, arbitrary external target crawl, full corpus evaluation, kernel escape testing, Windows/PowerShell execution, or production load benchmark was performed. Those remain separate evidence claims.
