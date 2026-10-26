"""Authenticated FastAPI controller; run on loopback port 9000 without reload."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any, cast

import uvicorn
from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sse_starlette import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app.database import TERMINAL_STATES, Database, DatabaseError
from app.evidence import ArtifactError, EvidenceStore
from app.model_adapter import MetaRepairAdapter, ModelSettings
from app.runtime import Runtime, UnavailableRuntime
from app.snapshots import REPOSITORY_ROOT, SnapshotManager
from app.worker import RepairWorker
from shared.config import REGISTRY
from shared.contracts.models import ArtifactSummary, JobMode, JobRequest, OrchestratorJob

logger = logging.getLogger("faultline.orchestrator")


@dataclass(frozen=True)
class Settings:
    """Controller-only settings, with the token excluded from representation."""

    data_dir: Path = REPOSITORY_ROOT / "data"
    control_token: str | None = None
    inspector_origin: str = "http://127.0.0.1:4000"

    def __repr__(self) -> str:
        return f"Settings(data_dir={self.data_dir!r}, inspector_origin={self.inspector_origin!r})"

    @classmethod
    def from_environment(cls) -> Settings:
        """Read named settings without opening any local credential file."""
        return cls(
            data_dir=Path(os.environ.get("FAULTLINE_DATA_DIR", str(REPOSITORY_ROOT / "data"))),
            control_token=os.environ.get("FAULTLINE_CONTROL_TOKEN"),
            inspector_origin=os.environ.get("FAULTLINE_INSPECTOR_ORIGIN", "http://127.0.0.1:4000"),
        )


@dataclass
class Controller:
    """Lifespan-owned dependencies shared by routes and the serial worker."""

    settings: Settings
    database: Database
    worker: RepairWorker
    evidence: EvidenceStore


def controller(request: Request) -> Controller:
    """Resolve typed application state after successful lifespan initialization."""
    return cast(Controller, request.app.state.controller)


def authorize(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Use constant-time credential comparison on every protected route."""
    token = controller(request).settings.control_token
    scheme, separator, supplied = (authorization or "").partition(" ")
    if (
        not token
        or not separator
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied.encode(), token.encode())
    ):
        raise DatabaseError("unauthorized", 401)


Control = Annotated[Controller, Depends(controller)]


