# FaultLine developer platform: DX, TUI, configuration, CI, and transition spec

**Status:** Proposed design, October 30, 2026. Awaiting owner approval. Sections 2–8 describe intended behavior and are not implemented unless marked **exists today**. Terminal mockups show literal screen designs with illustrative values. They are not recorded results and do not imply a live Meta trial (none has been recorded; see [PROJECT_STATUS.md](PROJECT_STATUS.md)).

**Goal:** Turn FaultLine from a seeded-shop demo into a CLI that developers point at their own repositories. The engine stays the same: reproduce, propose, gate, verify in isolation, then deliver evidence. BuggyShop becomes the showcase fixture, and the Inspector becomes an optional local dashboard.

## 0. Non-negotiable floors

These rules come from settled decisions and existing code. No config key, flag, or environment variable can relax them.

| # | Floor | Source today |
| --- | --- | --- |
| F1 | **No reproduction, no repair.** The model is never called until a declared invariant has reproduced the failure in the sandbox. If nothing reproduces, the outcome is `no_failure` and no patch is proposed. | `worker.py` baseline stage, `TerminalOutcome.NO_FAILURE` |
| F2 | **No repository code runs on the host.** This covers init, test discovery, setup, baseline, and candidates. If the sandbox is unavailable, FaultLine fails closed. | `UnavailableRuntime`, `RuntimeUnavailable` |
| F3 | **The oracle is out of the patch's reach.** Patches that touch `faultline.toml`, `.faultline/**`, declared invariants, tests, lockfiles, `.git/**`, `.github/**`, or `.env*` are rejected before execution. | Separate export of application files from tests and references (README gate 5) |
| F4 | **Provider identity comes from the endpoint host** and is recorded only when that provider actually returned a response. The `provider` config key is only a preset; it never labels evidence. | `ModelSettings.provider` |
| F5 | **No silent fallback.** A configured provider that fails produces `model_error`. The deterministic adapter is available only for the showcase fixture. | `model_adapter.py` module docstring |
| F6 | **Aggregate limits are required by default.** Disabling them takes `mode = "disabled"` in config plus `--allow-disabled-limits` on each run, and is refused in CI. | `ResourceLimits`, HANDOFF settled decisions |
| F7 | **Built-in AST floor:** dangerous names and attributes, plus catch-all exception handlers, are always rejected. Config can add denials but cannot remove any. | `policy._DANGEROUS_NAMES`, `_DANGEROUS_ATTRIBUTES`, `_catches_everything` |
| F8 | **FaultLine never deploys or pushes to a default branch.** Delivery stops at a working-tree change, a local branch, or a draft PR. | README "does not deploy to production" |

## 1. What exists today and where it surfaces

Each hardcoded value below becomes a config key or command. The showcase fixture's config (§4.5) is required to reproduce these values exactly (§9.2 drift test).

| Hardcoded today | Location | Platform surface |
| --- | --- | --- |
| Repair target file | `policy.TARGET_FILE`, `fixtures/provenance.py`, `fixtures/evaluation/corpus.py`, `snapshots.BACKEND_APP` | `[repair].editable` |
| Import allowlist | `policy._IMPORTS` | `[repair.imports].allow` |
| Diff, source, and line caps (16 KiB, 32 KiB, 100 lines) | `policy.MAX_*` | `[repair].max_*`, under hard ceilings |
| Scenario, route, error fingerprint, expected assertion IDs | `shared/config/scenarios.py` `REGISTRY` | `[[invariants.*]]`, `fingerprint` |
| Browser journey and independently derived prices | `tools/browser-runner/src/scenario.ts`, `oracle.ts` | `[[invariants.journey]]` |
| 27 HTTP business assertions plus confirmation | `app/http_regression.py`, `runtime.REGRESSION_ASSERTIONS` | `[[invariants.rule]]`, `[[invariants.test]]` |
| Stage budgets (preflight 45 s, baseline 20 s, attempt 75 s, generation 45 s, verification 20 s, work 170 s, cleanup 10 s, overall 180 s) | `worker.Budgets` (`preflight` exists on `main`) | `[budgets]` |
| Aggregate limits (512 MiB, no swap, 64 tasks, one CPU) | `isolated_runtime.py` | `[sandbox.limits]` |
| Model endpoint, effort, format, timeout | `ModelSettings.from_environment` (`META_*`) | `[model]`; env vars still override |
| One feedback-guided retry, at most 12 failed checks fed back | `worker.py`, `model_adapter.py` | `[model].max_attempts` |
| Service launch and loopback ports | `scripts/start-demo.sh` | `[project]`, `[[project.service]]`, `faultline up` |
| Bundle verification, replay export, trial ledger, evaluation | `tools/verify_bundle.py`, `scripts/export_replay.py`, `scripts/trial_ledger.py`, `scripts/evaluate.sh` | `faultline packet verify`, `faultline replay export`, `faultline bench trials`, `faultline bench corpus` |
| Inspector | `web/inspector-ui` | `faultline dashboard` |
| `[scenarios.*]` ReproSpecs (request steps), `[[invariants.rule]]` HTTP rules (both the `faultline init` form and the §4.3 `request`/`assert` form), and ad-hoc probes, checked live against a running service through `ReproEngine` in two fresh sessions (**exists today**, October 30) | `app/probes.py`, `GET /scenarios`, `POST /invariants/{id}/check` | Inspector scenario rail. Repair stays limited to registered scenarios until Phase 1 |
| Control API (`/api/faultline/readiness`, `/jobs`, `/jobs/{id}/events` SSE, `/cancel`, `/artifacts/{id}`) | `app/main.py` | Phase 0 CLI transport |

## 2. Installation

### 2.1 Channels

| Channel | Command | What it does | Phase |
| --- | --- | --- | --- |
| uv (primary) | `uv tool install faultline` | Isolated tool environment and a `faultline` shim on PATH. Matches the repo's uv toolchain. | 1 |
| pipx | `pipx install faultline` | Same wheel, same result. | 1 |
| Script | `curl -fsSL https://faultline.dev/install.sh \| sh` | A thin wrapper over uv (details below). | 2 |
| npm | `npm install -g faultline` | A shim that runs `uvx faultline@<pinned>`. It contains no second engine and is for JS-first teams only. | 3 |
| From source (now) | `git clone … && make setup` then `uv run --project services/repair-orchestrator faultline …` | Phase 0 entry point. | 0 |

**Unverified:** Nobody has checked whether `faultline` is available on PyPI or npm, or whether the owner controls `faultline.dev`. Reserve the names, or fall back to `faultline-cli`, before publishing anything. Never publish an install script on a domain the owner does not control.

The install script:

- Detects OS and architecture.
- Reuses `uv` if present, or installs it into `~/.local/bin`.
- Runs `uv tool install faultline==<version>` and checks the wheel's SHA-256 against the release's `SHA256SUMS`.
- Never uses sudo.
- Supports `--dry-run`, `--version X.Y.Z`, and `--no-modify-path`.
- Ends by printing the steps below.

```text
$ curl -fsSL https://faultline.dev/install.sh | sh
FaultLine installer
  platform    linux x86_64 (Fedora 44)
  uv          found at ~/.local/bin/uv
  install     uv tool install faultline==0.3.0
  checksum    faultline-0.3.0-py3-none-any.whl matches SHA256SUMS
  installed   ~/.local/bin/faultline

Missing system package (FaultLine will not use sudo):
  bubblewrap  →  sudo dnf install bubblewrap

Next:
  faultline doctor            check sandbox, browser, and model access
  cd ~/code/your-app && faultline init
```

### 2.2 Packaging blockers found in the current code

1. `services/repair-orchestrator/pyproject.toml` ships `packages = ["app"]`. The code also imports `shared.contracts.models`, `shared.config`, and `fixtures.provenance` from the repo root via `pythonpath = ["../.."]`, so the built wheel cannot run on its own. On top of that, a top-level `app` package would collide with users' own `app` packages. **Fix (Phase 1):** use a single `faultline` distribution with an `src/` layout:
   - `faultline.engine` (from `app/`)
   - `faultline.contracts` (from `shared/contracts/`)
   - `faultline.config` (replaces `shared/config/`)
   - `faultline.cli`
   - `faultline.tui`
