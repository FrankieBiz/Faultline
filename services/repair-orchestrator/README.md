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
| `FAULTLINE_AGGREGATE_LIMITS` | `required` (default) or `disabled`. Required runs every candidate backend in a verified cgroup v2 user scope and withholds readiness if that cannot be established or enforced. Any other value withholds readiness. |
| `META_API_KEY` | Hosted Meta credential; takes precedence over the `MODEL_API_KEY` compatibility alias. |
| `META_BASE_URL` | Provider base URL; defaults to `https://api.meta.ai/v1`. |
| `META_MODEL_NAME` | Exact model ID; defaults to `muse-spark-1.3`. `Llama-3.3-70B-Instruct` requires explicit configuration and a successful probe. |
| `META_REASONING_EFFORT` | `low` (default, documented for Muse Spark Chat), `medium`, `high`, or `none` to omit the field for models that reject it. |
| `META_RESPONSE_FORMAT` | `json_schema` (default, strict schema) or `json_object` for compatible endpoints without JSON Schema support. Every response is still validated locally against the strict `PatchProposal` contract. |
| `META_TIMEOUT_SECONDS` | One generation request's wall-clock bound, 5–180 seconds (default 45). The controller's 45-second generation budget still applies to repair jobs. |

Provider identity is derived from the endpoint host, never from variable names.
Only `meta.ai`, `meta.com`, and `llama.com` hosts (or their subdomains) are labeled
`meta`; loopback endpoints are `local`, and any other host is `openai-compatible`.
An attempt records `provider`/`model` only from a returned response. The endpoint
it was sent to is kept separately as `dispatched_provider`/`dispatched_model`, so a
provider error is never counted as model output.

Missing model credentials select the **identified deterministic fallback**, as
required by this service's implementation task. Callers of the Python adapter can
also explicitly request `fallback=True`. This overrides SpecV1's original prohibition
on a canned live generation path. Provider errors never silently select fallback.
Fallback proposals and successful attempts record `provider=deterministic`; they
must not be counted as live Meta repair trials. Startup Meta probing consumes its
own real catalog request and generation and logs its timestamp/result/usage.

## Repair attempts and gate feedback

The system prompt states the checkout business contract (catalog prices in integer
cents, coupon normalization, floored percentages, HTTP 400 for unknown coupons,
single stored order) rather than the seeded defect or its fix. The user message is
untrusted evidence: the current source, its SHA-256, and the failure.

At most two attempts run. When an independent gate rejects the first, the second
receives bounded findings as untrusted evidence: the gate name, the policy error,
up to twelve failing assertions with expected and observed values (240 bytes per
field), and up to 4 KiB of the rejected diff. Gates that feed back are patch
policy, candidate start-up, verification, and the adapter's own proposal contract
(malformed or out-of-scope output). Transport errors and timeouts retry without
findings. Each attempt records `prior_feedback`, `generation_ms`, and
`diff_recounted`.

The patch policy also rejects catch-all exception handlers (bare `except`,
`except Exception`, `except BaseException`), which suppress failures instead of
repairing them. Specific handlers remain allowed; the oracle judges their effect.

After a candidate is verified, the worker stores a `proof_bundle` (JSON) and
`proof_bundle_md` (review summary). The bundle restates the recorded verdicts,
patch, and every artifact's id, role, size, and SHA-256 under one digest;
`tools/verify_bundle.py` re-checks it offline against exported artifacts. The digest
is a checksum, not a signature. A compilation fault is logged and leaves the
verified outcome unchanged.

Models often miscount unified-diff hunk headers. Like `git apply --recount`, the
adapter recomputes hunk line counts from the hunk body and relocates a hunk only to
the single exact occurrence of its old lines in the source. It never edits content
or matches fuzzily. The strict policy then validates the result unchanged. The
model's own output is retained in `raw_patch` and the `proposal` artifact, and
`parsed_diff` holds the diff the gates checked.

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

The default `UnavailableRuntime` blocks execution with HTTP 503. Set
`FAULTLINE_RUNTIME=isolated` to select `IsolatedRuntime`; the demo launcher does this
explicitly. The old host-execution demo adapter has been removed. Python tests can
still inject labeled simulations via `create_app(runtime=...)`.

