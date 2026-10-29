"""Bounded public access to the existing isolated, verifier-guided repair loop."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import signal
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.evaluation import (
    ApplicationExporter,
    BackendLauncher,
    IsolatedBackendLauncher,
    LimitRecorder,
    classify,
    evaluate_holdout,
)
from app.model_adapter import MetaRepairAdapter, ModelSettings
from app.snapshots import REPOSITORY_ROOT
from fixtures.evaluation.corpus import case_bytes, load_corpus
from fixtures.provenance import verify_manifest


class LiveLauncher(BackendLauncher, Protocol):
    """Backend launcher that proves containment before public admission."""

    async def preflight(self) -> None:
        """Raise unless isolation and aggregate resource limits are enforced."""
        ...


@dataclass(frozen=True)
class LiveSettings:
    """Public admission limits; the model configuration remains server-owned."""

    allowed_origins: tuple[str, ...] = ("https://frankiebiz.github.io",)
    trust_proxy: bool = False
    per_client_per_hour: int = 4
    daily_cap: int = 150
    max_waiting: int = 3
    run_timeout_seconds: float = 240.0
    # Production pins the provider so a missing key never serves the fallback as the demo.
    require_provider: str | None = None
    # Under systemd (Restart=always), exit after an infrastructure failure so the
    # fail-closed preflight runs again instead of staying unavailable until a manual restart.
    exit_on_failure: bool = False
    # With exit_on_failure, a service that starts unavailable (for example during a brief
    # provider outage) restarts after this delay to run its preflight and probe again.
    unavailable_retry_seconds: float = 300.0

    def __post_init__(self) -> None:
        if min(self.per_client_per_hour, self.daily_cap, self.max_waiting) < 0:
            raise ValueError("Live admission limits cannot be negative")
        if not 0 < self.run_timeout_seconds <= 240:
            raise ValueError("Live run timeout must be between zero and 240 seconds")
        if "*" in self.allowed_origins:
            raise ValueError("Live origins must be explicit")

    @classmethod
    def from_environment(cls) -> LiveSettings:
        """Read named settings without opening environment files."""
        return cls(
            allowed_origins=tuple(
                origin.strip()
                for origin in os.environ.get(
                    "LIVE_DEMO_ALLOWED_ORIGINS", "https://frankiebiz.github.io"
                ).split(",")
                if origin.strip()
            ),
            trust_proxy=os.environ.get("LIVE_DEMO_TRUST_PROXY") == "1",
            per_client_per_hour=int(os.environ.get("LIVE_DEMO_PER_CLIENT_PER_HOUR", "4")),
            daily_cap=int(os.environ.get("LIVE_DEMO_DAILY_CAP", "150")),
            max_waiting=int(os.environ.get("LIVE_DEMO_MAX_WAITING", "3")),
            require_provider=os.environ.get("LIVE_DEMO_REQUIRE_PROVIDER") or None,
            exit_on_failure=os.environ.get("LIVE_DEMO_EXIT_ON_FAILURE") == "1",
        )


class RunRequest(BaseModel):
    """Visitors may select a corpus identifier, never submit source or prompts."""

    model_config = ConfigDict(extra="forbid", strict=True)
    defect_id: str = Field(max_length=100)


class PublicOutput:
    """Redact server credentials and host paths before retaining public evidence."""

    def __init__(self, adapter: MetaRepairAdapter) -> None:
        self.secrets = tuple(
            value
            for value in (
                adapter.settings.api_key,
                os.environ.get("META_API_KEY"),
                os.environ.get("MODEL_API_KEY"),
                os.environ.get("FAULTLINE_CONTROL_TOKEN"),
            )
            if value
        )

    def text(self, value: str, limit: int = 2048) -> str:
        """Bound UTF-8 bytes after removing credentials and absolute host paths.

        Relative patch headers identify the public repair target and remain in
        the diff. Absolute paths, including paths echoed by candidate text, do not.
        """
        for secret in self.secrets:
            value = value.replace(secret, "[redacted]")
        value = re.sub(r"(?<![\w./])(?:[A-Za-z]:[\\/]|/)(?=[\w.~])[^\s\"'<>]+", "[path]", value)
        return value.encode()[:limit].decode("utf-8", errors="ignore")

    def clean(self, value: Any) -> Any:
        """Sanitize already allowlisted JSON fields recursively."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.clean(item) for item in value]
        if isinstance(value, dict):
            return {self.text(str(key)): self.clean(item) for key, item in value.items()}
        return value

    def attempt(self, record: dict[str, Any]) -> dict[str, Any]:
        """Retain only the public attempt contract, never logs or original model diffs."""
        result = {
            key: self.clean(record.get(key))
            for key in (
                "attempt_number",
                "outcome",
                "provider",
                "model",
                "generation_ms",
                "prompt_tokens",
                "completion_tokens",
                "failing_after",
            )
        }
        result.update(
            explanation=self.text(record.get("explanation") or ""),
            diff=self.text(record.get("diff") or "", 16 * 1024),
            diff_recounted=bool(record.get("diff_recounted", False)),
            policy=None,
            prior_feedback=None,
        )
        policy = record.get("policy")
        if policy is not None:
            result["policy"] = self.clean(
                {"is_valid": policy["is_valid"], "error": policy.get("error")}
            )
        feedback = record.get("prior_feedback")
        if feedback is not None:
            result["prior_feedback"] = self.clean(
                {
                    key: feedback.get(key)
                    for key in (
                        "gate",
                        "policy_error",
                        "failed_check_count",
                        "failed_checks",
                        "included_rejected_diff",
                    )
                }
            )
        return result


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _error(code: str, message: str, status: int, retry: int | None = None) -> JSONResponse:
    details: dict[str, Any] = {"code": code, "message": message}
    if retry is not None:
        details["retry_after_seconds"] = retry
    return JSONResponse(
        {"error": details},
        status_code=status,
        headers={"Retry-After": str(retry)} if retry is not None else None,
    )