2. `pytest` and `pytest-asyncio` are in runtime `dependencies`. Move them to the dev group.
3. The trusted browser runner is TypeScript and needs Node 24 or later. Bundle it as a single `faultline-runner.mjs` in the wheel's package data. `doctor` checks for Node. Chromium installs to the Playwright cache via `doctor --fix` (user-level).

### 2.3 Global state locations

| Path | Contents |
| --- | --- |
| `~/.config/faultline/config.toml` | User defaults: preferred provider, editor, theme. Never secrets. |
| `~/.local/share/faultline/` | Engine database, disposable worktrees, setup caches keyed by lockfile digest |
| `$XDG_RUNTIME_DIR/faultline/` | Control token (0600) and the socket of a running engine |
| `<repo>/faultline.toml` | Project config, committed |
| `<repo>/.faultline/journeys/`, `.faultline/payloads/` | Invariant sources. Committed and always protected. |
| `<repo>/.faultline/runs/` | Run packets. `init` adds this to `.gitignore`. |

### 2.4 `faultline doctor`

Doctor runs every check, even after a failure. `--json` emits the same results. `--fix` performs user-level actions only: Chromium install and directory creation. For system packages it prints the exact `sudo dnf install` command. Exit codes: 0 when ready, 78 for config errors, 30 when the host is not ready.

```text
$ faultline doctor
Host
  ✓ Linux x86_64 · Fedora 44
  ✓ git · uv · Python 3.13
  ✓ Node.js 24 (trusted browser runner)
  ✓ Chromium in Playwright cache
Sandbox · engine bwrap
  ✓ bubblewrap with unprivileged user namespaces
  ✓ systemd user manager reachable
  ✓ cgroup v2 controllers delegated: memory pids cpu
  ✓ enforcement probe: memory kill at 512 MiB, task cap at 64, read back from kernel
Model · meta · muse-spark-1.3
  ✓ META_API_KEY is set (value never shown)
  ✓ probe: available · identity meta (host api.meta.ai)
Config · faultline.toml
  ✓ schema 1 · 1 journey · 1 rule · 1 test suite · 10 protected paths

Ready. Run `faultline run` to reproduce and repair.
```

A failing check looks like this:

```text
  ✗ cgroup v2 controllers delegated: memory pids · missing: cpu
    Candidates cannot run without enforced aggregate limits, so FaultLine fails closed.
    Run from a desktop terminal or a systemd user service, not a bare SSH login.
    Details: faultline doctor --explain limits
```

## 3. `faultline init`: the onboarding wizard

### 3.1 Principles

- Detection proposes and the developer confirms. Every detected value appears next to its evidence ("from pyproject.toml").
- Anything that executes repository code happens in the sandbox (F2). That includes running the test command, collecting tests, installing dependencies, and probing the health URL. If the sandbox isn't ready, `init` stops after `doctor` with the fix.
- Secrets are never typed, echoed, or written. The wizard records an environment variable name and checks only whether it is set.
- A model probe sends one request and says so before sending it.
- The wizard ends with a reproducible failure if one exists, so the next command is obvious.

### 3.2 Transcript

```text
$ cd ~/code/acme-storefront && faultline init

FaultLine 0.3.0 · set up verified repair for this repository.
Repository code runs only inside the sandbox, including during setup.

Repository  ~/code/acme-storefront · git · branch main · clean
Sandbox     bwrap · limits probe passed (512 MiB · 64 tasks · 1 CPU)

Detected
  ✓ Python 3.13 app            pyproject.toml, uv.lock · fastapi in dependencies
  ✓ Next.js frontend in web/   web/package.json, web/package-lock.json
  ✓ pytest                     [tool.pytest.ini_options] in pyproject.toml
  ✓ App entry point            Procfile: web: uvicorn app.main:app

1/7 Project
? Project name › acme-storefront
? Setup command (runs in sandbox, registry-only network) › uv sync --locked
  Installing dependencies in sandbox… ✓ 14.2 s (cached by uv.lock digest)

2/7 Services
? App command › uv run uvicorn app.main:app --host 127.0.0.1 --port {port}
  Starting in sandbox… ✓ healthy at /healthz in 1.9 s
? Also start web/ (Next.js) for browser journeys? (Y/n) › y
? Web command › npm --prefix web run start -- --port {port}
  Starting in sandbox… ✓ healthy at / in 6.3 s
? Can patches modify web/? (y/N) › n

3/7 Tests
? Test command › uv run pytest -q --junitxml={report}
  Running in sandbox… 211 passed, 1 failed · 18.4 s
    ✗ tests/test_checkout.py::test_checkout_without_coupon
      E  TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'
  This failure reproduces. FaultLine can attempt a repair after setup.

4/7 Repair scope
? Files patches may modify › app/**/*.py
  Always protected: faultline.toml · .faultline/** · tests/** · uv.lock · web/package-lock.json
                    .git/** · .github/** · .env*
? Also protect (comma-separated globs) › migrations/**, app/schemas.py

5/7 Model
? Which model proposes patches?
  › Meta Model API          META_API_KEY is set
    Ollama (local)          running at 127.0.0.1:11434 · 2 models
    OpenAI                  OPENAI_API_KEY not set
    Anthropic               ANTHROPIC_API_KEY not set
    Other OpenAI-compatible endpoint
? Model (from the provider's model list) › muse-spark-1.3
? Reasoning effort › low   (low · medium · high · none)
  Each attempt sends: the failing editable file (≤ 32 KiB), up to 12 failing checks,
  and redacted server logs (≤ 16 KiB). It never sends environment variables, .env files,
  protected paths, or text matching redaction rules.
? Send one probe request now? (Y/n) › y
  ✓ available · 1.2 s · evidence identity: meta (host api.meta.ai)

6/7 Invariants (what must stay true after a repair)
? Add invariants from › [x] pytest suite (all 212 tests; failing ones become reproduction targets)
                        [x] Record a browser journey now (Playwright codegen, sandboxed app)
                        [x] Declare an HTTP rule now
? Journey name › checkout
  Codegen open on the sandboxed web service. Close the browser window to save.
  ✓ .faultline/journeys/checkout.spec.ts · 6 steps · sandbox replay ✗ at "Place order" · reproduces
? Rule id › checkout.no_coupon
? Request › POST /api/checkout  body from file › .faultline/payloads/two-mugs.json
? Expect status › 201
? Add a JSON check (path, matcher, value; blank to finish) › $.discount equals 0
? Add a JSON check › $.total equals_path $.subtotal
? Add a JSON check ›
  Checking rule against current code in sandbox… ✗ status 500 (expected 201) · reproduces

7/7 Delivery
? After a verified repair, locally › interactive review (TUI)
? In CI › draft pull request

Write these files?
  + faultline.toml
  + .faultline/journeys/checkout.spec.ts
  + .faultline/payloads/two-mugs.json
  ~ .gitignore  (+ .faultline/runs/)
(Y/n) › y

Done. 3 invariants currently fail and reproduce:
  test:tests/test_checkout.py::test_checkout_without_coupon
  rule:checkout.no_coupon
  journey:checkout

Next: faultline run
```

### 3.3 Detection rules

| Signal | Inference | Shown as |
| --- | --- | --- |
| `pyproject.toml` with `fastapi`, `django`, or `flask` in dependencies | `project.stack` | "fastapi in dependencies" |
| `uv.lock`, `poetry.lock`, `requirements*.txt` | `setup_command`, lockfiles | "uv.lock → uv sync --locked" |
| `Procfile`, `[project.scripts]`, Makefile `run`/`dev` target, `package.json` `dev`/`start` | `dev_command` with `--port {port}` injected | Source line quoted |
| `[tool.pytest.ini_options]`, `pytest.ini`, `package.json` `test` | `test_command` with a JUnit reporter injected | "pytest via pyproject.toml" |
| `playwright.config.*`, `tests/e2e/*.spec.ts` | Offer existing specs as journeys | "3 Playwright specs found" |
| Health probe order | `/healthz`, `/health`, `/` (first 2xx wins) | "healthy at /healthz" |
| `META_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` set; `127.0.0.1:11434/api/tags` reachable | Provider list annotations | "set" or "not set", never values |

