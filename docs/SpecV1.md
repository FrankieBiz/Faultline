# FaultLine — SpecV1

## Controlled browser QA and verified source repair

**Specification date:** October 26, 2026

**Status:** Implementation-ready design; application implementation and runtime validation have not been performed.

**Audience:** Engineers and coding agents implementing the demo, plus reviewers assessing its claims.

**Companion:** [Research, evidence, and design decisions](./SpecV1-research-notes.md).

This document replaces the initial FaultLine design. The original file is preserved. Requirements below describe the application to build; examples and release thresholds are not claims that the application already exists or has passed testing.

## 1. Product promise and boundaries

FaultLine reproduces a failure in a controlled web application, asks a Meta model for a bounded source patch, runs the candidate in isolation, and checks whether the intended behavior has been restored. The Inspector connects the observed failure, proposed change, and verification evidence in one visible workflow.

**Hero loop:** Run Chaos → reproduce checkout failure → request repair → validate patch → activate candidate → verify checkout and regressions → save evidence → clean up → show Verified or a specific failure outcome.

The first release supports one seeded backend bug, one registered browser scenario, and one active job. It uses Next.js, FastAPI, TypeScript Playwright, and hosted Meta inference. It does not require human approval between steps inside the isolated demo.

### Required in v1

- A small BuggyShop catalog, product detail, local browser cart, and checkout.
- A realistic optional-coupon runtime bug in one existing Python route file.
- A trusted browser scenario, API regression checks, and explicit business assertions.
- One orchestrator owning persistent job state, bounded model requests, patch policy, candidate execution, and cleanup.
- Inspector progress, failure/success screenshots, diff, assertions, logs, and request usage.
- Repeatable fresh-start behavior, cancellation, crash recovery, and detection when repair is unavailable.

### Deferred

Frontend repair, search-page repair, arbitrary repositories or target URLs, autonomous browsing, random fault injection, multiple users, remote execution, production deployment, automatic commits/merges, real payments, and automatic changes to the developer's checkout are outside v1. There is no alternate model provider or hidden prerecorded repair path.