The isolated implementation requires Linux, Bubblewrap, working unprivileged
user namespaces, the built storefront/runner, and installed Playwright Chromium.
With the default aggregate limits it also requires cgroup v2 and a reachable
systemd user manager (`systemd-run`, `systemctl --user`, and `XDG_RUNTIME_DIR`)
that delegates the memory, pids, and cpu controllers. The controller should run
inside that manager's cgroup subtree, for example as a user service or from a
desktop terminal. From a login-session scope such as plain SSH, the manager
typically cannot move processes into a user scope; readiness then reports
`aggregate_limits_unavailable`.
Startup launches the actual isolation profile, an aggregate-limit enforcement
probe, and the trusted browser to establish readiness. Candidate code receives
readonly source/interpreter/library mounts, private process/network namespaces,
bounded private tmpfs, per-process resource limits, an aggregate cgroup v2 scope,
and a prebound backend listener FD. The trusted frontend, HTTP assertions, and
browser runner execute outside the candidate boundary and outside its scope. No
host-writable directory or model/controller credential is mounted into it.

Evidence consists of actual screenshots, trace ZIPs, bounded request logs, correlated
backend logs, and measured assertions. HTTP response bytes are bounded while
streaming. Liveness pipes supervise owned subprocess groups through cancellation
and controller exit; scratch resources stay under the job-owned snapshot runtime.
The output is a verified candidate, not a deployed production checkout.

### Aggregate resource limits

Each candidate backend's Bubblewrap launch runs under `systemd-run --user --scope`
as `faultline-<installation>-<generation UUID>.scope`, where `<installation>` is
the installation ID's lowercase alphanumerics (up to 64). Backend-only
evaluation sessions launched before any reconciliation use `evaluation` instead.
These limits cover every task in the scope together:

| Property | Value | Kernel file checked |
| --- | --- | --- |
| `MemoryMax` | 512 MiB | `memory.max` |
| `MemorySwapMax` | 0, so pressure cannot move to swap or zram | `memory.swap.max` |
| `TasksMax` | 64 processes and threads | `pids.max` |
| `CPUQuota` | 100% of one CPU | `cpu.max` |
| `OOMPolicy` | `kill`, so an OOM kills the whole scope | `memory.oom.group` |

- **Launch.** `systemd-run` execs in place, so the existing supervisor still owns
  the process group. Only `XDG_RUNTIME_DIR` and, if set, `DBUS_SESSION_BUS_ADDRESS`
  are passed to it. `env -i` then empties the environment before Bubblewrap starts.
  This matters because a candidate can read Bubblewrap's initial environment at
  `/proc/1/environ`. The candidate itself still sees only the profile's variables.
- **Verification, not assumption.** Before the backend may answer requests, the
  controller must observe the scope active and read the five kernel files above;
  every value must equal the configuration. A scope that never appears is a
  trusted-infrastructure failure, never a candidate verdict. After `/healthz`,
  the values are read again and the scope's `cgroup.procs` must match the
  supervised launch's process tree exactly. Any mismatch rejects the generation. The kernel's values are returned
  as `RuntimeExecution.resource_limits`, a `ResourceLimits` record with
  `verified=true`. `ExecutionRecord.resource_limits` is optional, so earlier
  records still load; a missing value means unknown, never enforced.
- **Enforcement preflight.** Before readiness, a probe scope runs a sandboxed
  interpreter with no rlimits under 64 MiB, no swap, and 16 tasks. A child
  process allocates 256 MiB, then the parent tries to start 64 threads. Readiness
  needs four things. The child must die from SIGKILL. The scope's own
  `memory.events` `oom` and `oom_kill` counters must rise. Thread creation must
  stop below the task limit. The scope's `pids.events` `max` counter must rise. A
  global OOM or an rlimit cannot raise these scope counters. The probe uses
  `OOMPolicy=continue` only so its counters stay readable. The CPU quota is
  configured and read back, but its throttling is not probed.
- **Cleanup.** Cleanup confirms that the unit no longer exists. An OOM-failed unit
  is reset first. After a one-second grace period, only that unit is sent
  SIGKILL. Unconfirmed removal keeps ownership, so the cleanup quarantine applies.
  Reconciliation releases leftover scopes with this installation's prefix and
  never touches other units.
- **Modes and readiness.** `disabled` skips the scope and the probe. Readiness
  then reports `resource_limits.mode="disabled"`, and every
  `RuntimeExecution.resource_limits` has `mode="disabled"` and `verified=false`. In required
  mode, readiness is blocked with `aggregate_limits_unavailable` or
  `aggregate_limits_not_enforced` when limits cannot be established or enforced.
  An unknown mode blocks it with `aggregate_limits_mode_invalid`.
  `GET /readiness` includes `resource_limits`, which lists the requested mode,
  configured limits, preflight result, and the probe's measured counters.