### 3.4 Non-interactive form

```bash
faultline init --yes \
  --provider ollama --model qwen2.5-coder:14b \
  --dev-command "uv run uvicorn app.main:app --host 127.0.0.1 --port {port}" \
  --test-command "uv run pytest -q --junitxml={report}" \
  --editable "app/**/*.py" --protect "migrations/**" \
  --no-probe
```

`init --template ecommerce-app` writes the showcase config (§4.5) into a scratch clone of the fixture.

## 4. `faultline.toml` specification

### 4.1 Format decision: TOML

TOML, not YAML, for these reasons:

- **Stdlib parser.** Python 3.13 ships `tomllib`, so there's no dependency.
- **Consistent with the toolchain.** It matches `pyproject.toml`, uv, and ruff.
- **No implicit type coercion.** YAML would read `no` as false, `1.10` as 1.1, and `0755` as octal. That makes TOML a better fit for the strict Pydantic contracts (`extra="forbid"`, `strict=True`) that already define every wire type in `shared/contracts/models.py`.
- **Editor support.** `faultline config schema` writes JSON Schema, and Taplo and Even Better TOML read the `#:schema` directive for completion.

YAML stays for GitHub workflow files only.

### 4.2 Discovery and precedence

Discovery walks up from the working directory to the git root and stops at the first `faultline.toml`. `--config PATH` overrides discovery.

Precedence, highest first:

1. CLI flags
2. `FAULTLINE_*` environment variables (and legacy `META_*` for the model section)
3. `faultline.toml`
4. `~/.config/faultline/config.toml`
5. Built-in defaults

Security-relevant keys can be set only in `faultline.toml`, not from the environment or user config: `sandbox.limits.mode`, `invariants.forbidden_paths`, and `repair.editable`. `faultline config show --resolved` prints the merged result and where each value came from.

### 4.3 Annotated schema

```toml
#:schema ./.faultline/schema-v1.json      # written by `faultline config schema`
schema = 1                                # Required. Unknown keys anywhere are errors.

# ── project ──────────────────────────────────────────────────────────────────
[project]
name = "acme-storefront"                  # Display name. Default: repository directory name.
stack = "python-fastapi"                  # python-fastapi | python-django | python-flask | node-next | custom.
                                          # Informs defaults only; never changes gates.
root = "."                                # Paths below are relative to this, inside the git repo.
setup_command = "uv sync --locked"        # Runs in the sandbox once per lockfile digest; result cached read-only.
lockfiles = ["uv.lock"]                   # Setup cache keys. Always protected.
dev_command = "uv run uvicorn app.main:app --host 127.0.0.1 --port {port}"
                                          # The primary service, named "app". Runs only inside the sandbox.
                                          # {port} is allocated per run.
url = "http://127.0.0.1:{port}"           # Base URL for rules and journeys. Always loopback.
health = "/healthz"                       # Must return 2xx before baseline starts. Bounded by budgets.preflight.
test_command = "uv run pytest -q --junitxml={report}"
                                          # Default command for [[invariants.test]]. {report} is a sandbox path.

[[project.service]]                       # Optional extra processes, e.g. a frontend the journey drives.
name = "web"
dev_command = "npm --prefix web run start -- --port {port}"
url = "http://127.0.0.1:{port}"
health = "/"
editable = false                          # false: files under this service are read-only to patches.
env = { BACKEND_URL = "{app.url}" }       # Only {placeholders} and literals. Host environment is never inherited.

# ── repair scope and static policy ───────────────────────────────────────────
[repair]
editable = ["app/**/*.py"]                # Globs a patch may modify. Must not overlap forbidden_paths.
context = []                              # Extra read-only files sent to the model. Default: direct imports of
                                          # the failing file, depth 1, each ≤ max_source_bytes.
max_files = 1                             # Files per patch. Hard ceiling 8. Today's engine: 1.
max_diff_bytes = 16384                    # Hard ceiling 65536. Today: 16 KiB.
max_source_bytes = 32768                  # Largest editable file sent or patched. Today: 32 KiB.
max_changed_lines = 100                   # Hard ceiling 400. Today: 100.

[repair.imports]
allow = ["typing.cast", "fastapi.HTTPException"]
                                          # Exact module.name pairs a patch may import. Empty: no new imports.
deny = []                                 # Adds to the built-in floor (F7). Can never remove entries.

# ── sandbox ──────────────────────────────────────────────────────────────────
[sandbox]
engine = "bwrap"                          # bwrap  : Linux namespaces + cgroup v2 user scope (exists today)
                                          # docker : Docker or rootless Podman container (Phase 2)
                                          # microvm: Firecracker on KVM (reserved; rejected until shipped)
                                          # "worktree" is rejected: worktrees are how FaultLine checks out
                                          # source, not an isolation boundary.
network = "none"                          # Candidate phase: none = only this run's own services on loopback.
setup_network = "registries"              # setup_command only: none | registries (PyPI, npm registry hosts).

[sandbox.limits]                          # Aggregate across all candidate processes, read back from the kernel.
mode = "required"                         # required | disabled. disabled also needs --allow-disabled-limits
                                          # on every run and is refused when CI=true.
memory = "512MiB"
swap = "0"
tasks = 64
cpus = 1.0

[sandbox.docker]                          # Read only when engine = "docker".
runtime = "podman"                        # docker | podman. Rootless is recommended.
image = "ghcr.io/OWNER/faultline-runtime@sha256:<digest>"   # Hypothetical; init pins by digest.

# ── model ────────────────────────────────────────────────────────────────────
[model]
provider = "meta"                         # Preset: meta | ollama | openai | anthropic | openai-compatible.
                                          # Sets base_url and wire format. Evidence identity comes from the
                                          # host (F4): meta.ai, meta.com, llama.com → meta; loopback → local;
                                          # api.openai.com → openai; api.anthropic.com → anthropic;
                                          # anything else → openai-compatible.
model_name = "muse-spark-1.3"             # Exact model ID. init offers the provider's /models list.
api_key_env = "META_API_KEY"              # Variable NAME. A value that looks like a credential is an error.
                                          # Omit for ollama.
base_url = "https://api.meta.ai/v1"       # Optional override. HTTPS, or http on loopback only.
reasoning_effort = "low"                  # low | medium | high | none. Unsupported → doctor error, never dropped.
response_format = "json_schema"           # json_schema | json_object. Output is always validated locally.
timeout_seconds = 45                      # 5–180 per request. budgets.generation still applies.
max_attempts = 2                          # Each later attempt receives bounded gate findings. Hard ceiling 3.
require_identity = ""                     # e.g. "meta": fail the run if the responding host is not that identity.

[model.egress]                            # What leaves the machine. Preview with `faultline run --show-prompt`.
logs = "redacted"                         # redacted | none
max_evidence_kib = 16
redact = ["(?i)authorization:.*", "(?i)set-cookie:.*"]   # Added to built-in secret patterns.

# ── invariants (the oracle) ──────────────────────────────────────────────────
[invariants]
forbidden_paths = ["tests/**", "migrations/**", "app/schemas.py"]
                                          # Patches touching these are rejected before execution.
                                          # Built-ins always added (F3).

[[invariants.journey]]                    # A browser journey run by FaultLine's trusted runner, outside the
id = "checkout"                           # candidate sandbox, against the candidate's URL.
spec = ".faultline/journeys/checkout.spec.ts"   # Playwright Test file. `faultline journey record` writes one.
timeout_ms = 20000
evidence = ["screenshot", "trace", "requests", "logs"]   # Required set today. "video" is optional.

[[invariants.rule]]                       # One declarative HTTP request. If a check needs more than one
id = "checkout.no_coupon"                 # request, write it as a test instead.
description = "Checkout without a coupon creates an order at the catalog subtotal"
request = { method = "POST", path = "/api/checkout", json = "@.faultline/payloads/two-mugs.json" }
fingerprint = "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'"
                                          # Optional. Reproduction must match this server error, so a
                                          # different failure is never "repaired".

[[invariants.rule.assert]]
status = 201

[[invariants.rule.assert]]
path = "$.discount"                       # JSONPath into the response body.
equals = 0                                # Matchers: equals | equals_path | matches (regex) | type | exists.

[[invariants.rule.assert]]
path = "$.total"
equals_path = "$.subtotal"

[[invariants.test]]                       # An existing suite as an invariant. Each JUnit test case becomes
id = "pytest"                             # one invariant ID: test:<classname>::<name>.
command = "uv run pytest -q --junitxml={report}"   # Default: project.test_command.
report = "junit"                          # junit only. pytest --junitxml, Playwright --reporter=junit.
select = []                               # Paths or IDs to include. Default: all.

# ── budgets (seconds; defaults equal today's controller budgets) ──────────────
[budgets]
preflight = 45
baseline = 20
attempt = 75
generation = 45
verification = 20
work = 170
cleanup = 10
overall = 180

# ── evidence ─────────────────────────────────────────────────────────────────
[evidence]
dir = ".faultline/runs"
video = false                             # Playwright video. Off by default for size and privacy.
redact_headers = ["authorization", "cookie", "set-cookie"]
retention_days = 30                       # `faultline runs gc` deletes older packets.

# ── delivery ─────────────────────────────────────────────────────────────────
[delivery]
mode = "interactive"                      # interactive | pr | auto-apply
ci_mode = "pr"                            # Used when CI=true. interactive is invalid there.
branch_prefix = "faultline/"
                                          # Fixed floor, not configurable: delivery requires outcome=verified
                                          # and cleanup confirmed.

[delivery.pr]
base = ""                                 # Default: the repository's default branch. Never pushed to directly.
draft = true
labels = ["faultline"]
reviewers = []

[delivery.auto_apply]
target = "working-tree"                   # working-tree | branch (new local branch + commit; never pushed).
commit_trailer = true                     # Adds "FaultLine-Run: <run-id>" when target = "branch".

# ── triggers (CI incident mapping) ───────────────────────────────────────────
[[triggers.incident]]
match = { route = "POST /api/checkout", fingerprint = "TypeError:" }   # Substring match on relay payload.
reproduce = ["rule:checkout.no_coupon", "journey:checkout"]
mode = "repair"                           # repair | detect
```