class LiveService:
    """One FIFO worker, ephemeral client hashes, and durable public run evidence."""

    def __init__(
        self,
        launcher: LiveLauncher,
        adapter: MetaRepairAdapter,
        data_dir: Path,
        settings: LiveSettings,
    ) -> None:
        self.launcher = launcher
        self.adapter = adapter
        self.data_dir = data_dir
        self.settings = settings
        self.output = PublicOutput(adapter)
        self.corpus = load_corpus()
        self.cases = {case["id"]: case for case in self.corpus["holdout"]}
        self.available = False
        self.reason: str | None = "Service is starting."
        self.provider: str | None = None
        self.model: str | None = None
        self.runtime_limits: dict[str, Any] | None = None
        self.exporter: ApplicationExporter | None = None
        self.runs: dict[str, dict[str, Any]] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        # Includes the active run (reserved immediately at admission) at index 0.
        self.order: deque[str] = deque()
        self.clients: dict[str, deque[float]] = {}
        self.salt = secrets.token_bytes(32)

    def ledger(self) -> list[dict[str, Any]]:
        """Read persisted accounting, including records from previous processes."""
        path = self.data_dir / "ledger.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Invalid live ledger record")
            rows.append(row)
        return rows

    async def prepare(self) -> None:
        """Withhold admission unless provenance, runtime, provider, and storage pass."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            (self.data_dir / "runs").mkdir(exist_ok=True)
            self.ledger()
            manifest = verify_manifest()
            commit = manifest.get("source_commit")
            if commit is None:
                raise ValueError("Missing pinned fixture commit")
            self.exporter = ApplicationExporter(REPOSITORY_ROOT, commit, self.data_dir / "work")
            await self.launcher.preflight()
            runtime = getattr(self.launcher, "runtime", None)
            self.runtime_limits = self.output.clean(
                getattr(runtime, "resource_limits_status", None)
            )
        except Exception:
            self.reason = "Runtime, provenance, or persistent storage preflight failed."
            return
        try:
            probe = await self.adapter.probe()
        except Exception:
            self.reason = "Repair provider probe failed."
            return
        self.provider = self.output.text(probe.provider, 256)
        self.model = self.output.text(probe.model, 256)
        self.available = probe.available
        self.reason = (
            None
            if probe.available
            else self.output.text(probe.reason or "Repair provider is unavailable.")
        )
        required = self.settings.require_provider
        if self.available and required and probe.provider != required:
            self.available = False
            self.reason = f"The configured provider is {self.provider}, not {required}."

    def request_restart(self) -> None:
        """Ask the process supervisor for a fresh process and preflight."""
        if self.settings.exit_on_failure:
            os.kill(os.getpid(), signal.SIGTERM)

    async def retry_later(self) -> None:
        """Stay visibly unavailable, then restart to retry the preflight and probe."""
        await asyncio.sleep(self.settings.unavailable_retry_seconds)
        self.request_restart()

    def remaining(self) -> int:
        """Reserve daily capacity for queued work as well as persisted completions."""
        day = _now()[:10]
        completed = sum(
            str(row.get("created_at", row["finished_at"]))[:10] == day for row in self.ledger()
        )
        reserved = sum(
            str(self.runs[identifier]["created_at"])[:10] == day for identifier in self.order
        )
        return max(0, self.settings.daily_cap - completed - reserved)

    def position(self, identifier: str) -> int:
        return self.order.index(identifier) if identifier in self.order else 0

    def admit(self, body: RunRequest, request: Request) -> JSONResponse:
        """Check and reserve all limits without yielding between check and enqueue."""
        if body.defect_id not in self.cases:
            return _error("unknown_defect", "Choose a listed defect.", 400)
        if not self.available:
            return _error("unavailable", self.reason or "Service is unavailable.", 503)
        try:
            remaining = self.remaining()
        except (OSError, ValueError, KeyError):
            self.available = False
            self.reason = "Persistent accounting is unavailable."
            return _error("unavailable", self.reason, 503)
        if remaining == 0:
            now = datetime.now(UTC)
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return _error(
                "daily_cap_reached",
                "Today's live run limit has been reached.",
                429,
                max(1, int((midnight - now).total_seconds())),
            )
        address = request.client.host if request.client else "unknown"
        if self.settings.trust_proxy and request.headers.get("x-forwarded-for"):
            address = request.headers["x-forwarded-for"].split(",")[-1].strip()
        client_key = hashlib.sha256(self.salt + address.encode()).hexdigest()
        now_tick = time.monotonic()
        # Expire inactive buckets as well, so unique visitors cannot grow memory forever.
        for key in list(self.clients):
            history = self.clients[key]
            while history and history[0] <= now_tick - 3600:
                history.popleft()
            if not history:
                del self.clients[key]
        history = self.clients.get(client_key, deque())
        if len(history) >= self.settings.per_client_per_hour:
            retry = max(1, int(3600 - (now_tick - history[0])) + 1) if history else 3600
            return _error("rate_limited", "Hourly client limit reached.", 429, retry)
        if self.order and len(self.order) - 1 >= self.settings.max_waiting:
            return _error("queue_full", "The live repair queue is full.", 429, 30)
        identifier = str(uuid4())
        case = self.cases[body.defect_id]
        self.runs[identifier] = {
            "id": identifier,
            "defect_id": case["id"],
            "defect_title": case["title"],
            "defect_class": case["defect_class"],
            "state": "queued",
            "position": len(self.order),
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "provider": None,
            "model": None,
            "classification": None,
            "events": [],
            "outcome": None,
            "attempts": [],
        }
        history.append(now_tick)
        self.clients[client_key] = history
        self.order.append(identifier)
        self.queue.put_nowait(identifier)
        return JSONResponse(
            {"run_id": identifier, "position": self.position(identifier)}, status_code=202
        )

    def save(self, run: dict[str, Any]) -> None:
        """Atomically replace the run, then append and flush one accounting record."""
        path = self.data_dir / "runs" / f"{run['id']}.json"
        partial = path.with_suffix(".partial")
        with partial.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(run, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        partial.replace(path)
        row = {
            key: run[key]
            for key in (
                "id",
                "defect_id",
                "outcome",
                "provider",
                "model",
                "classification",
                "created_at",
                "finished_at",
            )
        }
        row["attempts"] = len(run["attempts"])
        with (self.data_dir / "ledger.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    async def worker(self) -> None:
        """Evaluate exactly one run at a time and retain terminal outcomes."""
        while True:
            identifier = await self.queue.get()
            run = self.runs[identifier]
            run.update(state="running", position=0, started_at=_now())
            started = time.monotonic()

            def event(item: dict[str, Any], run: dict[str, Any] = run) -> None:
                run["events"].append(self.output.clean(item))
                if item["stage"] == "propose" and item["status"] == "passed":
                    provider = item["data"]["provider"]
                    run.update(
                        provider=self.output.text(provider, 256),
                        model=self.output.text(item["data"]["model"], 256),
                        classification=classify(provider),
                    )

            try:
                async with asyncio.timeout(self.settings.run_timeout_seconds):
                    if self.exporter is None or not self.available:
                        raise RuntimeError("Service was not prepared")
                    case = self.cases[run["defect_id"]]
                    result = await evaluate_holdout(
                        case,
                        case_bytes(case).decode("utf-8"),
                        self.adapter,
                        LimitRecorder(self.launcher),
                        self.exporter,
                        self.corpus["incident_request"],
                        on_event=event,
                    )
                    run["outcome"] = self.output.text(result["outcome"])
                    run["attempts"] = [self.output.attempt(item) for item in result["attempts"]]
                    run["state"] = "finished"
            except TimeoutError:
                run.update(state="failed", outcome="timeout")
            except asyncio.CancelledError:
                run.update(state="failed", outcome="interrupted")
                raise
            except Exception:
                # Unknown infrastructure/cleanup errors quarantine further admission.
                run.update(state="failed", outcome="runtime_error")
                self.available = False
                self.reason = "Runtime failed; service restart is required."
            finally:
                run["finished_at"] = _now()
                event(
                    {
                        "t_ms": round((time.monotonic() - started) * 1000),
                        "stage": "done",
                        "status": "passed" if run["outcome"] == "verified" else "failed",
                        "attempt": None,
                        "message": "Live repair completed.",
                        "data": {"outcome": run["outcome"]},
                    }
                )
                try:
                    self.save(run)
                except OSError:
                    self.available = False
                    self.reason = "Persistent storage failed; service restart is required."
                self.order.popleft()
                self.queue.task_done()
                if not self.available:
                    self.request_restart()

    def aggregate(self) -> dict[str, Any]:
        """Aggregate the persisted ledger, never an in-memory substitute."""
        rows = self.ledger()
        result: dict[str, Any] = {
            "runs_total": len(rows),
            "verified": sum(row["outcome"] == "verified" for row in rows),
            "by_defect": {},
            "by_classification": {},
            "recent": [
                {
                    key: row.get(key)
                    for key in (
                        "id",
                        "defect_id",
                        "outcome",
                        "provider",
                        "model",
                        "classification",
                        "attempts",
                        "finished_at",
                    )
                }
                for row in reversed(rows[-20:])
            ],
        }
        for row in rows:
            for group, key in (("by_defect", "defect_id"), ("by_classification", "classification")):
                label = row.get(key) or "unknown"
                bucket = result[group].setdefault(label, {"runs": 0, "verified": 0})
                bucket["runs"] += 1
                bucket["verified"] += row["outcome"] == "verified"
        cleaned: dict[str, Any] = self.output.clean(result)
        return cleaned


def create_live_app(
    *,
    launcher: LiveLauncher | None = None,
    adapter: MetaRepairAdapter | None = None,
    data_dir: Path | str | None = None,
    settings: LiveSettings | None = None,
) -> FastAPI:
    """Build the public service; preflight and worker creation happen during lifespan."""
    config = settings if settings is not None else LiveSettings.from_environment()
    directory = Path(data_dir or os.environ.get("LIVE_DEMO_DATA_DIR", "data/live-demo"))

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        provider = (
            adapter if adapter is not None else MetaRepairAdapter(ModelSettings.from_environment())
        )
        backend = launcher if launcher is not None else IsolatedBackendLauncher()
        service = LiveService(backend, provider, directory, config)
        application.state.live = service
        task: asyncio.Task[None] | None = None
        try:
            await service.prepare()
            if service.available:
                task = asyncio.create_task(service.worker(), name="live-repair-worker")
            elif config.exit_on_failure:
                task = asyncio.create_task(service.retry_later(), name="live-repair-retry")
            yield
        finally:
            service.available = False
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if adapter is None:
                await provider.close()

    application = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default validation detail echoes untrusted submitted values.
        return _error("invalid_request", "Submit only a defect_id string.", 400)

    @application.get("/api/live/status")
    async def status(request: Request) -> dict[str, Any]:
        service: LiveService = request.app.state.live
        try:
            remaining = service.remaining()
        except (OSError, ValueError, KeyError):
            remaining = 0
            service.available = False
            service.reason = "Persistent accounting is unavailable."
        return {
            "available": service.available,
            "reason": service.reason,
            "provider": service.provider,
            "model": service.model,
            "classification": classify(service.provider) if service.provider else None,
            "queue": {
                "running": bool(service.order),
                "waiting": max(0, len(service.order) - 1),
                "max_waiting": config.max_waiting,
            },
            "limits": {
                "per_client_per_hour": config.per_client_per_hour,
                "daily_cap": config.daily_cap,
                "daily_remaining": remaining,
            },
            "defects": [
                {
                    "id": case["id"],
                    "title": case["title"],
                    "defect_class": case["defect_class"],
                    "expected_failures": case["expected_failures"],
                }
                for case in service.corpus["holdout"]
            ],
            "runtime_limits": service.runtime_limits,
        }

    @application.post("/api/live/runs")
    async def submit(body: RunRequest, request: Request) -> JSONResponse:
        service: LiveService = request.app.state.live
        return service.admit(body, request)

    @application.get("/api/live/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> Any:
        service: LiveService = request.app.state.live
        try:
            if str(UUID(run_id)) != run_id:
                raise ValueError("Not a canonical run ID")
        except ValueError:
            return _error("not_found", "Run not found.", 404)
        if run_id in service.runs:
            return {**service.runs[run_id], "position": service.position(run_id)}
        path = directory / "runs" / f"{run_id}.json"
        try:
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return _error("not_found", "Run not found.", 404)

    @application.get("/api/live/ledger")
    async def ledger(request: Request) -> Any:
        service: LiveService = request.app.state.live
        try:
            return service.aggregate()
        except (OSError, ValueError, KeyError):
            return _error("unavailable", "Persistent accounting is unavailable.", 503)

    return application


def create_app() -> FastAPI:
    """Uvicorn factory: ``uvicorn app.live_demo:create_app --factory``."""
    return create_live_app()