- **Evaluation.** `IsolatedRuntime.backend_preflight()` and
  `backend_session(application)` run one backend alone through this same scoped
  launch path, without needing a browser build.

Bubblewrap is invoked with an explicit `--unshare-user`, because `--unshare-all`
only tries a user namespace; the profile preflight asserts that the sandbox's
user and network namespaces differ from the controller's. The backend launcher
formats every log record, including uncaught tracebacks that echo candidate
source, as one escaped JSON line, so candidate text cannot forge a correlated
server event.

These are cgroup accounting limits plus Linux namespaces on a shared host kernel.
They are not a VM. Per-process rlimits remain inside the namespace as a second
layer. The scope does not limit disk I/O, and kernel and systemd defects are
outside its protection. An internal, AI-assisted adversarial review on
October 27, 2026 confirmed the memory, task, environment, filesystem, network, and
cleanup defenses with real probes. Its remaining items are accepted residual risks:
no seccomp filter is applied, so the full syscall surface of the shared kernel is
exposed; the candidate's abstract listener lives in the host network namespace,
where another local process could connect to it by its random name; and trusted
parsers outside the sandbox (HTTPX, the uvicorn bridge, Chromium) read
candidate-influenced bytes. An external review is still warranted before
expanding to arbitrary applications or exposing job submission publicly.

## Evaluation harness

`app.evaluation` measures the gates and the configured provider on the hash-pinned
corpus in `fixtures/evaluation/` (see `docs/EVALUATION.md`). It reuses this
adapter, patch policy, oracle, and feedback loop, and runs every variant and
candidate through `IsolatedRuntime.backend_session`. It refuses to run unless the
aggregate-limit preflight passed, unless `--allow-disabled-limits` is given, and
results record the limits each session actually had.

```bash
./scripts/evaluate.sh --suite all            # deterministic unless a provider is configured
./scripts/evaluate.sh --suite holdout --repeat 3
```

Results are checkpointed after every case to `data/evaluations/<UTC time>/`
(`results.json` and `summary.md`), and an interrupted run is marked incomplete.

The typed runtime contract remains:

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
Git performs `apply --unidiff-zero --check --index` and `apply --unidiff-zero --index`;
exports come from the staged index. Only backend application Python files enter candidate snapshots.
The controller parses candidate ASTs; candidate imports run only in the restricted namespace.
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
proof. Production cannot select these simulations. Executions record `runtime_kind`; historical records without isolated browser provenance remain unverified in the Inspector.

Deadlines use a monotonic clock: preparation/baseline 20 seconds, each attempt
75 seconds, generation 45 seconds, verification 20 seconds, work cutoff 170 seconds,
overall 180 seconds, and a final cleanup reserve of 10 seconds. Up to two generation
attempts are permitted, and a second requires a complete remaining attempt budget.
Controller-enforced runner timeouts persist `timed_out` reports without inventing
missing evidence. Only verified behavior plus durable evidence and confirmed
cleanup can finalize `state=succeeded, outcome=verified`.

Run the required isolated browser checks after building dependencies:

```bash
make integration
```

This target fails if containment or Chromium is unavailable. The general test suite
may skip environment-dependent browser cases on unprepared machines; those skips
do not establish isolated runtime correctness. Real aggregate-limit tests, including
memory and task hogs, live in `tests/test_resource_limits_cgroup.py`. Run them with
`FAULTLINE_REQUIRE_ISOLATED_TESTS=1` to fail rather than skip.


## Project execution

`faultline run [scenario_name] [--config faultline.toml]` uses the same durable worker
with a project-scoped scenario registry, immutable tracked-source exports, two
fresh baseline sessions, contained Meta inference, and the general sandbox runtime.
`--repro path.json --target path/to/source` selects an external ReproSpec;
`--detect` measures without inference. See [the complete configuration and limits](../../docs/PROJECT_RUNNER.md).

For HTTP admission, set `FAULTLINE_CONFIG` and optionally `FAULTLINE_SCENARIO`.
Only the selected operator-owned configuration is admitted; HTTP callers cannot
supply commands or paths. The default controller continues to serve the checkout demo.
