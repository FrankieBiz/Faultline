# Plan: interactive judge experience with a live repair service

Decided October 29, 2026. Goal: every judge can make something happen from the public judge page (https://frankiebiz.github.io/Faultline/), with no install.

## Pieces and owners

| Piece | Owner | Files (exclusive) |
| --- | --- | --- |
| Live repair service (backend) | Codex `gpt-6.1-sol` | `services/repair-orchestrator/app/live_demo.py` (new), an optional progress hook in `services/repair-orchestrator/app/evaluation.py`, `services/repair-orchestrator/tests/test_live_demo.py` (new), `scripts/start-live-demo.sh` (new) |
| Deployment kit | Claude subagent | `deploy/**` (new), `scripts/configure-live-demo.py` (new) |
| Judge page: recorded-run playback and live panel | Claude coordinator | `docs/index.html` |
| Video footage (after the above) | Claude subagent | `docs/video/**` or `/tmp` only |
| README, HANDOFF, integration, verification, commit | Claude coordinator | `README.md`, `.agents/**` |

Nobody commits except the coordinator. Nobody touches `meta-provided/`. Never print or commit secrets. Ports 3000/4000/8000/9000 belong to another worktree's demo; do not stop or signal those processes.

## Live repair service contract

The service lets a visitor pick one of the 10 corpus defects (`fixtures/evaluation/cases.json` → `holdout`, including the registered `seeded_missing_coupon`) and watch the configured provider repair it through the existing evaluation loop (`evaluate_holdout`: baseline measurement with the 27-check HTTP oracle, proposal, patch policy, re-measurement in a fresh isolated backend, one retry with gate findings). Visitors never submit code or free text; only a defect ID.

Process: FastAPI app in `app/live_demo.py`, started by `scripts/start-live-demo.sh`, binding `127.0.0.1:${LIVE_DEMO_PORT:-9600}`. A reverse proxy (Caddy) terminates TLS in production. Uses `IsolatedBackendLauncher` (fail closed: no run unless the sandbox preflight and aggregate-limit probe pass) and `MetaRepairAdapter(ModelSettings.from_environment())`. Provider identity and labels come only from adapter responses and `classify()`.

Configuration (environment):

- `LIVE_DEMO_PORT` (default 9600)
- `LIVE_DEMO_ALLOWED_ORIGINS` (comma-separated, default `https://frankiebiz.github.io`)
- `LIVE_DEMO_TRUST_PROXY` (`1` to take the client address from the last `X-Forwarded-For` hop; default off)
- `LIVE_DEMO_PER_CLIENT_PER_HOUR` (default 4), `LIVE_DEMO_DAILY_CAP` (default 150, UTC day), `LIVE_DEMO_MAX_WAITING` (default 3)
- `LIVE_DEMO_DATA_DIR` (default `data/live-demo`)
- Model settings are the existing `META_*` variables.

Endpoints (all JSON; CORS for allowed origins, methods GET/POST, header Content-Type):

- `GET /api/live/status`
  `{"available": bool, "reason": str|null, "provider": str|null, "model": str|null, "classification": str|null, "queue": {"running": bool, "waiting": int, "max_waiting": int}, "limits": {"per_client_per_hour": int, "daily_cap": int, "daily_remaining": int}, "defects": [{"id", "title", "defect_class", "expected_failures": [str]}], "runtime_limits": {...}|null}`
- `POST /api/live/runs` body `{"defect_id": str}` → `202 {"run_id": str, "position": int}`.
  Errors: `400 {"error": {"code": "unknown_defect", "message"}}`, `429 {"error": {"code": "rate_limited"|"queue_full"|"daily_cap_reached", "message", "retry_after_seconds"}}`, `503 {"error": {"code": "unavailable", "message"}}`.
- `GET /api/live/runs/{run_id}` →
  `{"id", "defect_id", "defect_title", "defect_class", "state": "queued"|"running"|"finished"|"failed", "position": int, "created_at", "started_at", "finished_at", "provider", "model", "classification", "events": [EVENT], "outcome": str|null, "attempts": [ATTEMPT]}`; `404` if unknown.
  - EVENT: `{"t_ms": int (since run start), "stage": "baseline"|"propose"|"policy"|"verify"|"done", "status": "running"|"passed"|"failed"|"rejected"|"error", "attempt": int|null, "message": str, "data": {...}}`
    - baseline done: `data = {"failing": [check ids], "total": 27}`
    - propose done: `data = {"provider", "model", "generation_ms", "prompt_tokens", "completion_tokens", "decision"}` or error `data = {"code"}`
    - policy: `data = {"error": str|null}`
    - verify done: `data = {"failing": [check ids], "total": 27}`; candidate rejected: `data = {"rejection": str}`
    - done: `data = {"outcome": str}`
  - ATTEMPT: `{"attempt_number", "outcome", "provider", "model", "generation_ms", "prompt_tokens", "completion_tokens", "explanation", "diff", "diff_recounted", "policy": {"is_valid", "error"}|null, "failing_after": [str]|null, "prior_feedback": {...}|null}` (no backend logs, no file paths, no model_diff).
- `GET /api/live/ledger` → `{"runs_total", "verified", "by_defect": {id: {"runs", "verified"}}, "by_classification": {cls: {"runs", "verified"}}, "recent": [{"id", "defect_id", "outcome", "provider", "model", "classification", "attempts", "finished_at"}]}` (last 20), read from the persisted ledger so it survives restarts.

Behavior: one run at a time (FIFO queue, at most `max_waiting` waiting), overall per-run timeout 240 s → outcome `timeout`. Each finished run is appended to `ledger.jsonl` and saved as `runs/<id>.json` under the data dir. Store no client addresses (rate limiting keeps salted hashes in memory only). Responses never include secrets, backend logs, or filesystem paths. Bounded sizes: explanation ≤ 2 KiB, diff ≤ 16 KiB.

## Judge page behavior

- The recorded Meta repair section gets "Play the recorded run": the five steps light up at real timing from job `3573b32b` events (13.0 s). Labeled as a replay.
- A new "Break it yourself" section: pick a defect, run it live, watch events stream, see the diff and verdict, see the public ledger. API base comes from `<meta name="faultline-live-api" content="...">` (set by `scripts/configure-live-demo.py`) or a `?live=` override. Offline, unconfigured, or capped → explains that and offers the recorded playback. Provider labels come from the response; only `classification == "meta_model"` is described as Meta.