### 4.4 Validation rules

Config errors exit with 78 and name the exact key.

| Rule | Message |
| --- | --- |
| `editable` overlaps `forbidden_paths` or a built-in protected path | `repair.editable "app/**" overlaps protected "app/schemas.py"` |
| `sandbox.engine = "worktree"` | `worktree is how FaultLine checks out source, not an isolation boundary. Use bwrap or docker.` |
| `api_key_env` value looks like a credential, or any key named `api_key`, `token`, or `password` appears | `model.api_key_env must be a variable name such as META_API_KEY. Do not put credentials in faultline.toml.` |
| `limits.mode = "disabled"` while `CI=true` | Refused |
| `limits.mode = "disabled"` locally without `--allow-disabled-limits` | Refused |
| No invariants declared | `faultline run` refuses: `nothing can reproduce a failure (F1)` |
| `{port}` missing from a `dev_command` | Error |
| `provider = "ollama"` with a non-loopback `base_url` | Warning: `evidence identity will be openai-compatible` |
| A value above a hard ceiling | Error that states the ceiling |
| A Phase 0 build given values that differ from the showcase fixture | Exit 78: `not supported by this release` |

### 4.5 Showcase fixture config: `fixtures/ecommerce-app/faultline.toml`

Phase 0 adds this file in place and moves no sources. Every value equals today's constant, and a test enforces that (§9.2).

```toml
schema = 1

[project]
name = "ecommerce-app"
stack = "python-fastapi"
root = "../.."                            # Phase 0: sources stay under apps/buggyshop-* (see §9).
dev_command = "uvicorn app.main:app --host 127.0.0.1 --port {port}"
url = "http://127.0.0.1:{port}"
health = "/healthz"

[[project.service]]
name = "storefront"
dev_command = "node node_modules/next/dist/bin/next start -p {port} -H 127.0.0.1"
url = "http://127.0.0.1:{port}"
health = "/"
editable = false
env = { BUGGYSHOP_BACKEND_URL = "{app.url}" }

[repair]
editable = ["apps/buggyshop-backend/app/routes/checkout.py"]
max_files = 1
max_diff_bytes = 16384
max_source_bytes = 32768
max_changed_lines = 100

[repair.imports]
allow = [
  "typing.cast", "uuid.uuid4", "fastapi.HTTPException", "app.catalog.get_product",
  "app.orders.LineItem", "app.orders.Order", "app.orders.create_order", "app.schemas.CheckoutRequest",
]

[sandbox]
engine = "bwrap"
network = "none"

[sandbox.limits]
mode = "required"
memory = "512MiB"
swap = "0"
tasks = 64
cpus = 1.0

[model]
provider = "meta"
model_name = "muse-spark-1.3"
api_key_env = "META_API_KEY"
reasoning_effort = "low"
response_format = "json_schema"
timeout_seconds = 45
max_attempts = 2

[invariants]
forbidden_paths = [
  "apps/buggyshop-backend/tests/**", "apps/buggyshop-backend/app/catalog.py",
  "apps/buggyshop-backend/app/orders.py", "apps/buggyshop-backend/app/schemas.py",
  "apps/buggyshop-frontend/**", "fixtures/**", "tools/**", "shared/**",
]

[[invariants.pack]]                       # Today's trusted oracle, unchanged: the browser journey
name = "ecommerce-checkout@1"             # (scenario.ts, oracle.ts), 8 scenario assertions, 27 HTTP
                                          # regressions, and the confirmation check.
fingerprint = "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'"

[budgets]
preflight = 45
baseline = 20
attempt = 75
generation = 45
verification = 20
work = 170
cleanup = 10
overall = 180

[delivery]
mode = "interactive"                      # [a] apply is disabled for this fixture: it must stay seeded so
ci_mode = "pr"                            # every run reproduces the same defect.
```

`[[invariants.pack]]` is the only built-in pack. It exists so the existing oracle keeps running byte-for-byte while the general invariant formats mature. Phase 1 (§9.3) ports it to `.faultline/` files and keeps the pack as an alias.

## 5. CLI reference

### 5.1 Commands

| Command | Purpose | Key flags | Phase |
| --- | --- | --- | --- |
| `faultline doctor` | Host, sandbox, model, and config preflight | `--fix`, `--json`, `--explain TOPIC` | 0 |
| `faultline up` / `down` | Start or stop the local engine (and fixture services) | `--fixture ecommerce-app`, `--port` | 0 |
| `faultline run [TARGET…]` | Reproduce, propose, gate, verify, review. With no targets, every failing invariant is a target. | `--detect-only`, `--attempts N`, `--provider`, `--model`, `--require-identity meta`, `--expect verified`, `--delivery MODE`, `--show-prompt`, `--plain`, `--json`, `--allow-disabled-limits` | 0 (fixture), 1 |
| `faultline review [RUN]` | Open the review screen (default: latest run) | | 0 |
| `faultline apply RUN` | Apply a verified patch | `--branch` | 1 |
| `faultline reject RUN` | Record a rejection, optionally retry | `--reason TEXT`, `--retry` | 1 |
| `faultline pr RUN` | Open a draft PR with evidence | `--base`, `--ready`, `--yes`, `--packet DIR` | 2 |
| `faultline verify` | Gate and verify an existing patch with no model call (Copilot, Claude Code, Codex, or human) | `--patch FILE`, `--worktree`, `--commit SHA` | 2 |
| `faultline invariants ls\|check` | List invariants, or run them against HEAD without repairing | `--json` | 1 |
| `faultline journey record` | Wrap `playwright codegen` against the sandboxed app | `--name`, `--start PATH` | 1 |
| `faultline runs ls\|show\|rm\|gc` | Run history | `--outcome`, `--since` | 0 |
| `faultline packet export\|verify\|rerun` | Portable evidence. `verify` never executes anything; `rerun` explicitly does, in the sandbox. | `--out`, `--against-checkout DIR` | 0 (`verify` wraps `tools/verify_bundle.py`), 2 |
| `faultline replay export RUN` | Static, read-only replay | `--out DIR` | 0 (wraps `scripts/export_replay.py`) |
| `faultline dashboard` | Local web dashboard (the Inspector) | `--port 4000`, `--no-open`, `--run RUN` | 0 |
| `faultline incident` | CI: incident payload → reproduce, then repair | `--payload-file`, `--mode` | 2 |
| `faultline bench corpus\|trials` | Evaluation corpus and trial ledger | `--suite holdout`, `--repeat N`, `--trials N`, `--require-identity meta` | 0 (wraps scripts) |
| `faultline config validate\|show\|schema` | Config tooling | `--resolved` | 0 |