Retain the FaultLine name and **Run Chaos** button, but label the scenario **Scripted checkout repair** and disclose that the bug is seeded and file localization is preconfigured. The demo demonstrates integration repeatability, not general defect discovery or general repair accuracy. Chaos engineering normally uses experiments against measurable steady-state behavior; that broader claim is not established here. [Chaos engineering principles](https://principlesofchaos.org/)

FaultLine's presentation centers on inspectable browser reproduction and protected verification. Issue-to-code repair and browser-test auto-healing already exist; avoid claiming those capabilities are new. Application source repair is distinct from changing a test's element matching. [Sentry Issue Fix](https://docs.sentry.io/api/seer/start-seer-issue-fix/), [mabl auto-heal](https://help.mabl.com/hc/en-us/articles/19078158616340-Assertions-and-auto-heal)

## 2. BuggyShop business contract

### 2.1 Fixture catalog and pages

| Product ID | Name | Unit price |
|---|---|---:|
| `trail-mug` | Trail Mug | 1,999 USD cents |
| `field-notebook` | Field Notebook | 1,500 USD cents |

Required pages are `/`, `/product/[id]`, and `/checkout`. Use Next.js App Router consistently. The cart lives in browser state; a new browser context starts with an empty cart. Quantity controls and checkout must have accessible names and stable role/label locators. A submitted order displays its ID, line items, subtotal, discount, and total.

Prices come from the backend catalog. Requests cannot supply prices. There is no tax, shipping charge, authentication, stock depletion, or payment-provider call. Display cents as USD only at the UI boundary.

### 2.2 API behavior

| Endpoint | Required result |
|---|---|
| `GET /healthz` | 200 with `{"status":"ok","app":"buggyshop-api"}` when startup is complete |
| `GET /api/products` | 200 with the fixed catalog |
| `GET /api/products/{product_id}` | 200 product; unknown ID returns 404 |
| `POST /api/checkout` | Valid request creates one synthetic order and returns 201 |
| `GET /api/orders/{order_id}` | 200 stored order in the current test namespace; unknown ID returns 404 |

Checkout request example:

```json
{
  "items": [{"product_id": "trail-mug", "quantity": 2}],
  "coupon_code": null
}
```

Rules:

- `items` contains 1–2 entries, each with a different known product ID.
- `quantity` is a strict integer from 1 through 10. Reject booleans, numeric strings, fractional numbers, null, and missing quantities.
- Reject unknown fields in checkout and item objects.
- `coupon_code` is an optional string or null. Missing, null, empty, or whitespace-only values normalize to no coupon.
- Otherwise trim surrounding whitespace and uppercase. The only recognized value is `DEMO10`; all other nonempty values return 422.
- `subtotal_cents` is the sum of catalog price × quantity. No coupon means zero discount. `DEMO10` means `discount_cents = subtotal_cents // 10`; `total_cents = subtotal_cents - discount_cents`.
- Validation failures return 422 and create no order. Structured validation bodies may use FastAPI's normal `detail` format; tests assert status and absence of an order, not unstable error prose.
- Successful requests create a server-generated UUID order ID. The response and readback use the same schema. Within the fixed scenario, the browser issues exactly one checkout request.

Successful response for the example:

```json
{
  "order_id": "42d7cd06-8edc-4c43-9c22-741f93c3e860",
  "currency": "USD",
  "items": [
    {"product_id": "trail-mug", "quantity": 2, "unit_price_cents": 1999, "line_total_cents": 3998}
  ],
  "subtotal_cents": 3998,
  "discount_cents": 0,
  "total_cents": 3998
}
```

For two mugs with `DEMO10`, the discount is 399 cents and total is 3,599 cents. For one mug, the discount is 199 cents and total is 1,800 cents. These examples deliberately cover fractional-cent rounding.

Order storage is synthetic and survives requests only for the lifetime of the execution's backend process. A fresh backend process starts empty. For test isolation, middleware selects a namespace from the trusted runner's `X-Faultline-Case-Id` header; manual fixture use defaults to `demo`. A namespace is an in-memory key, never a filesystem path. This mechanism belongs only to the fixture application.

Add `GET /api/orders` returning `{"orders":[...]}` for the current namespace, so negative tests can assert an unchanged order count. The list/readback implementation lives outside the repairable route file. No order-reset HTTP endpoint is needed.

### 2.3 Seeded defect

The healthy implementation satisfies all preceding rules. The seeded implementation differs only in optional-coupon discount lookup: no coupon yields a missing discount value which fails during arithmetic. Recognized coupons still work; unknown coupons are rejected before arithmetic.

The seed must pass dependency installation, compilation, application startup, catalog checks, and the recognized-coupon control. Missing, null, empty, and whitespace-only coupons produce the intended TypeError and checkout 500. Do not use an unconditional exception, a missing identifier, a deliberate syntax error, or a source comment that gives the model the solution.

Pin healthy and seeded revisions in a trusted fixture manifest generated during setup. Record the actual commit IDs and expected source hashes; fail readiness if they cannot be resolved or disagree. The healthy source and seeding recipe are excluded from the repair prompt and runtime candidate export.

## 3. Architecture and repository organization

```text
Inspector browser
  → Inspector Next.js server proxy
    → FastAPI orchestrator + SQLite + one serial worker
      → Meta hosted API: bounded patch proposal
      → host-side policy validation and candidate snapshot export
      → restricted BuggyShop backend + prebuilt frontend
      → separate trusted Playwright Test runner
      → registered evidence artifacts
```

The orchestrator is the only workflow owner. The runner executes trusted tests once and returns observations; it never requests a repair, schedules another execution, applies a patch, or calls the model. Remove the original runner HTTP service and synchronous callback chain.

```text
faultline/
  apps/buggyshop-frontend/          # Next.js App Router; fixed during v1 repair
  apps/buggyshop-backend/
    app/routes/checkout.py         # Only repairable source file
    app/                           # Catalog, validation, order storage/readback, health
  services/repair-orchestrator/    # FastAPI controller, worker, policy, runtime adapter
  tools/browser-runner/            # Trusted TypeScript Playwright Test CLI and oracle
  web/inspector-ui/                # Next.js App Router and server proxy
  shared/contracts/               # Canonical Pydantic models and generated schemas/types
  shared/config/                  # Trusted scenario registry and fixture manifest
  fixtures/                       # Healthy/seed provenance; excluded from candidates
  scripts/                        # Setup, supervised demo startup, verification, reset
  data/                           # Ignored SQLite DB, job snapshots, and evidence
```

Use Node.js 24 LTS and Python 3.13 in controlled build/runtime environments. Pin concrete dependencies and image digests during setup, commit lockfiles, and record versions in the demo manifest. Match the Playwright package version to its browser image. Prefer native arm64 images on Apple Silicon; do not silently switch to emulated images. [Node release policy](https://nodejs.org/en/about/previous-releases), [Playwright Docker guidance](https://playwright.dev/docs/docker)

The fixture frontend and Inspector are built before demo jobs. Use production-serving processes, not development hot reload. Only the backend candidate changes in v1. A backend candidate is activated from a validated snapshot using the fixed dependency image; no dependency installation or frontend rebuild occurs in the hero loop.

The target frontend proxies its browser `/api/*` requests to the backend at a fixed internal service name. The browser runner therefore uses one fixture origin and does not need cross-origin application requests. The Inspector is a different application and calls only its own server proxy.

## 4. Scenario registry and execution ownership

The server-owned registry has one enabled v1 scenario:

| Field | Value or source |
|---|---|
| `scenario_id` | `checkout-flow` everywhere |
| `seed_id` | `checkout-missing-coupon-v1` |
| `seed_commit`, `seed_source_hash` | Trusted fixture manifest |
| `scenario_version`, `fixture_version` | Versioned values in the manifest |
| Repair target | `apps/buggyshop-backend/app/routes/checkout.py` |
| Browser origin | `http://buggyshop-web:3000` inside the job network |
| Failure route | `POST /api/checkout` |
| Primary input | Two mugs; coupon left empty |
| Expected behavior | One order; subtotal/total 3,998 cents; zero discount |
| Repairable failure | Seeded checkout 500 plus correlated TypeError in the allowed route |
| Verification | Original flow, API regression cases, and fresh-context confirmation |

URLs, browser source hints, stack traces, and model text are observations, not authority. Only the registry selects the seed, file, commands, test suite, and service addresses. Do not accept these capabilities from API callers.

Each job starts from a fresh seeded baseline automatically. The baseline gets its own backend process, empty order store, and fresh browser context. Each repair attempt starts from the same seed rather than the previous candidate. Each candidate verification uses a fresh backend process; individual test cases use new contexts and fresh case namespaces. The original order and its readback remain within the same case.

Attach browser listeners before navigation. Capture response status, uncaught browser exceptions, assertions, and transport failures separately. HTTP 500 is an HTTP response, not a `requestfailed` event. [Playwright request semantics](https://playwright.dev/docs/api/class-page#page-event-requestfailed)

Run through Playwright Test with a JSON reporter, tracing enabled for every execution, one worker, and retries set to zero. Await functional assertions and drain bounded response-body collection before closing the context. Use role/label locators, not fixed sleeps. [Playwright assertions](https://playwright.dev/docs/test-assertions), [Trace Viewer](https://playwright.dev/docs/trace-viewer)

Collect backend structured logs with execution ID, case ID, request ID, route, and exception type. Middleware adds request IDs to responses. Capture process stderr for the traceback; do not enable public debug tracebacks. Frontend server logs are evidence when needed, but browser `pageerror` alone is never the oracle for server failures.

### Runner invocation contract

The trusted CLI reads one `RunnerRequest` JSON file mounted read-only at `/input/request.json`: `schema_version`, `job_id`, `execution_id`, `phase` (`baseline` or `verification`), `scenario_id`, `app_generation_id`, `candidate_snapshot_sha256`, and `timeout_ms`. The controller supplies these values and caps the timeout at 20,000 milliseconds and the remaining stage budget. The runner resolves the fixed origin and suite from its trusted registry; the request contains no URL, command, source path, or test path.

Run the fixed command `node dist/cli.js --request /input/request.json`. Write the completed `ExecutionReport` to `/artifacts/report.json` and evidence beneath `/artifacts/`, a runner-only mount. Include an artifact manifest with IDs, relative filenames, roles, sizes, and hashes; the controller validates containment, file bytes, and referenced IDs before registering it. Stdout is diagnostic text, not the machine-report channel.

Exit codes are 0 for passed, 1 for assertion failure, 2 for runner/infrastructure error, and 3 for runner timeout. An assertion-failing baseline is the expected trigger for classification, not an automatic runner error. Report/exit-code disagreement or missing reports is infrastructure failure, except when the controller itself enforced a known deadline, which supplies the appropriate timeout verdict. The runner creates no recursive repair or retry process.

## 5. Canonical contracts and persistent state

### 5.1 One schema authority

Define strict Pydantic models in `shared/contracts/`, with unknown fields forbidden. Export JSON Schema Draft 2020-12, generate TypeScript declarations using `json-schema-to-typescript`, and validate runner data using Ajv's 2020 implementation. Use simple objects, arrays, scalar fields, enums, and local references; avoid generator-unsupported schema features. Regeneration and shared positive/negative fixtures must pass in both languages. Generated files are never edited manually. [Pydantic schema generation](https://docs.pydantic.dev/latest/concepts/json_schema/), [TypeScript generator](https://github.com/bcherny/json-schema-to-typescript), [Ajv schema support](https://ajv.js.org/json-schema.html)

Persisted control-plane records and runner envelopes carry `schema_version: "1.0"`. The raw provider `PatchProposal` is the five-field schema in section 7 and is versioned by its enclosing attempt and recorded schema hash. IDs are server-generated UUID strings. Persist timestamps as UTC RFC 3339; enforce active deadlines with a monotonic clock.

| Contract | Required information |
|---|---|
| `Job` | ID; requested/effective mode; scenario/seed/versions; state, stage, outcome; request fingerprint; deadline; baseline and attempt references; cancellation flag; repair block reason; cleanup status; timestamps |
| `ExecutionReport` | ID, job, phase, optional attempt; candidate snapshot hash and resource generation; scenario/fixture versions; verdict; named case/assertion results; observations; artifact IDs; start/end timestamps |
| `FailureObservation` | ID; case/step; kind; request URL/method/status or transport error; exception type and bounded trace; correlated logs; expected/observed summary; diagnostic artifact IDs |
| `PatchProposal` | `decision`, `target_file`, `base_sha256`, `unified_diff`, `explanation` |
| `RepairAttempt` | ID/index; request/response metadata; proposal or parse error; base/candidate hashes; gate results; verification execution; verification result; usage/estimate; start/end timestamps |
| `Artifact` | ID, job, optional execution/attempt, role, content type, size, SHA-256, private storage key, creation time |
| `JobEvent` | Job ID, monotonic sequence number, UTC time, stage, message code, bounded display message |

Execution phases are `baseline` and `verification`. A verification report contains separately named primary, regression, and confirmation case results. Verdicts are `passed`, `assertion_failed`, `infrastructure_error`, and `timed_out`. Each assertion has ID, pass/fail, expected/observed summary, and duration. A report is immutable after completion.

Observation kinds are `assertion`, `http_error`, `browser_exception`, `transport_error`, `server_exception`, and `runner_error`. There may be several observations; do not flatten them into a single arbitrary error.

### 5.2 Job state and outcome

Job states: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `interrupted`.

Stages: `preparing`, `baseline`, `diagnosing`, `patch_validation`, `activating`, `verification`, `cleanup`, `completed`. Store gate results and events; a terminal job has stage `completed` and preserves the failed stage in its error details.

Cleanup status: `not_started`, `in_progress`, `succeeded`, `failed`.

| Terminal outcome | State | Meaning |
|---|---|---|
| `verified` | succeeded | Expected baseline failed; all candidate gates passed; evidence and cleanup complete |
| `detected` | succeeded | Explicit detection-only job reproduced the expected failure; no repair requested |
| `no_failure` | succeeded | Baseline business assertions passed; no repair occurred |
| `repair_unavailable` | failed | Expected failure reproduced, but configured repair capability was unavailable |
| `unexpected_failure` | failed | Baseline failed outside the registered repairable fingerprint |
| `invalid_patch` | failed | Attempts ended without an applicable policy-compliant candidate |
| `model_error` | failed | Final attempt ended in provider, refusal, incomplete, or parsing failure |
| `unresolved` | failed | Final candidate was applicable but failed compile, readiness, or behavior checks |
| `infrastructure_error` | failed | Trusted runner/runtime failed independently of a candidate defect |
| `artifact_error` | failed | Required evidence could not be durably saved |
| `timeout` | failed | Global 170-second work cutoff or 180-second overall deadline expired |
| `cleanup_failed` | failed | Owned resources could not be confirmed clean; new jobs blocked |
| `cancelled` | cancelled | Cancellation honored and cleanup confirmed |
| `interrupted` | interrupted | Process restart abandoned an unfinished job and reconciliation confirmed cleanup |

Before termination, `outcome` is null. On exhausted attempts, use the final attempted gate's outcome and retain every earlier failure in attempt records. Do not replace an earlier attempt history with the final result. Expiry of a global deadline takes terminal `timeout` precedence; local stage/request timeouts follow the attempt rules in section 10.3. Cleanup failure takes precedence over every other outcome, while preserving `last_work_outcome` and individual verification results.

**Completed GREEN is derived only from `state=succeeded`, `outcome=verified`, and `cleanup_status=succeeded`.** Detection success, a baseline that already passed, or a model's explanation cannot produce a repaired GREEN result.

### 5.3 SQLite and resource ownership

Use SQLite tables `jobs`, `executions`, `repair_attempts`, `artifacts`, `job_events`, and `runtime_resources`, with schema migrations. Store large evidence outside SQLite under server-generated job directories. Short transactions persist intent and state; never hold a transaction across model requests, container work, or browser execution. One writer/worker is sufficient; WAL may support UI readers but is not a substitute for a single workflow owner. [SQLite concurrency](https://www.sqlite.org/wal.html#concurrency)

Use a single durable demo lease record to reject overlapping jobs/reset operations. `queued` is the short persisted state before the sole worker claims a job; it is not a multi-job backlog. Start one FastAPI process without reload. Use lifespan startup/shutdown to own the worker and reconcile resources. [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)

Persist runtime intent before creating resources. Label each container/network with the installation ID, job ID, role, and generation ID. On restart, reconcile only resources belonging to this installation, terminate unfinished jobs, save `interrupted`, and clean up. Do not attempt to resume midway through candidate mutation. Failed reconciliation sets `cleanup_failed` and keeps the lease quarantined.

## 6. Controller API and Inspector proxy

Bind the Inspector to `127.0.0.1:4000` and controller to `127.0.0.1:9000`. The controller requires `Authorization: Bearer <FAULTLINE_CONTROL_TOKEN>` on all routes except a minimal `/healthz`. The token exists only in controller and Inspector server environments. It never enters browser JavaScript, target containers, runner input, artifacts, or model prompts.

The Inspector exposes a same-origin `/api/faultline/*` proxy. Mutation handlers require the exact configured Inspector origin and a session-bound CSRF token. Reject missing/unexpected origins and invalid CSRF tokens. The proxy forwards only registered controller routes and supplies the controller bearer token. CORS and loopback binding alone are not authorization.

| Endpoint | Request / response |
|---|---|
| `POST /jobs` | Body `{scenario_id, idempotency_key, mode?}`; mode is `repair` (default) or `detect`; 202 `{job_id, state, effective_mode, repair_block_reason}` |
| `GET /jobs?limit=20` | Latest jobs first; limit 1–100; `{jobs:[...]}`; no pagination cursor required in v1 |
| `GET /jobs/{job_id}` | `{job, baseline, attempts, executions, artifacts, events}`; unknown ID 404 |
| `GET /scenarios` | Enabled registry summaries; includes expected behavior and repairable scope, never source/secret configuration |
| `GET /readiness` | Overall `ready`, `detect_only`, or `blocked`, component statuses, reason codes, probe time/model, cleanup quarantine; never secret values |
| `POST /jobs/{job_id}/cancel` | 202 for active job; 200 unchanged terminal record for terminal job; unknown ID 404 |
| `POST /demo/reset` | 200 after owned resources are clean and local preflight succeeds; active job 409; failure 503 with reason |
| `GET /artifacts/{artifact_id}` | Content selected through the registered artifact ID; unknown ID 404 |

`idempotency_key` is a client UUID retained across retries of the same click. The request fingerprint includes scenario and requested mode. Check idempotency before the busy condition: same key and same fingerprint returns the same job without running again; same key/different fingerprint returns 409 `idempotency_conflict`. A new key while a job/reset owns the lease returns 409 `busy`. Persist idempotency for as long as job history exists.

Reject unknown scenario IDs and malformed bodies with 422. A quarantined runtime rejects new jobs with 503 `cleanup_required`. Use controller errors shaped as `{"error":{"code":"busy","message":"A demo job is already active.","job_id":null}}`, with the appropriate safe message and optional associated job ID.

If the model is unavailable but local detection is ready, accept a repair-mode job with `effective_mode=detect` and a visible block reason. Run baseline detection without generation requests. Its terminal outcome is `repair_unavailable` when the expected defect appears, `unexpected_failure` for another defect, or `no_failure` when assertions pass. An explicitly requested detect-mode job uses `detected` for the expected failure.

Reset is an idle maintenance operation. It disposes owned leftovers, removes disposable snapshots/runtime state, checks the trusted fixture manifest and local images, and releases quarantine only after cleanup succeeds. It retains reports and does not mutate the seed or developer checkout. Reset does not rerun the model probe. Restart the controller to recheck provider readiness after a configuration change or transient provider failure; document that restart as the explicit recovery action.

## 7. Meta repair adapter

### 7.1 Fixed protocol

Use the OpenAI Python client against Meta's documented compatible endpoint, with automatic retries disabled. The application has one adapter: `MetaRepairAdapter.propose_patch(context) -> PatchProposal`. The model has no tools, shell, browser, repository API, or network fetch function.

| Setting | v1 value |
|---|---|
| Base URL | `https://api.meta.ai/v1` |
| Endpoint | `/chat/completions` |
| Key | `MODEL_API_KEY`, treated as an opaque secret |
| Model | `META_MODEL_NAME`, default `muse-spark-1.3` Standard mode |
| Optional documented model | `muse-wonder-1.0`, only when explicitly configured and probed |
| Output | `response_format.type=json_schema`, `json_schema.strict=true` |
| Reasoning | `reasoning_effort=low` |
| Completion limit | `max_completion_tokens=4096`, including reasoning |
| Sampling | Leave temperature/top-p unset |
| Tools | Omit tools entirely |
| Client retries | `max_retries=0`; orchestrator owns all generation requests |

Do not mix Responses API fields into Chat requests. In particular, do not send `max_output_tokens` or `text.format`, and do not run `apply_chat_template` before sending structured messages. Meta documents Chat for simple turns and demonstrates `muse-spark-1.3` structured output. Runtime compatibility still requires the startup probe. [Chat protocol](https://dev.meta.ai/docs/protocols/chat-completions), [structured output](https://dev.meta.ai/docs/structured-output), [model catalog](https://dev.meta.ai/docs/models)

Use this proposal schema, with every property required:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "decision": {"type": "string", "enum": ["patch", "no_patch"]},
    "target_file": {"type": "string"},
    "base_sha256": {"type": "string"},
    "unified_diff": {"type": "string"},
    "explanation": {"type": "string"}
  },
  "required": ["decision", "target_file", "base_sha256", "unified_diff", "explanation"]
}
```

For `patch`, require the exact registry path, the supplied 64-character base hash, a nonempty diff, and a concise explanation capped at 2 KiB. For `no_patch`, path/hash/diff must be empty strings and the explanation must state why. Local semantic validation remains mandatory even when strict JSON decoding succeeds.

Accept exactly one response choice with `finish_reason=stop`, nonempty string content, no refusal/tool call, and a locally valid proposal. Reject truncated output, unexpected response shape/model, extra prose, Markdown fences, invalid JSON, extra keys, or semantic mismatch. Record a safe diagnostic rather than attempting format repair behind the request counter.

### 7.2 Readiness probe

Before enabling repair, perform authenticated `GET /v1/models`, require the configured exact model ID, then issue one bounded Chat generation using the production proposal schema and a generated nonce. Ask for `no_patch`, empty path/hash/diff, and the nonce as the entire explanation. Verify completion, returned model, schema, and nonce locally.

Probe limits are five seconds for the catalog request and fifteen seconds/512 completion tokens for generation. Log probe identity, timestamp, endpoint/model, latency, safe error code, and usage separately from jobs. The probe is a real generation request, counted and costed separately from each job's two-request limit. Never describe it as a free or local check.

Probe once per controller startup and model/schema fingerprint. If startup repair readiness fails, enter detection-only mode and display the latest probe time and reason. Recovery requires an explicit controller restart and another separately recorded startup probe. No background generation probes, hidden in-job probes, or automatic endpoint/model/provider fallback are allowed.

### 7.3 Prompt boundaries, accounting, and failure policy

Trusted instructions specify the scenario's behavior, exact edit scope, proposal format, and base hash. The user-message data contains only selected failure observations and the allowed current source. Delimit logs, source comments, and network bodies as untrusted evidence; their text cannot expand capabilities. Enforcement happens in code outside the model. [OWASP prompt-injection guidance](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)

Limits: source at most 32 KiB UTF-8, selected evidence at most 16 KiB, serialized generation request at most 64 KiB, response body at most 64 KiB, diff at most 16 KiB. Reject an oversized source or request before generation rather than truncating source code. Truncate evidence deterministically with explicit markers and retain the bounded raw evidence artifact. Screenshots are displayed to people but not sent to the model in v1.

A generation wire request is counted when dispatched, whether it succeeds, fails, times out, refuses, or returns invalid content. At most two may be dispatched per job. Retry only transient transport/429/5xx failures or rejected candidate proposals while another complete attempt fits; every new dispatch consumes the next attempt. Honor `Retry-After` only within the remaining attempt/deadline budget. Authentication, billing, permission, or unsupported-schema failures stop repair and mark readiness unavailable. A valid `no_patch` stops the job as unresolved. No provider or schema fallback is permitted.

Record returned input/completion/cached token counts when present; unknown usage remains unknown. Display an estimate using a dated pricing table and preserve conservative request reservations for unknown timeout usage. Do not equate local timeout with confirmed provider cancellation. Do not promise a hard spend cap from a different protocol's token counter. Standard-mode data handling is not a zero-retention guarantee. [Pricing](https://dev.meta.ai/docs/pricing-rate-limits), [token counting](https://dev.meta.ai/docs/token-counting), [zero data retention](https://dev.meta.ai/help/policies-and-privacy/zero-data-retention)

## 8. Patch policy and candidate identity

Apply patches only in an orchestrator-owned disposable worktree created from the trusted seed commit. The normal developer checkout is never a target. The host performs policy operations but never imports or executes candidate Python or JavaScript.

For every attempt:

1. Create a fresh detached worktree from the seed; verify its target hash and clean index/worktree.
2. Resolve the target exclusively from the registry. Verify it and every parent are regular paths without symlinks, and canonical containment holds within the disposable root.
3. Parse only a UTF-8 Git-style unified diff for the exact one existing file. Reject absolute paths, traversal, quoted/escaped unusual filenames, duplicate file sections, additions/deletions, renames/copies, binary patches, mode changes, submodules, and paths outside the allowlist.
4. Require at most 16 KiB diff and at most 100 added-plus-deleted lines, excluding headers. Empty/no-op patches are invalid. Recheck the supplied base hash immediately before application.
5. Invoke Git with fixed argument arrays and diff bytes through stdin: `git apply --check --index`, then `git apply --index`. Never use shell interpolation, `--unsafe-paths`, three-way fallback, or fuzzy repair of the diff.
6. Inspect the indexed diff and filesystem again: exact file set, normal file mode, expected size, permitted line count, and no unexpected changes. Cap resulting target size at 32 KiB.
7. Export the validated staged index's required backend application files with `git checkout-index` into a new snapshot directory. Do not export `HEAD`, which would omit the staged repair. Exclude `.git`, fixtures, tests, tooling, and credentials.
8. Hash a sorted manifest of exported relative paths, modes, and file bytes. Store its SHA-256, target before/after hashes, diff, and runtime resource generation before activation.
9. Mount the exported snapshot read-only in the fixed backend runtime image. Compile there with bytecode directed to temporary storage; then start a new backend container from the same snapshot.

Git applicability does not prove safety or correctness. Worktrees share repository administration and are not process isolation. [Git apply](https://git-scm.com/docs/git-apply), [index export](https://git-scm.com/docs/git-checkout-index), [Git worktree](https://git-scm.com/docs/git-worktree)

The controller assigns the container ID and generation to the snapshot. Readiness requires the owned process/container alive, the exact health response, and a successful catalog smoke request. A container started from another snapshot cannot satisfy the attempt. Application self-reported revision strings alone are not trusted provenance.

## 9. Execution boundary and trusted oracle

Run the fixture frontend, candidate backend, and trusted runner on a per-job internal Docker network, without published fixture ports. Only Inspector/controller ports are exposed, on host loopback. Human inspection uses saved artifacts; a live target iframe is not required.

The backend uses a non-root user, read-only root filesystem and code snapshot, bounded `/tmp`, dropped capabilities, no privilege escalation, and no host networking. Do not mount the repository, home directory, Docker socket, host credentials, or writable host source. Model keys/control tokens exist only in the host control plane. Dependencies are prebuilt from trusted locked manifests; candidate dependency changes are forbidden.

Initial runtime caps, to verify during rehearsal:

| Resource | Memory | CPUs | PID limit |
|---|---:|---:|---:|
| Backend | 512 MiB | 1 | 128 |
| Prebuilt target frontend | 1 GiB | 1 | 256 |
| Trusted runner/Chromium | 2 GiB | 2 | 512 |

Give the runner its own writable artifact directory and browser temporary storage; the backend cannot mount either. Run Chromium as a non-root user with its documented sandbox/seccomp requirements and private shared memory allocation. Do not copy privileged/container examples into this execution profile. Container settings must be rehearsed on the actual arm64 machine. [Docker runtime controls](https://docs.docker.com/reference/cli/docker/container/run/), [Playwright Docker](https://playwright.dev/docs/docker)

The trusted runner image contains the fixed oracle and fixture expectations. The candidate backend has no test files, report-writing channel, model credentials, or controller token. Do not import candidate application code inside the host controller or privileged runner; verify its behavior through HTTP/browser interfaces.

An internal network is one control, not a complete host boundary. Before release, test that candidate code cannot reach the control API, model API, Docker daemon, a dummy host secret, or an instrumented outside endpoint. Refuse repair execution if the required containment profile cannot be established. Do not fall back to running the candidate on the host. This profile is scoped to the controlled fixture; arbitrary hostile repositories require a separate design. [Docker security](https://docs.docker.com/engine/security/), [internal-network limitations](https://docs.docker.com/reference/cli/docker/network/create/#network-internal-mode---internal)

## 10. Workflow, time allocation, and cleanup

### 10.1 Per-job sequence

1. **Persist and prepare:** Validate request, acquire lease, write job, load trusted seed, create fresh runtime/resources, and check readiness.
2. **Baseline:** Run the browser's desired checkout behavior. Save immutable failure evidence and a report whose verdict remains failed. Separately classify whether it matches the repairable fingerprint.
3. **Stop when appropriate:** A passing baseline yields `no_failure`; another failure yields `unexpected_failure`; unavailable repair yields detection-only results. None requests a patch.
4. **Diagnose:** For a repairable failure, create a fresh attempt, bounded prompt, and counted generation request.
5. **Validate and activate:** Enforce proposal/patch policy, export and compile the candidate, replace the backend, and check readiness. The frontend stays fixed.
6. **Verify:** Run the complete protected suite and fresh-context confirmation. Save the candidate report and evidence.
7. **Retry if eligible:** After a rejected attempt, stop/remove that candidate, retain evidence, create the next attempt from the original seed, and include only a bounded summary of the previous rejected gate. Do not reveal withheld cases or expected values through retry feedback.
8. **Finalize:** Save required artifacts, stop/remove owned containers/networks, dispose worktrees/snapshots after exporting review artifacts, confirm cleanup, release lease, and write terminal outcome.

### 10.2 Deadlines

| Allocation | Maximum |
|---|---:|
| Preparation plus baseline | 20 seconds |
| Complete attempt, including model and checks | 75 seconds |
| Generation request inside an attempt | 45 seconds |
| Candidate verification command | 20 seconds, within attempt allowance |
| Active work cutoff | 170 seconds from job start |
| Final cleanup reserve | 10 seconds |
| Overall healthy-controller job deadline | 180 seconds |

Pass the minimum of local-stage and remaining global time to each operation. Start attempt two only with at least 75 seconds before the work cutoff. Time spent honoring provider backoff, discarding a rejected candidate, collecting evidence, or restarting a service counts toward the active budget.

At the work cutoff, stop dispatching work, close local model requests, terminate owned child processes/containers, and enter cleanup. By the overall deadline, persist timeout or cleanup failure if cleanup cannot be confirmed. A crashed controller cannot guarantee a wall-clock terminal update; startup reconciliation records that interruption rather than pretending the deadline was honored.

These limits are proposed engineering targets, not measured latency or repair success. If rehearsal cannot meet them, the release gate fails and the limit change must be explicit and versioned.

### 10.3 Failure and cancellation rules

- A baseline transport/readiness failure is an infrastructure result; it must not cause a speculative source patch.
- Expiry of the 20-second preparation/baseline allocation is `infrastructure_error` with `baseline_timeout`. A local model-request timeout is an attempt-level `model_error` with `provider_timeout`; a candidate verification timeout is an attempt-level `unresolved` with `verification_timeout`. The latter execution verdict is `timed_out`. A 75-second attempt deadline uses `model_error` if generation is still active, otherwise `unresolved`, with `attempt_timeout`. These local failures may use the remaining attempt when eligible; after exhaustion, their classification becomes the terminal outcome. Only a global cutoff supersedes them with terminal `timeout`.
- Candidate compile/startup/health failure is a candidate rejection (`unresolved` after exhaustion), unless evidence identifies failure of the trusted runtime itself.
- Once candidate verification starts, any failed mandatory assertion rejects the candidate. No retry-until-green or skipped required test is allowed.
- Runner tests disabled, missing, changed, or producing malformed reports cause trusted-runner failure, never success.
- Cancellation is checked before every side effect and between blocking operations. Kill owned children and clean up; show cancelled only after cleanup is confirmed.
- Cancellation after a terminal result returns that result; it does not rewrite history.
- Successful verification followed by evidence failure is `artifact_error`; followed by cleanup failure is `cleanup_failed`. Keep the verification evidence but do not show completed GREEN.
- Failure to clean up quarantines the lease. Idle reset/reconciliation may retry cleanup; ordinary jobs cannot bypass it.
- Rollback means discarding the candidate and retaining the immutable seed. It never means reverse-applying a patch into the developer checkout.

## 11. Verification oracle and evidence

### 11.1 Browser acceptance

The primary case navigates catalog → mug detail → quantity two → cart → checkout, leaves coupon empty, and submits once. Healthy/candidate expectations are:

- Exactly one `POST /api/checkout` occurs with the intended items and normalized coupon meaning.
- Status is 201; response validates against the order schema.
- Order ID is a nonempty UUID; values match independently computed expectations.
- Confirmation displays the same ID, quantities, subtotal, discount, and total.
- Order readback matches, and the current case namespace contains exactly one order.
- No unexpected first-party 5xx response or uncaught browser exception occurred.

The same test fails on the seeded revision; baseline classification additionally requires checkout 500, correlated TypeError from the registered file, visible failure UI, and no order. Preserve this failure rather than rewriting it as a passing test because the failure was expected by the demo.

### 11.2 Protected API and confirmation cases

Use a fresh namespace for every row; new browser contexts for browser cases. Pricing expectations are authored in the trusted runner and reviewed against the business contract, not imported from the application's pricing code.

| Case | Required result |
|---|---|
| Missing coupon; one mug | 201; subtotal/total 1,999; discount zero; stored order |
| Explicit null, empty, and whitespace coupon | Each 201 with zero discount |
| Recognized `DEMO10`; one mug | 201; discount 199; total 1,800 |
| Trimmed/lowercase ` demo10 `; two mugs | 201; discount 399; total 3,599 |
| One mug + two notebooks; no coupon | 201; subtotal/total 4,999 |
| One mug + two notebooks; `DEMO10` | 201; discount 499; total 4,500 |
| Quantity ten | 201; catalog-derived values |
| Empty cart, duplicate ID, unknown ID | Each 422; no new order |
| Quantity 0, 11, -1, 1.5, `"2"`, true, null, missing | Each 422; no new order |
| Unknown coupon or wrong coupon type | 422; no new order |
| Client-supplied price or unknown object fields | 422; no new order |
| Unknown order/product readback | 404 |
| Final fresh-context browser confirmation | Original flow passes again in a new namespace |

Apply one suite-level 20-second verification timeout, with bounded individual API requests; do not multiply a long per-test default across all cases. Every required case must run. Timeouts and omitted cases reject the candidate.

The model receives intended behavior and the original failure, not oracle source, withheld case inputs, or golden repaired source. Withholding helps reduce direct leakage but does not prove independence or general correctness. Report the result as **verified against the declared suite**. Passing tests can still miss overfitting. [Repair-correctness research](https://people.csail.mit.edu/rinard/paper/issta15.pdf), [Playwright isolation](https://playwright.dev/docs/browser-contexts)

### 11.3 Evidence contract

For baseline and every candidate execution, save screenshots at the meaningful failure/final state, Playwright trace, JSON assertions/report, filtered first-party request/response metadata, and correlated service logs. Save proposal/diff and source hashes per attempt, including rejected attempts.

Use `data/jobs/<job_id>/executions/<execution_id>/` and attempt subdirectories internally; never return those raw paths to the browser. Artifacts have server-generated IDs and SHA-256 values. Before final success, verify required files exist and match their registered hashes. Preserve original baseline artifacts permanently within retained job history; reset never overwrites them.

Capture only first-party textual response bodies, up to 2 KiB per body and 16 KiB total per execution. Cap collected text logs at 64 KiB, retaining the failure-relevant tail with truncation metadata. Redact authorization/cookie headers and secret-like configured values before persistence or model use. Give traces a 25 MiB budget; if essential evidence cannot be saved under its budget, record `artifact_error` rather than fabricating or silently substituting evidence.

Render code, traces, logs, URLs, and model explanations as escaped text. Never execute them or render untrusted HTML/active Markdown. The artifact route resolves only database-owned IDs, verifies containment and media type, and prevents traversal. Offer traces as local downloads; do not upload them to an outside viewer automatically.

## 12. Inspector behavior

The initial screen shows readiness, the scripted scenario and seed disclosure, its expected checkout behavior, recent jobs, and **Run Chaos**. When only detection is ready, keep the action available with an explicit **Detection only — repair unavailable** label and reason.

After submission, poll the job every second and show completed/current stages: reproduce, diagnose, validate patch, start candidate, verify, clean up. Use observed stage events; do not display invented percentages or simulated activity. Refreshing the page reloads the same persistent job. A network error in the Inspector does not cancel the job or create another one.

The job detail shows:

- Immutable **Observed failure** screenshot beside **Verified result** only when that verification passed; failed candidates are labeled accordingly.
- Attempt selector, escaped source diff, rejected-gate explanations, and assertion checklist.
- Scenario/fixture versions, seed/candidate identity, configured/returned model, latency, token usage when known, and dated estimated cost.
- Clear terminal outcome and cleanup state, with a copyable safe diagnostic.
- Cancel during active work; Reset when idle, including recovery from cleanup quarantine.

Use accessible contrast, text alongside status colors, keyboard-operable controls, and readable code wrapping. Do not use a screenshot alone as proof. If verification passed but cleanup failed, show both facts and no completed GREEN badge.

## 13. Startup, configuration, and operating procedure

Required server configuration: `MODEL_API_KEY` for repair, `FAULTLINE_CONTROL_TOKEN`, fixed Inspector origin, fixture manifest path, data directory, and Docker connection. `META_MODEL_NAME` defaults to Spark Standard. Keep a committed `.env.example` containing names and safe descriptions only; actual secrets stay ignored and server-side.

Implement two top-level commands:

- `./scripts/setup_demo.sh`: validate runtimes, install locked trusted dependencies, resolve/pin images, build the fixed UI/runner/runtime images, generate contracts/fixture manifest, and run non-live checks. No secrets are baked into images.
- `./scripts/run_demo.sh`: validate Docker availability, versions, image/seed/schema integrity, writable data directory and free loopback ports; start controller and prebuilt Inspector under supervision; wait for exact health/readiness; print `http://127.0.0.1:4000`; trap exit to stop owned processes. Start no unrelated processes and kill no unidentified listener.

Model absence does not prevent detection-ready startup. Docker or runner failure blocks jobs with an actionable reason. Avoid Uvicorn import paths containing hyphenated package names: launch from the service working directory with `app.main:app`, rather than treating repository folder names as Python modules. No application hot reload or parallel Uvicorn worker is allowed during demo jobs.

On this machine, the research session observed arm64, Node 26.0.0, Python 3.14.0, Git 2.50.1, and an installed Docker client whose daemon was not running. These observations are not evidence that the controlled Node 24/Python 3.13 runtime images, Meta access, or the application work. Setup must establish those requirements explicitly.

Pre-demo procedure: start Docker, complete setup/preflight, confirm model probe readiness, open Inspector, run the rehearsal gates, then perform the live loop. A recording can be provided as separately labeled demonstration material, but it cannot generate a live verified job or stand in for missing runtime evidence.

## 14. Implementation sequence and ownership

Build the application later in these ordered slices. Each slice produces reviewable behavior before the next depends on it.

| Slice | Owner/responsibility | Exit condition |
|---|---|---|
| 1. Contracts and fixture | Shared-contract owner plus BuggyShop owner | Canonical schemas; healthy business suite; runtime-compiling seed with expected failure |
| 2. Trusted runner | Runner owner | Reports healthy success and seeded failure with immutable artifacts; API/browser oracle reviewed |
| 3. Controller without generation | Orchestrator owner | Durable single job; detection-only flow; idempotency; cancellation; cleanup/restart recovery |
| 4. Candidate policy/runtime | Orchestrator owner | Known test patches pass/reject policy correctly and run only inside the required boundary |
| 5. Meta adapter | Adapter owner | Startup probe; mocked error-contract checks; then separately recorded live proposal/verification |
| 6. Inspector and integration | UI owner plus integration owner | Real progress and evidence, accurate outcomes, protected proxy, no mock live success |
| 7. Rehearsal | Integration owner, independently reviewed | All release gates below pass with actual evidence |

Agents can work in parallel after contracts stabilize, with explicit file/module ownership. They must not redefine shared contracts independently or revert another worker's changes. Contract, verification-oracle, and candidate-policy changes require review by someone other than their author.

Known canned patches may be used only in automated policy/verification tests, clearly identified as test inputs. They never enter the live generation path.

## 15. Acceptance and release gates

The following are proposed acceptance targets. No live repair trials or runtime performance measurements were performed while writing this specification.

### 15.1 Required automated checks

- Canonical schema regeneration is clean; shared positive/negative fixtures agree between Python and TypeScript.
- Fixture/frontend/Inspector builds and relevant typechecks pass in the pinned runtime.
- Healthy reference passes all business cases; seeded reference fails only the declared no-coupon family while its recognized-coupon/catalog controls pass.
- All malformed, empty, oversized, multi-file, traversal, symlink, binary, renamed, mode-changing, and stale-hash patch cases are rejected without mutating the seed/developer checkout.
- Exported candidate contains staged repair bytes, not `HEAD`; provenance binds the actual runtime to those bytes.
- Fake fixes that skip checkout, hide the failure, return generic success/constant totals, fabricate confirmation, or alter tests fail the declared acceptance gate.
- Oracle files/artifacts cannot be modified by candidate code; prompt-injection text cannot expand paths, commands, providers, or request limits.
- Provider 401/402/403, rate limit, malformed/refused/truncated output, timeout, and unavailable model yield accurate outcomes without hidden fallback/retries.
- Direct unauthenticated controller calls and cross-origin/invalid-CSRF mutations fail; artifact traversal/HTML injection fails.
- Idempotent retries create one job; conflicting keys/new busy submissions behave as specified.
- Stop backend, break candidate syntax, serve the wrong generation, kill the worker/controller, cancel each stage, fail artifact persistence, and fail cleanup: each produces the declared result and recovery behavior.
- A cleanup failure after verification prevents GREEN and blocks another job until confirmed reset.
- Candidate containment probes pass. Pin Playwright package/browser image compatibility and verify startup health, not just an open port. [Compose readiness distinction](https://docs.docker.com/compose/how-tos/startup-order/)

### 15.2 Rehearsal gates

1. Reproduce the seeded failure in **10/10** fresh resets with the expected fingerprint and evidence.
2. Run **ten live repair jobs** on the target machine, with pinned model/settings, source, fixtures, dependencies, and no manual source edits. Target at least **9/10 verified jobs**, each within two generation requests and the deadline.
3. Require the final **three consecutive jobs** to complete successfully with full evidence and cleanup.
4. Report success numerator/denominator, first-request success, within-two-request success, every failure category, per-job duration, observed median/maximum, usage, and advisory cost. Do not infer a stable p95 or general repair accuracy from this small seeded sample.
5. Confirm no container/browser accumulation and inspect memory pressure across the run set.

The release report must list tests the model saw, withheld inputs, oracle author/reviewer, and known coverage limits. Passing the gates earns a controlled-demo claim only. If a gate fails, document the actual result and fix/retest it; do not relax or relabel evidence silently.

## 16. Extension path after v1

The next slice may add a frontend whitespace-search runtime bug, with explicit empty-query behavior, a build-compatible seed, frontend build/restart verification, and its own protected oracle and time budget. Add it only after v1 passes rehearsal; do not add it to v1's success denominator retroactively.

Broader source localization, arbitrary repositories, remote workers, change promotion, authentication/multi-tenancy, and production operation each need a separate spec. Preserve the adapter, registry, runtime, and evidence boundaries so those additions do not require changing the meaning of a verified result.
