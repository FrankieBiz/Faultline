# FaultLine repair orchestrator

A FastAPI control plane with transactional SQLite admission, a serial repair worker,
strict single-file patch policy, bounded Meta Chat requests, explicit deterministic
repair, durable evidence, and resumable SSE events.

Run from the repository root with Python 3.13:

```bash
uv sync --project services/repair-orchestrator --python 3.13 --locked
# Supply FAULTLINE_CONTROL_TOKEN through the server environment.
uv run --project services/repair-orchestrator --python 3.13 --locked python -m app.main
```

The controller binds `127.0.0.1:9000`, uses one worker, and requires Bearer
authentication for all registered controller endpoints. `/healthz` is public.
Documentation/schema routes are disabled. This is a monorepo service: the checkout's
canonical `shared/` contracts and pinned `fixtures/` provenance must be available.
When launching from the service directory, set `PYTHONPATH=../..`.

## Configuration

| Variable | Meaning |
| --- | --- |
| `FAULTLINE_CONTROL_TOKEN` | Required controller credential; keep server-side. |
| `FAULTLINE_DATA_DIR` | SQLite, retained evidence, and disposable runtime exports; defaults to repository `data/`. |
| `FAULTLINE_INSPECTOR_ORIGIN` | Exact allowed CORS origin; defaults to `http://127.0.0.1:4000`. |
| `META_API_KEY` | Hosted Meta credential; takes precedence over the `MODEL_API_KEY` compatibility alias. |
| `META_BASE_URL` | Provider base URL; defaults to `https://api.meta.ai/v1`. |
| `META_MODEL_NAME` | Exact model ID; defaults to `muse-spark-1.3`. `Llama-3.3-70B-Instruct` requires explicit configuration and a successful probe. |

Missing model credentials select the **identified deterministic fallback**, as
required by this service's implementation task. Callers of the Python adapter can
also explicitly request `fallback=True`. This overrides SpecV1's original prohibition
on a canned live generation path. Provider errors never silently select fallback.
Fallback proposals and successful attempts record `provider=deterministic`; they
must not be counted as live Meta repair trials. Startup Meta probing consumes its
own real catalog request and generation and logs its timestamp/result/usage.

## HTTP routes

All controller routes begin with `/api/faultline`:

- `POST /jobs`: `{scenario_id, idempotency_key, mode?}`, returning 202 with `job_id`.
- `GET /jobs?limit=20`: latest jobs, bounded to 1–100.
- `GET /jobs/{id}`: job, baseline, attempts, executions, public artifact metadata, events.
- `GET /jobs/{id}/events`: `text/event-stream`; resume with `Last-Event-ID` or `?after=`.
- `POST /jobs/{id}/cancel`: 202 while active; 200 with unchanged terminal history.
- `POST /reset`: idle reconciliation; active jobs return 409; failed cleanup retains quarantine.
- `GET /readiness`, `GET /scenarios`, `GET /artifacts/{id}`: component status, registry, and verified inert evidence downloads.

The existing canonical scenario is `scripted_checkout_repair`. The previous backend
handoff's `TENOFF`/`FIFTEEN` coupons, response fields, and validation statuses remain
authoritative. Submission does not accept paths, commands, URLs, or model settings.
Idempotency is checked before readiness/busy checks; the same key with changed
semantic input returns 409. Admission, lease reservation, and the first event commit
in one transaction. Failed admission leaves no orphan queued job.

## Runtime integration boundary

`app.runtime.Runtime` is the typed integration seam for the isolated backend and
trusted browser runner. Its default `UnavailableRuntime` reports blocked readiness
and rejects job admission with 503 `isolated_runtime_unavailable`. There is no
production switch that executes candidate code on the host and no HTTP switch
that installs a test runtime. `create_app(runtime=...)` is a trusted Python
composition hook for the future container adapter.

The browser runner currently being developed elsewhere in this checkout uses
different scenario/contracts and lacks the fixed `--request` interface. Connecting
it requires aligning its generated contracts and named verification assertions,
implementing the isolated container profile, and passing containment checks.
This service does **not** claim live browser, container, or hosted Meta repair
validation. A healthy HTTP process alone does not imply repair readiness.

A runtime implementation must:

- Persist/label owned resources with installation, job, and snapshot generation IDs
  before creation; avoid inheriting controller/model credentials.
- Start fresh isolated baseline/candidate processes with read-only snapshot mounts,
  empty order stores, fresh browser contexts, and trusted case namespaces.
- Execute only the fixed oracle once, honor cancellation/deadlines, and return a
  canonical report plus observed generation/hash and matching exit code.
- Supply actual screenshot, trace, request metadata, and correlated backend logs.
  Report identity, mandatory assertions, evidence roles, byte caps, and hashes are
  validated by the controller. Required assertion IDs are defined by the existing
  scenario and `app.runtime.REGRESSION_ASSERTIONS`.
- Confirm installation-scoped cleanup/reconciliation. Cleanup failure quarantines
  admission; reset retains all reports and artifacts.

Snapshots are real detached worktrees from the fixture's pinned seed commit.
Git performs `apply --check --index` and `apply --index`; exports come from the
staged index. Only backend application Python files enter candidate snapshots.
The host parses candidate ASTs but never imports or executes candidate code.
AST checks are bounded policy, not process isolation.

## Verification

```bash
cd services/repair-orchestrator
uv run --python 3.13 --locked pytest
uv run --python 3.13 --locked mypy
```

Root `make check` verifies both backend services independently, including Ruff,
strict mypy, tests, fixture provenance, and distribution builds. Tests inject
explicit runtime simulations. The hero test additionally executes the exported
seed/candidate in **test-only host subprocesses**, measuring the real fixture API
against independent pricing/validation assertions. Screenshot/trace bytes in these
simulations are labeled test data; they are not browser evidence or containment
proof. Production cannot select these simulations.

Deadlines use a monotonic clock: preparation/baseline 20 seconds, each attempt
75 seconds, generation 45 seconds, verification 20 seconds, work cutoff 170 seconds,
overall 180 seconds, and a final cleanup reserve of 10 seconds. Up to two generation
attempts are permitted, and a second requires a complete remaining attempt budget.
Controller-enforced runner timeouts persist `timed_out` reports without inventing
missing evidence. Only verified behavior plus durable evidence and confirmed
cleanup can finalize `state=succeeded, outcome=verified`.