async def parse_submission(request: Request) -> JobRequest:
    """Decode wire JSON using the canonical strict contract's JSON semantics."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            raise DatabaseError("request_too_large", 413)
    try:
        return JobRequest.model_validate_json(bytes(body))
    except ValidationError as exc:
        raise DatabaseError("invalid_request", 422) from exc


def _accepted(job: OrchestratorJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "state": job.state.value,
        "effective_mode": job.effective_mode.value,
        "repair_block_reason": job.repair_block_reason,
    }


async def event_stream(
    database: Database,
    job_id: str,
    *,
    after: int = 0,
    request: Request | None = None,
    poll_seconds: float = 0.1,
) -> AsyncIterator[ServerSentEvent]:
    """Replay durable events, resume after Last-Event-ID, and close after completion."""
    while True:
        if request is not None and await request.is_disconnected():
            return
        # Snapshot terminal status first, so a concurrent final event is never skipped.
        terminal = database.get_job(job_id).state in TERMINAL_STATES
        events = database.list_events(job_id, after=after, limit=100)
        for event in events:
            after = event.sequence
            yield ServerSentEvent(
                id=str(event.sequence), event="job_event", data=event.model_dump_json()
            )
        if terminal and len(events) < 100:
            return
        if len(events) == 100:
            continue
        await asyncio.sleep(poll_seconds)


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    adapter: MetaRepairAdapter | None = None,
    runtime: Runtime | None = None,
    snapshots: SnapshotManager | None = None,
) -> FastAPI:
    """Construct the controller, allowing explicit trusted test/runtime injection."""
    configuration = settings if settings is not None else Settings.from_environment()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if not configuration.control_token:
            raise RuntimeError("FAULTLINE_CONTROL_TOKEN is required")
        owned_database = database is None
        db = database or Database(configuration.data_dir / "faultline.db")
        model = adapter or MetaRepairAdapter(ModelSettings.from_environment())
        store = EvidenceStore(
            db,
            configuration.data_dir,
            secrets=tuple(
                value for value in (configuration.control_token, model.settings.api_key) if value
            ),
        )
        worker = RepairWorker(
            db,
            model,
            runtime or UnavailableRuntime(),
            snapshots or SnapshotManager(configuration.data_dir),
            store,
        )
        application.state.controller = Controller(configuration, db, worker, store)
        try:
            await worker.start()
            logger.info(
                "Repair startup probe: time=%s result=%s",
                worker.probe_time,
                asdict(worker.probe) if worker.probe else None,
            )
            yield
        finally:
            await worker.stop()
            if adapter is None:
                await model.close()
            if owned_database:
                db.close()

    application = FastAPI(
        title="FaultLine Repair Orchestrator",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[configuration.inspector_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )

    @application.exception_handler(DatabaseError)
    async def database_error(request: Request, exc: DatabaseError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.code.replace("_", " "),
                    "job_id": exc.job_id,
                }
            },
            headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo request bodies, which may contain credentials or untrusted text.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Request validation failed.",
                    "job_id": None,
                }
            },
        )

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Return minimal process health without secrets or readiness claims."""
        return {"status": "ok", "app": "faultline-orchestrator"}

    from fastapi import APIRouter

    routes = APIRouter(prefix="/api/faultline", dependencies=[Depends(authorize)])

    @routes.get("/readiness")
    async def readiness(control: Control) -> dict[str, Any]:
        """Expose safe component readiness and deterministic/provider identity."""
        lease = control.database.get_lease()
        runtime_ready = control.worker.runtime.ready
        probe = control.worker.probe
        status = (
            "blocked"
            if lease.quarantined or not runtime_ready
            else ("ready" if probe and probe.available else "detect_only")
        )
        return {
            "status": status,
            "runtime_ready": runtime_ready,
            "quarantined": lease.quarantined,
            "model": asdict(probe) if probe else None,
            "probe_time": control.worker.probe_time,
            "reason": "cleanup_required"
            if lease.quarantined
            else ("isolated_runtime_unavailable" if not runtime_ready else None),
        }

    @routes.get("/scenarios")
    async def scenarios() -> dict[str, Any]:
        """List only server-owned scenario descriptions and permitted scope."""
        return {"scenarios": [scenario.model_dump(mode="json") for scenario in REGISTRY.values()]}

    @routes.post("/jobs", status_code=202)
    async def create_job(
        body: Annotated[JobRequest, Depends(parse_submission)],
        control: Control,
    ) -> dict[str, Any]:
        """Admit one idempotent job after readiness and quarantine checks."""
        existing = control.database.find_idempotent(body)
        if existing is not None:
            return _accepted(existing)
        lease = control.database.get_lease()
        if lease.quarantined:
            raise DatabaseError("cleanup_required", 503, lease.job_id)
        if not control.worker.runtime.ready:
            raise DatabaseError("isolated_runtime_unavailable", 503)
        probe = control.worker.probe
        effective = body.mode
        reason = None
        if body.mode == JobMode.REPAIR and (probe is None or not probe.available):
            effective = JobMode.DETECT
            reason = probe.reason if probe else "probe_unavailable"
        job = control.database.create_job(
            body, effective_mode=effective, repair_block_reason=reason
        )
        control.worker.notify()
        return _accepted(job)

    @routes.get("/jobs")
    async def list_jobs(
        control: Control, limit: Annotated[int, Query(ge=1, le=100)] = 20
    ) -> dict[str, Any]:
        """Return a bounded latest-first job history."""
        return {"jobs": control.database.list_jobs(limit)}

    @routes.get("/jobs/{job_id}")
    async def get_job(job_id: str, control: Control) -> dict[str, Any]:
        """Return persistent job evidence without exposing private storage paths."""
        job = control.database.get_job(job_id)
        executions = control.database.list_executions(job_id)
        return {
            "job": job,
            "baseline": next((item for item in executions if item.phase == "baseline"), None),
            "attempts": control.database.list_attempts(job_id),
            "executions": executions,
            "artifacts": [
                ArtifactSummary.model_validate(item.model_dump(exclude={"storage_key"}))
                for item in control.database.list_artifacts(job_id)
            ],
            "events": control.database.list_events(job_id, limit=1000),
        }

    @routes.get("/jobs/{job_id}/events")
    async def events(
        job_id: str,
        request: Request,
        control: Control,
        last_event_id: Annotated[int | None, Header(ge=0)] = None,
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> EventSourceResponse:
        """Stream authenticated stage events, with monotonic replay cursors."""
        control.database.get_job(job_id)
        return EventSourceResponse(
            event_stream(
                control.database,
                job_id,
                after=last_event_id if last_event_id is not None else after,
                request=request,
            ),
            ping=15,
            send_timeout=5,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @routes.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: str, control: Control, response: Response) -> OrchestratorJob:
        """Persist cancellation intent; completed results remain unchanged."""
        job = control.database.request_cancel(job_id)
        response.status_code = 200 if job.state in TERMINAL_STATES else 202
        control.worker.notify()
        return job

    @routes.post("/reset")
    async def reset(control: Control) -> dict[str, str]:
        """Reconcile idle owned resources and release cleanup quarantine."""
        try:
            await control.worker.reset()
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError("reset_failed", 503) from exc
        return {"status": "ok"}

    @routes.get("/artifacts/{artifact_id}")
    async def artifact(artifact_id: str, control: Control) -> Response:
        """Serve verified registered evidence as inert, private downloads."""
        item = control.database.get_artifact(artifact_id)
        try:
            content = control.evidence.read(item)
        except ArtifactError as exc:
            raise DatabaseError("artifact_error", 503) from exc
        return Response(
            content,
            media_type=item.content_type,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'",
                "Content-Disposition": f'attachment; filename="{item.id}"',
                "Cache-Control": "no-store",
            },
        )

    application.include_router(routes)
    return application


app = create_app()


def main() -> None:
    """Start exactly one controller on loopback port 9000."""
    uvicorn.run("app.main:app", host="127.0.0.1", port=9000, workers=1)


if __name__ == "__main__":
    main()