Global flags: `--config PATH`, `--plain`, `--json`, `--ascii`, `-v`/`-q`. The CLI honors `NO_COLOR`.

### 5.2 Exit codes

| Code | Meaning | `TerminalOutcome` |
| --- | --- | --- |
| 0 | Verified candidate. For `invariants check` and `packet verify`: everything passed. | `verified` |
| 10 | Failure reproduced, no repair requested | `detected` |
| 11 | Failure not reproduced; nothing proposed | `no_failure` |
| 20 | Repair attempted, no verified candidate | `unresolved`, `invalid_patch`, `repair_unavailable`, `unexpected_failure` |
| 21 | Model unavailable or errored | `model_error` |
| 30 | Infrastructure, artifact, or timeout failure | `infrastructure_error`, `artifact_error`, `timeout` |
| 31 | Cleanup unconfirmed; engine quarantined | `cleanup_failed` |
| 64 | Usage error | |
| 78 | Config invalid or unsupported | |
| 130 | Cancelled or interrupted | `cancelled`, `interrupted` |

`--expect verified` turns any outcome other than verified into a non-zero exit. This replaces `scripts/rehearse-demo.sh`.

### 5.3 Output modes

| Condition | Mode |
| --- | --- |
| TTY and not CI | Textual TUI (§6) |
| `--plain`, non-TTY, or `CI=true` | One line per stage event (§6.7) |
| `--json` | NDJSON on stdout, human logs on stderr. Each event is a `JobEvent` (`schema_version`, `job_id`, `sequence`, `timestamp`, `stage`, `message_code`, `message`), followed by a final run-summary object. |

The engine allows one run at a time per installation (the existing singleton `RuntimeLease`). A second run shows `waiting for run 7f3c2a1e to release the runtime · [c] cancel waiting` instead of failing.

## 6. Terminal UI

### 6.1 Stack

- **Textual** for interactive screens.
- **Rich** for plain-mode rendering.
- All three modes (TUI, plain, `--json`) consume one event stream. Phase 0 reads it from the controller's SSE endpoint; Phase 1 reads it in-process.
- On reconnect, the stream resumes from the last `sequence`.
- Screens are covered by `pytest-textual-snapshot` tests.

### 6.2 Visual language

| Element | Rule |
| --- | --- |
| Status glyphs | ✓ pass · ✗ fail · ● running · ○ pending · ! attention · – skipped. ASCII fallback (`--ascii` or a non-UTF-8 locale): `ok`, `FAIL`, `..`, `--`, `!!`, `skip`. |
| Color | Meaning, never decoration. Green = measured pass, red = measured fail, amber = degraded or stale (limits disabled, base changed), cyan = keys and links, dim = metadata. Color never carries meaning alone; a glyph and a word always accompany it. |
| Model text | Labeled "Proposed diagnosis (model-generated, not verified)" in italics. Never shown as a verdict. |
| Time | Measured elapsed per stage, shown next to the stage budget. No percentage bars for work of unknown length. A spinner only on the active stage, and none in plain mode. |
| Width | Mockups are 100 columns. Below 100, the "Expected" column is dropped. At the 80×24 minimum, panes stack and paths abbreviate from the left (`apps/…/checkout.py`). |
| Keyboard | Every action has a key. `?` lists them all. Logs never auto-scroll while the user is scrolled up. Focus never jumps on its own. |
| Accessibility | TUIs read poorly with screen readers, so `--plain` is a full alternative that offers the same decisions as prompts. |

### 6.3 Screen 1: live run

```text
 FaultLine · acme-storefront · run 7f3c2a1e                     bwrap · 512 MiB · 64 tasks · 1 CPU ✓
────────────────────────────────────────────────────────────────────────────────────────────────────
 ✓ Prepare             0.8s   worktree @ 1a2b3c4 (detached) · deps cache hit (uv.lock 3e1f…)
 ✓ Reproduce           4.1s   rule:checkout.no_coupon  status 500, expected 201
                              TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'
                              server log matches fingerprint ✓ · journey:checkout ✗ at "Place order"
 ● Propose patch      12.4s   muse-spark-1.3 · host api.meta.ai · attempt 1 of 2 · budget 45s
 ○ Policy check
 ○ Activate candidate
 ○ Verify
 ○ Clean up
────────────────────────────────────────────────────────────────────────────────────────────────────
 12:04:31  baseline    journey checkout: POST /api/checkout → 500 (step 4 of 6)
 12:04:31  baseline    212 tests: 211 passed, 1 failed · 1 rule: 0 passed, 1 failed
 12:04:32  diagnosing  sending 1 editable file (1.8 KiB), 2 failing checks, 3.1 KiB redacted logs
────────────────────────────────────────────────────────────────────────────────────────────────────
 elapsed 17.3s · overall budget 180s                    [l] logs  [e] evidence  [c] cancel  [?] help
```

The stage labels match the Inspector's `STAGE_LABEL` exactly, so the CLI and the dashboard read the same.

### 6.4 Screen 2: review (verified)

The review screen opens automatically when a run reaches a terminal state. It leads with the decision: what failed, what changed, what passed, what was not checked, and whether cleanup completed.

```text
 FaultLine · run 7f3c2a1e · VERIFIED CANDIDATE                                   cleanup confirmed ✓
────────────────────────────────────────────────────────────────────────────────────────────────────
 What failed   POST /api/checkout returned 500 when the coupon was omitted
 What changed  app/routes/checkout.py  +1 −1 · 1 hunk · policy ✓ · base 2d4a180d matches HEAD
 What passed   all 214 invariants on the candidate · 0 regressions vs baseline
 Not checked   anything outside declared invariants: authorization, real data, load, other routes
 Model         muse-spark-1.3 · identity meta (host api.meta.ai) · attempt 1/2 · 2,184 → 412 tokens
────────────────────────────────────────────────────────────────────────────────────────────────────
 Invariant                                   Baseline         Candidate        Expected
 journey:checkout                            ✗ 500            ✓ order shown    order confirmation
 rule:checkout.no_coupon  $.discount         ✗ 500            ✓ 0              0
 rule:checkout.no_coupon  $.total            ✗ 500            ✓ 3998           = $.subtotal (3998)
 test:test_checkout::without_coupon          ✗ TypeError      ✓ passed         passed
 test:test_checkout::tenoff                  ✓ 3599           ✓ 3599           3599
 … 210 more passing in both                                                     [i] show all
────────────────────────────────────────────────────────────────────────────────────────────────────
 Proposed diagnosis (model-generated, not verified)
   "The discount lookup returns None when no coupon is given; default the discount to 0."
────────────────────────────────────────────────────────────────────────────────────────────────────
 [a] apply  [d] diff  [v] trace  [p] create PR  [r] reject  [e] evidence  [i] invariants  [q] quit
```

### 6.5 Screen 3: diff viewer

```text
 Diff · apps/…/routes/checkout.py · base 2d4a180d (seeded) → candidate         hunk 1 of 1 · unified
────────────────────────────────────────────────────────────────────────────────────────────────────
  40  40      if coupon_code and coupon_code not in discounts:
  41  41          raise HTTPException(status_code=400, detail="Invalid coupon code")
  42  42
  43      -   discount = cast(int, discounts.get(coupon_code))
      43  +   discount = cast(int, discounts.get(coupon_code, 0))
  44  44      total = subtotal - discount
  45  45      order: Order = {
  46  46          "id": str(uuid4()),
────────────────────────────────────────────────────────────────────────────────────────────────────
 Policy  ✓ in scope  ✓ 1 file  ✓ 2 changed lines ≤ 100  ✓ syntax  ✓ no new imports  ✓ base hash
 [s] split view  [n/N] next/prev hunk  [w] wrap  [y] copy patch path  [esc] back
```

