# Agent handoff state

- Updated: October 26, 2026 (America/New_York).
- Branch: `FrankieBiz/apex-orchestration-setup-model`.
- Backend owner: OpenAI GPT-6.1 via Codex.

## Completed backend scope

Canonical contracts and the scenario registry are in `shared/`. The FastAPI
fixture, strict request validation, catalog, thread-safe namespace storage, and
tests are in `apps/buggyshop-backend/`. Healthy and seeded checkout snapshots,
SHA-256 metadata, and a fail-closed verifier are in `fixtures/`. Run `make check`
from the root, or `uv run --python 3.13 --locked pytest` in the backend directory.

`make check` passed on Python 3.13.16: 153 tests, Ruff lint/format, strict mypy
(25 files), fixture provenance, and wheel/source distribution builds. This is
backend verification only; no browser, controller, model, Docker containment,
or full hackathon rehearsal has been validated.

## Settled interfaces

- The explicit backend task supersedes SpecV1's differing coupon names,
  statuses, scenario ID, and order field examples. Do not silently combine them.
- Scenario: `scripted_checkout_repair`. Repair target:
  `apps/buggyshop-backend/app/routes/checkout.py`.
- Catalog products: `id`, `name`, `price_cents`; mug 1999, notebook 1500.
- Checkout: `items: [{product_id, quantity}]`, optional `coupon_code`.
  Quantities are strict integers 1–10; one or two distinct known products;
  undeclared fields rejected with 422.
- Coupons: trimmed/uppercased `TENOFF` (10%) and `FIFTEEN` (15%); discount
  truncated to integer cents. Unknown nonempty coupon returns 400.
- Orders: `id`, `line_items`, `subtotal`, `discount`, `total`. Line items use
  `product_id`, `quantity`, `unit_price_cents`, `line_total_cents`.
- `GET /api/orders` returns `{orders: [...]}`; order-by-ID readback is also
  available. Both use `X-Faultline-Case-Id`, default `demo`.
- Missing/null/empty/whitespace coupon deliberately raises TypeError during
  subtraction. HTTP 500 exposes its exact fingerprint without a traceback;
  backend logs retain the traceback and request/case correlation. No order is
  stored. The live route must remain byte-identical to the seeded snapshot.
- The healthy snapshot differs only by the discount lookup default. It is
  loaded independently in tests; tests never rewrite the live route.
- Canonical contracts forbid extra fields and scalar coercion. Decode wire
  data with `model_validate_json`; timestamps require timezone and normalize
  to UTC. Unknown token usage is null.

## Resolved verification issues

- Current Starlette TestClient prefers `httpx2`; it is a locked dev dependency
  alongside the task-required `httpx`. Keep warnings-as-errors enabled.
- Ruff needs explicit first-party imports for `app`, `shared`, and `fixtures`.
  Otherwise it sorts snapshot imports differently from the runtime route and
  breaks provenance. Format source before generating the manifest.
- The installed global `agent-finish` stages unrelated files and uses a
  different identity from this project's instructions. Use a task-scoped
  `git finish` with author/committer `Francis Bisignano
  <frankabisignano@gmail.com>` and explicit backend paths.

## Concurrent work and next steps

Existing `AGENTS.md` edits and `.agents/skills/hackathon-judge/` were present at
startup. Frontend files appeared concurrently during backend implementation.
These belong to other work; preserve them and exclude them from backend commits.

The source-containing revision is `44b2a13b412588de7596ef0f3bb2d1aae47799a5`;
`fixtures/manifest.json` pins that actual commit and both reference-file hashes.
The revision contains the live seeded route and both reference snapshots.
Future setup/runtime work should use this pinned commit and exclude healthy
source, provenance tooling, and tests from candidate exports. Shared contracts
and verification oracles still require independent review before release.

## Repair orchestrator implementation — October 26, 2026

The controller implementation lives in `services/repair-orchestrator/`. It uses
canonical additive schemas from `shared/contracts/models.py`; existing Job and
ExecutionReport fields remain compatible. `ExecutionVerdict` additionally permits
`timed_out`. Root `make check` now checks both Python services in separate processes
to avoid their intentionally identical `app` import names.

Implemented and verified:

- Atomic SQLite admission/idempotency, durable singleton lease, cancellation,
  ordered event allocation, immutable executions, and cleanup quarantine/reset.
- Strict single-file exact-hunk policy, AST capability/syntax checks, real detached
  seed worktrees, Git indexed application, and staged application-only exports.
- Meta Chat/schema adapter with bounded wire data, startup catalog/nonce probe,
  safe provider errors, and no implicit fallback after provider failures.
- The explicit task's absent-key/explicit deterministic fallback overrides
  SpecV1's original prohibition. Its provider identity is exposed and recorded;
  deterministic results must never count as live Meta repair trials.
- Seven-stage serial worker, monotonic budgets, at most two attempts, cleanup,
  restart interruption, authenticated API, SSE replay, and durable inert artifacts.
- `make check` passed: **171 orchestrator tests + 153 fixture tests**, Ruff
  lint/format, strict mypy, unchanged pinned fixture provenance, and both builds.
  The simulated hero test checks the actual exported FastAPI API in test-only
  host subprocesses. Browser screenshots/traces in simulations are labeled test
  data; no live browser, Docker containment, or hosted Meta trial was performed.

Integration remains blocked deliberately: `app.runtime.Runtime` is the typed seam
for the future isolated container/browser adapter. `UnavailableRuntime` is the
production default, so readiness is blocked and live admission returns 503 instead
of executing candidate code on the host. Inject a real runtime only after its
trusted runner, evidence collection, and containment checks exist. See the service
README for the exact required methods, assertion manifest, settings, and routes.

The concurrently appearing `tools/browser-runner/` currently follows SpecV1's
`checkout-flow`/`DEMO10` and hand-written extended TypeScript report contract. It
must align with the settled backend interfaces and generated shared contracts,
and implement the fixed request-file interface before integration. Preserve its
owner's current work. Contract/policy/oracle changes still need independent review
before release, as required by SpecV1; these tests are not that independent review.

Existing AGENTS.md edits, `.agents/skills/`, frontend, and browser-runner work were
not authored as part of this task and are excluded from the orchestrator commit.
Use a scoped `git finish` override for the project-required Francis Bisignano
identity; the global `agent-finish` still stages unrelated files and sets a
different identity.