The split view is available at 140 columns or wider; narrower terminals fall back to unified. When a hunk header was recounted, the header shows `hunk headers recounted from body (content unchanged)`.

### 6.6 Screen variant: no verified candidate

```text
 FaultLine · run 41d0be97 · NO VERIFIED CANDIDATE (unresolved)                   cleanup confirmed ✓
────────────────────────────────────────────────────────────────────────────────────────────────────
 Attempt 1   policy ✓   verify ✗   test:test_checkout::tenoff expected 3599, observed 3998
 Attempt 2   policy ✗   rejected before execution: catch-all exception handler (except Exception)
────────────────────────────────────────────────────────────────────────────────────────────────────
 Nothing was applied. The baseline failure still reproduces.
 [d] diffs  [e] evidence  [R] retry with a note  [i] invariants  [q] quit
```

On non-verified runs, `[a]` and `[p]` are absent from the key bar. Pressing them anyway explains why: `Apply requires outcome=verified and confirmed cleanup (F8)`.

### 6.7 Key map

| Scope | Key | Action |
| --- | --- | --- |
| Global | `?` | Help overlay with every binding |
| Global | `q` / `esc` | Back or quit (quitting mid-run asks first; the run continues in the engine) |
| Global | `c` | Cancel the run (confirm) |
| Global | `l`, `e`, `i` | Logs, evidence list, full invariant table |
| Global | `/` | Search logs |
| Global | `tab` | Cycle panes |
| Global | `Y` | Copy run ID |
| Review | `a` | Apply patch |
| Review | `d` | Diff viewer |
| Review | `v` / `V` | Candidate / baseline browser trace |
| Review | `p` | Create PR |
| Review | `r` | Reject |
| Review | `R` | Reject and retry with a note |
| Review | `o` | Open the packet folder |
| Diff | `s`, `n`/`N`, `w`, `y` | Split/unified, next/previous hunk, wrap, copy patch path |
| Evidence | `enter` | Open artifact (`xdg-open`) |
| Evidence | `t` | Trace viewer |
| Evidence | `h` | Show SHA-256 |

### 6.8 Action semantics

**`[a]` Apply.**
- Preconditions:
  - Outcome is `verified` and cleanup is confirmed.
  - The target file's current SHA-256 equals the run's `base_sha256`.
  - The target file has no uncommitted edits.
- A modal offers two choices:
  - **Working tree** (default): `git apply` with no commit. You review it with your own tools and commit under your own identity.
  - **New branch**: creates `faultline/7f3c2a1e` from HEAD and commits there, with the optional `FaultLine-Run` trailer. It is never pushed.
- If the file changed after the run: `base changed since run 7f3c2a1e. Re-run: faultline run --target rule:checkout.no_coupon`. Stale patches are never force-applied.
- Disabled on the showcase fixture, which must stay seeded.

**`[d]` Diff.** Opens the full-screen viewer (§6.5). Read-only.

**`[v]` / `[V]` Trace.**
- Runs `playwright show-trace <trace.zip>` for the candidate (`v`) or the baseline (`V`) using the bundled runner's Playwright.
- Without a display (`$DISPLAY` and `$WAYLAND_DISPLAY` empty, e.g. over SSH), it prints the artifact paths and `faultline dashboard --run 7f3c2a1e` instead.
- Video appears only when `evidence.video = true`.

**`[p]` Create PR.** This is an outward-facing action, so it confirms every time (`--yes` exists for CI only).
- The modal shows the repo, base, head branch, title, draft status, changed files, and body preview.
- Auth comes from `gh auth token` or `GH_TOKEN`.
- On confirm: pushes `faultline/<run>` and opens a draft PR. It never pushes to the base branch.
- The PR body template is in §8.6.

**`[r]` Reject.**
- Pick a reason: wrong fix · right symptom, wrong place · invariants incomplete · other (free text).
- The decision is recorded in the packet as `review.decision = "rejected"`, and nothing else changes.
- Choosing "invariants incomplete" offers to open `faultline.toml` at `[invariants]`. After you add a rule, `faultline verify --run 7f3c2a1e` re-checks the same candidate against it. A rejection becomes a permanent invariant.

**`[R]` Reject and retry.** Your note goes to one more attempt, labeled as untrusted reviewer input in the prompt (like gate findings today). It counts toward `max_attempts`.

### 6.9 Plain mode (CI logs)

```text
faultline run · acme-storefront@1a2b3c4 · run 7f3c2a1e · engine docker · model muse-spark-1.3
[  0.8s] prepare     ok    worktree 1a2b3c4 · deps cache hit
[  4.9s] reproduce   FAIL  rule:checkout.no_coupon status 500 (expected 201) · fingerprint matched
[ 17.2s] propose     ok    attempt 1/2 · identity meta (api.meta.ai) · 1 file +1 -1
[ 17.3s] policy      ok    scope · size · syntax · imports · base hash
[ 19.0s] activate    ok    app healthy at /healthz · web healthy at /
[ 24.1s] verify      ok    214/214 invariants · 0 regressions
[ 24.9s] cleanup     ok    scope released · worktree removed
outcome=verified run=7f3c2a1e packet=.faultline/runs/7f3c2a1e/packet sha256=9c1e…
```

## 7. Developer workflows

**A. A test fails locally.**
1. Run `faultline run`, or target it: `faultline run test:tests/test_checkout.py::test_checkout_without_coupon`.
2. The live screen shows reproduction, then the proposal, gates, and verification.
3. On review, check `[d]` and `[v]`, then press `[a]` to apply to the working tree.
4. `git diff` shows the change. You commit with your own identity.

**B. Check a patch from a coding agent or a colleague (no model call).**
1. Save the patch with `git diff > /tmp/fix.diff`, or leave it uncommitted.
2. Run `faultline verify --patch /tmp/fix.diff`, or `faultline verify --worktree` for uncommitted changes against HEAD.
3. The same gates run: scope, size, AST floor, protected paths, isolated execution, and every invariant.
4. Exit code 0 means verified. On failure, the review screen lists failing invariants with expected and observed values.

This is research direction B (independent evaluator, `LONG_TERM_RESEARCH_AND_IDEAS.md` §4.3), and it is the cheapest adoption path.

**C. Production crashes (CI).**
1. An error tracker alert goes to a small relay, which sends a sanitized `repository_dispatch` (§8.5).
2. The action runs `faultline incident` on the deployed SHA.
3. A `[[triggers.incident]]` entry maps the payload to invariants, which run in the sandbox.
4. If the failure reproduces, a repair runs. On `verified`, a draft PR opens with the packet.
5. If the failure does not reproduce, the step summary says so and names the route with no covering invariant (F1). Nothing is proposed.

**D. Share evidence with a reviewer.**
1. The author runs `faultline packet export 7f3c2a1e --out fix-7f3c.faultline.tgz`.
2. The reviewer runs `faultline packet verify fix-7f3c.faultline.tgz`. It checks schema, paths, sizes, and digests, and executes nothing.
3. Optionally the reviewer runs `faultline packet rerun`, which executes explicitly in their own sandbox.
4. For a public, read-only artifact: `faultline replay export`.

**E. Browse history visually.** `faultline dashboard` opens the Inspector at `http://127.0.0.1:4000` with run history, diffs, and artifacts. It shows the same data as the TUI. The CLI never depends on the dashboard.

## 8. CI/CD and GitHub Actions

### 8.1 Runner constraints

**Unverified:**
- Whether GitHub-hosted `ubuntu-latest` runners allow unprivileged user namespaces for bwrap. That label is migrating to Ubuntu 26 starting October 19, 2026, according to the runner notice in this repo's Verify log on October 30. Ubuntu has restricted these namespaces through AppArmor by default since 24.04.
- Whether the runner user gets a systemd user manager with cgroup delegation.

The README already requires both for the bwrap engine.

**Plan:**
- Hosted runners use `engine = "docker"` (Phase 2), with `--memory 512m --memory-swap 512m --pids-limit 64 --cpus 1 --network none --read-only --cap-drop ALL --security-opt no-new-privileges`. Limits are read back from the container's cgroup files.
- The bwrap engine is supported only on self-hosted Linux runners that pass `faultline doctor`.
- Until the docker engine ships, the action supports `command: reproduce` (detect-only) on hosted runners only when `doctor` passes, and otherwise exits 30 with the reason.

### 8.2 Trust model

- **Two jobs.**
  - `diagnose` has a read-only token and the model secret, and runs the sandbox. It never gets write permission.
  - `deliver` has write permission but no model secret, and **executes no repository or candidate code**. It re-checks the packet statically against a fresh checkout before pushing.
- **Forks are excluded.** `workflow_run` proceeds only when `head_repository.full_name == github.repository`, which avoids running secrets against untrusted fork code.
- **No `${{ }}` in `run:` scripts.** Event data reaches steps only through `with:` and `env:`, which prevents script injection.
- **Model secret behind an environment.** `faultline-model` can require reviewers, so incident-triggered runs can't spend credits unattended.
- **PRs need an app token to trigger CI.** PRs opened with `GITHUB_TOKEN` don't trigger other workflows, so the PR's own CI wouldn't run. `deliver` uses a GitHub App token via `actions/create-github-app-token`.

### 8.3 Composite action interface (`action/action.yml`, Phase 2)

| Input | Default | Meaning |
| --- | --- | --- |
| `command` | `run` | `run` · `reproduce` · `verify` · `incident` |
| `config` | `faultline.toml` | Config path |
| `sandbox` | `docker` | Engine override for CI |
| `targets` | (all failing) | Invariant IDs, space-separated |
| `patch` | | Path to a diff, for `command: verify` |
| `incident` | | JSON payload, for `command: incident` |
| `require-identity` | | e.g. `meta`. The run fails if the responding host's identity differs. |
| `version` | pinned | FaultLine version installed via `uv tool install` |

Outputs:

| Output | Meaning |
| --- | --- |
| `outcome` | `TerminalOutcome` value |
| `run-id` | The run's ID |
| `packet-path` | Where the evidence packet was written |
| `verified` | `true` or `false` |

The action writes the invariant table to `$GITHUB_STEP_SUMMARY`.

### 8.4 `.github/workflows/action-faultline.yml`

Actions are pinned to the same SHAs as `.github/workflows/check.yml`. Three references don't exist yet or aren't pinned in this repo, and are marked: the FaultLine action, `download-artifact`, and `create-github-app-token`.

```yaml
name: FaultLine
on:
  workflow_run:
    workflows: [Verify]
    types: [completed]
  repository_dispatch:
    types: [faultline-incident]
  workflow_dispatch:
    inputs:
      targets:
        description: Invariant IDs to reproduce (blank = all failing)
        required: false
permissions: {}
concurrency:
  group: faultline-${{ github.event.client_payload.fingerprint_id || github.event.workflow_run.head_sha || github.sha }}
  cancel-in-progress: false

jobs:
  diagnose:
    if: >-
      github.event_name != 'workflow_run' ||
      (github.event.workflow_run.conclusion == 'failure' &&
       github.event.workflow_run.head_repository.full_name == github.repository)
    runs-on: ubuntu-latest
    timeout-minutes: 20
    environment: faultline-model
    permissions:
      contents: read
    outputs:
      outcome: ${{ steps.faultline.outputs.outcome }}
      run-id: ${{ steps.faultline.outputs.run-id }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          ref: ${{ github.event.workflow_run.head_sha || github.event.client_payload.sha || github.sha }}
          persist-credentials: false
          fetch-depth: 0
      - uses: astral-sh/setup-uv@07a047e608db84b3d8c06cd9a7c7dcc9c355c18e # v10.3.2
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7
        with:
          node-version: '24'
      - id: faultline
        uses: FrankieBiz/Faultline/action@<full-sha> # v0.3.0, does not exist yet
        with:
          command: ${{ github.event_name == 'repository_dispatch' && 'incident' || 'run' }}
          incident: ${{ github.event_name == 'repository_dispatch' && toJSON(github.event.client_payload) || '' }}
          targets: ${{ inputs.targets }}
          sandbox: docker
        env:
          META_API_KEY: ${{ secrets.META_API_KEY }}
      - uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        if: always() && steps.faultline.outputs.run-id != ''
        with:
          name: faultline-packet
          path: .faultline/runs/${{ steps.faultline.outputs.run-id }}/packet
          retention-days: 14

  deliver:
    needs: diagnose
    if: needs.diagnose.outputs.outcome == 'verified'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
    steps:
      - id: app-token
        uses: actions/create-github-app-token@<full-sha> # pin before use
        with:
          app-id: ${{ vars.FAULTLINE_APP_ID }}
          private-key: ${{ secrets.FAULTLINE_APP_PRIVATE_KEY }}
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          ref: ${{ github.event.workflow_run.head_sha || github.event.client_payload.sha || github.sha }}
          token: ${{ steps.app-token.outputs.token }}
          fetch-depth: 0
      - uses: actions/download-artifact@<full-sha> # pin before use
        with:
          name: faultline-packet
          path: packet
      - uses: astral-sh/setup-uv@07a047e608db84b3d8c06cd9a7c7dcc9c355c18e # v10.3.2
      # Static only: schema, digests, base hashes vs this checkout, scope, protected paths, policy gates.
      - run: uvx faultline@0.3.0 packet verify packet --against-checkout .
      - run: uvx faultline@0.3.0 pr --packet packet --draft --yes
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
```

### 8.5 Incident payload (`client_payload`)

GitHub limits `client_payload` to 10 top-level properties, and this payload uses 8. The payload contains no request bodies, headers, cookies, user IDs, or stack-local values.

```json
{
  "schema": "faultline.incident/1",
  "sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
  "environment": "production",
  "route": "POST /api/checkout",
  "fingerprint": "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'",
  "fingerprint_id": "tracker:issue-4512",
  "first_seen": "2026-10-30T15:02:11Z",
  "issue_url": "https://tracker.example/issues/4512"
}
```

Error trackers can't post this shape directly, so a relay of about 40 lines maps the tracker's alert webhook to this payload. FaultLine ships reference relay templates in Phase 3. The relay's token needs permission to create repository dispatch events and nothing else.

### 8.6 PR body template

```markdown
### FaultLine verified candidate · run 7f3c2a1e

**Reproduced:** `POST /api/checkout` returned 500 when the coupon was omitted (rule `checkout.no_coupon`, journey `checkout`).
**Change:** `app/routes/checkout.py` (+1 −1), proposed by `muse-spark-1.3`, identity `meta` (host `api.meta.ai`), attempt 1 of 2.
**Verified:** 214/214 declared invariants passed on the candidate in an isolated sandbox (docker · 512 MiB · 64 tasks · 1 CPU, read back from cgroup files). Cleanup confirmed.
**Not verified:** behavior outside the declared invariants, including authorization, production data, and load.

| Invariant | Baseline | Candidate |
| --- | --- | --- |
| `journey:checkout` | ✗ 500 | ✓ order shown |
| `rule:checkout.no_coupon` `$.discount` | ✗ 500 | ✓ 0 |
| … 212 more | | |

Evidence packet: `faultline-packet` artifact, sha256 `9c1e…`. Verify offline with `faultline packet verify`.
The model's explanation is a proposed diagnosis, not a verified claim.
```

## 9. Transition plan

### 9.1 Constraints

- Submission is due **November 4, 2026, 9 PM ET**. Judging runs November 4–8, with finals on November 9 ([HACKATHON_BRIEF.md](HACKATHON_BRIEF.md); recheck the official pages).
- `meta-provided/` is immutable.
- `make check`, `make browser`, and `make integration` must stay green.
- The public submission may claim only shipped behavior.
- Provenance pins tie the fixture to paths. `fixtures/manifest.json` pins `source_commit` and `target_file = apps/buggyshop-backend/app/routes/checkout.py`. `SnapshotManager` creates worktrees from that commit, and `isolated_runtime.py`, `fixtures/evaluation/corpus.py`, `scripts/*.sh`, the Makefile, and `check.yml` all hardcode `apps/buggyshop-*`.
- Recorded evidence in `docs/evidence/` and `docs/replay/` refers to those paths.
- The running demo stacks, the live demo service (`app/live_demo.py` on `main`), and the judge page must keep working.

`HACKATHON_BRIEF.md` contains no rule against restructuring. The binding constraints are the deadline, truthful claims, and the immutable directory.

**Decision:** Before submission, add files only. Move nothing.

### 9.2 Phase 0: CLI preview over the existing engine (Oct 30 – Nov 3, timeboxed to about 1.5 engineering days)

The remaining work with the highest score impact belongs to the owner: live Meta trials, the impact account, and the video ([PROJECT_STATUS.md](PROJECT_STATUS.md)). Phase 0 runs only if it doesn't displace that work. A CLI-first story also steers clear of the webinar's "dashboards as the main feature" anti-pattern.

Add (no existing file's behavior changes):

| File | Content |
| --- | --- |
| `services/repair-orchestrator/app/cli/__init__.py`, `__main__.py` | Command dispatch: `doctor`, `up`, `down`, `run`, `review`, `runs`, `packet verify`, `replay export`, `bench`, `dashboard`, `config` |
| `app/cli/client.py` | httpx client for `/api/faultline/*`. Reads the token from `FAULTLINE_CONTROL_TOKEN` or `$XDG_RUNTIME_DIR/faultline/control-token` (0600). `faultline up` writes that file and then runs `scripts/start-demo.sh` with the token exported. |
| `app/cli/render.py` | Rich plain and live renderers over the SSE `JobEvent` stream (§6.3, §6.9) |
| `app/cli/review.py` | Rich review summary (§6.4) with `[d]`, `[v]`, `[e]`, `[q]` via key prompt. `[a]` and `[p]` disabled for the fixture. Textual comes in Phase 1. |
| `app/cli/config.py` | Strict TOML → Pydantic (`extra="forbid"`, `strict=True`). Exits 78 for any value outside the fixture's. |
| `services/repair-orchestrator/pyproject.toml` | `[project.scripts] faultline = "app.cli:main"`, plus `rich` (lock refreshed) |
| `fixtures/ecommerce-app/faultline.toml`, `README.md` | §4.5, pointing at existing paths |
| `services/repair-orchestrator/tests/test_cli.py` | CLI against `create_app(...)` with an injected simulated runtime, following the existing test pattern. Covers exit codes, plain output, and `--json` events. |
| `services/repair-orchestrator/tests/test_fixture_config.py` | **Drift test:** the fixture TOML equals `policy.TARGET_FILE`, `MAX_*`, `_IMPORTS`, `Budgets()`, the limits configuration, and `ModelSettings()` defaults |
| README section "CLI (preview)" | Lists only the shipped commands |

Unchanged in Phase 0: engine modules, contracts, scenario registry, runner, Inspector, live demo, provenance pins, recorded evidence, and `meta-provided/`.

Acceptance:
- `make check` passes with test counts at or above today's (239 / 320 / 32).
- `faultline run --fixture ecommerce-app --expect verified` exits 0 in labeled deterministic mode five times in a row.
- `faultline packet verify` agrees with `tools/verify_bundle.py` on the same bundle.

Lanes under the multi-model division of labor:
- **Backend** (`config.py`, `client.py`, tests): GPT lane.
- **Renderers, review screen, README section**: Claude lane.
- **Coordinator**: `make check` gate.

### 9.3 Phase 1: Restructure and generalize for Python web apps on bwrap (from November 10)

1. Tag the submitted commit as `hackathon-submission-2026-11-04` and keep `main` stable through the November 9 finals. Do Phase 1 on a branch.
2. Move the fixture:
   - `git mv apps/buggyshop-backend fixtures/ecommerce-app/backend`
   - `git mv apps/buggyshop-frontend fixtures/ecommerce-app/frontend`
   - `git mv fixtures/seeds fixtures/ecommerce-app/seeds`
   - `git mv fixtures/evaluation fixtures/ecommerce-app/evaluation`
   - Update path constants in `policy.py`, `snapshots.py`, `isolated_runtime.py`, `fixtures/provenance.py`, `corpus.py`, `scripts/setup.sh`, `scripts/start-demo.sh`, the Makefile, and `check.yml` cache paths.
3. Re-pin in two commits:
   - Commit the move.
   - Then run `uv run python -m fixtures.provenance --write --source-commit <move-commit>` and `python -m fixtures.evaluation.corpus --write`, and commit the manifests.
   - Leave historical evidence and replays untouched; they are dated records. Record the path change in `CHRONOLOGICAL_ADJUSTMENTS.md`.
4. Restructure the package (§2.2): `src/faultline/{engine,contracts,config,cli,tui}`, one wheel, bundled runner, pytest moved to dev.
5. Make the engine config-driven:
   - `RepairScope` replaces `TARGET_FILE`.
   - `ImportPolicy` replaces `_IMPORTS`; the F7 floor stays built in.
   - `InvariantSuite` (journey, rule, test) replaces `Scenario` and `REGISTRY`.
   - `SandboxProfile` launches `project.dev_command` inside bwrap, replacing the fixed backend launcher. It adds a setup cache with registry-only network and support for multiple services.
   - Multi-file patches up to `max_files`.
6. New user-facing pieces: the Textual TUI, `init`, `apply`, `reject`, `invariants`, and `journey record`. The ecommerce pack is ported to `.faultline/` files and stays available as an alias.
7. The Inspector becomes `faultline dashboard`, still a Node process in this phase.

Acceptance:
- Test counts don't drop.
- The evaluation corpus produces identical verified and rejected sets before and after the refactor.
- The fixture runs 5/5.
- An unrelated real Python repo chosen by the owner goes from `init` through reproduction without intervention, with every intervention recorded (research §4.2).

Scope limits: SQLite or in-memory state only. Services that need Postgres wait for Phase 2.

### 9.4 Phase 2: CI and teams

- `DockerRuntime` implements the existing `Runtime` protocol (`prepare`, `activate`, `execute`, `cleanup`, `reconcile`), so the worker doesn't change. It supports Podman rootless and Docker. Service sidecars come with it, and macOS works through Docker.
- GitHub Action and workflow (§8), `pr` delivery, `verify --patch`, and `incident`.
- Case packets with the manifest groups from research §13.1, plus `packet export` and `rerun`.
- The dashboard is served by the engine as a static export. A one-time token URL is exchanged for an HttpOnly same-origin cookie, which removes the need for the Next.js server proxy.

### 9.5 Phase 3: Breadth

- MicroVM engine (Firecracker on KVM)
- Reference incident relay templates
- npm shim
- OS keyring credential storage (`faultline auth`)
- Node backend stacks
- Signed packets (Sigstore; research §13.3)

### 9.6 What each phase may claim

| Phase | May claim | May not claim |
| --- | --- | --- |
| 0 | "A CLI preview drives the existing controller for the registered fixture" | Support for arbitrary repos, the GitHub Action, Docker, or PRs |
| 1 | "Local CLI repairs failing invariants in Python web apps on Linux with bwrap" | CI support, macOS, Postgres-backed apps |
| 2 | "GitHub Action with draft PRs; Docker engine" | Hardware isolation, production deployment |
| 3 | Per shipped item | Compliance certification. Signatures prove the issuer, not correctness. |

### 9.7 Risks

| Risk | Mitigation |
| --- | --- |
| Arbitrary apps lack an independent oracle, so a "verified" result means less | F1 refusal with zero invariants; the "Not checked" line is always shown; invariant counts appear next to every verdict |
| Patches game tests | F3 protected paths, plus a policy gate before execution |
| Proprietary source leaves the machine | `[model.egress]`, `--show-prompt`, and a local Ollama option shown first in docs for sensitive code |
| Hosted runners can't run bwrap | Docker engine; until then `doctor` fails closed in CI |
| Name or domain unavailable | Check before any publishing; `faultline-cli` fallback |
| Phase 0 displaces evidence work | Timebox and owner go/no-go on October 31 |
| Re-pinning breaks reproducibility | Two-commit re-pin and the identical-corpus-results acceptance check |

### 9.8 Owner decisions needed

1. Approve TOML over YAML (§4.1).
2. Decide whether Phase 0 runs before submission, or skip it.
3. Choose package and domain names, and confirm availability.
4. Choose a distribution license.
5. Choose GitHub App or fine-grained PAT for PR delivery.
6. Decide whether the Devpost text mentions the CLI preview. If it does, mention shipped commands only.
