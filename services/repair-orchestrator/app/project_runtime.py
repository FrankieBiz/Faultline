"""Universal ReproSpec runtime using the existing namespace/cgroup enforcement.

A fresh dev service runs on namespace-local loopback for every measurement.
Only its HTTP socket crosses the namespace; the oracle and browser driver live
outside it. No repository command is ever executed on the host.
"""

import asyncio
import base64
import hashlib
import json
import os
import shutil
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from app.database import utcnow
from app.isolated_runtime import (
    AggregateLimits,
    BackendResources,
    BoundedUDSTransport,
    BridgeServer,
    IsolatedRuntime,
    ManagedProcess,
)
from app.project import ProjectRun, tree_digest
from app.repro import Measurement, ReproEngine, ReproSession, ReproStep
from app.runtime import Phase, RuntimeArtifact, RuntimeExecution, RuntimeUnavailable
from app.snapshots import Snapshot
from shared.contracts.models import ExecutionReport, ExecutionVerdict, Observation, ObservationKind


class BrowserSession:
    def __init__(
        self,
        process: asyncio.subprocess.Process,
        backend: BackendResources,
        session_id: str,
        fingerprint: str | None,
    ) -> None:
        self.process = process
        self.backend = backend
        self.session_id = session_id
        self.expected_fingerprint = fingerprint

    async def exchange(self, payload: dict[str, Any]) -> Any:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps(payload).encode() + b"\n")
        await self.process.stdin.drain()
        response = json.loads(await self.process.stdout.readline())
        if "error" in response:
            raise RuntimeUnavailable("browser_step_failed")
        return response.get("result")

    async def perform(self, step: ReproStep) -> Measurement | bytes | None:
        result = await self.exchange(step.model_dump(mode="json"))
        if result is None:
            return None
        if "bytes" in result:
            return base64.b64decode(result["bytes"], validate=True)
        return Measurement(value=result["value"], status=result.get("status"))

    async def fingerprint(self) -> str | None:
        # Optional operator-declared log marker. Assertion evidence remains the
        # admission authority; logs are untrusted, never a model instruction.
        await asyncio.sleep(0.05)
        marker = self.expected_fingerprint
        return marker if marker and marker in self.backend.logs() else None


@dataclass
class SessionResources:
    backend: BackendResources
    browser: ManagedProcess | None = None
    bridge: BridgeServer | None = None
    bridge_task: asyncio.Task[None] | None = None
    bridge_socket: socket.socket | None = None


class ProjectRuntime(IsolatedRuntime):
    kind = "isolated-browser"

    def __init__(self, root: Path, run: ProjectRun) -> None:
        super().__init__()
        self.project_root = root
        self.run = run
        self.launcher = Path(__file__).with_name("project_launcher.py")
        self.sessions: dict[str, SessionResources] = {}
        self.aggregate_mode = "required"
        self.driver = Path(__file__).with_name("repro_browser.mjs")
        self.playwright = self.root / "tools/browser-runner/node_modules/playwright/index.mjs"

    def _sandbox(
        self, snapshot: Path, *, unit: str | None = None, limits: AggregateLimits | None = None
    ) -> list[str]:
        base = super()._sandbox(snapshot, unit=unit, limits=limits)
        args = [
            "--size",
            "268435456",
            "--tmpfs",
            "/tmp",
            "--setenv",
            "PATH",
            "/tmp/project/.venv/bin:/node/bin:/toolchain:/python/bin:/usr/bin",
        ]
        if self.node:
            prefix = Path(self.node).resolve().parent.parent
            args += ["--ro-bind", str(prefix), "/node"]
        uv = shutil.which("uv")
        if uv:
            args += ["--ro-bind", str(Path(uv).resolve()), "/toolchain/uv"]
        for name in ("node_modules", ".venv"):
            path = self.project_root / name
            if path.is_dir():
                if path.is_symlink():
                    raise RuntimeUnavailable("dependency_directory_must_not_be_symlinked")
                args += ["--ro-bind", str(path), "/dependencies/" + name]
        # uv virtualenvs may use an absolute interpreter symlink. Expose only
        # that interpreter distribution, never its parent cache/home directory.
        interpreter = self.project_root / ".venv/bin/python"
        if interpreter.exists():
            prefix = interpreter.resolve().parent.parent
            if (prefix / "bin").is_dir() and (prefix / "lib").is_dir():
                args += ["--ro-bind", str(prefix), str(prefix)]
        position = base.index("--remount-ro")
        return base[:position] + args + base[position:]

    async def _profile_preflight(self) -> None:
        import tempfile

        host_net = os.stat("/proc/self/ns/net").st_ino
        with tempfile.TemporaryDirectory(prefix="faultline-profile-") as directory:
            process = await ManagedProcess.start(
                *self._sandbox(Path(directory)),
                "/python/bin/python3.13",
                "-I",
                "-c",
                "import os; "
                f"assert os.stat('/proc/self/ns/net').st_ino != {host_net}; "
                "assert not os.path.exists('/snapshot/.env'); "
                "assert os.statvfs('/').f_flag & os.ST_RDONLY; "
                "print('project-profile-ready')",
                env={},
            )
            if (
                await process.wait(5) != 0
                or bytes(process.stdout).strip() != b"project-profile-ready"
            ):
                raise RuntimeUnavailable("project_profile_unavailable")

    async def reconcile(self, installation_id: str) -> None:
        self._installation = installation_id
        self._preflight = False
        await self._release_leftover_scopes()
        await self.backend_preflight()
        if not self.node or not self.driver.is_file() or not self.playwright.is_file():
            raise RuntimeUnavailable("playwright_driver_unavailable_run_make_setup")
        self._preflight = True

    async def prepare(self, installation_id: str, job_id: str, snapshot: Snapshot) -> None:
        if not self.ready or installation_id != self._installation:
            raise RuntimeUnavailable("isolated_runtime_unavailable")
        self._verify_project_snapshot(snapshot)

    async def activate(self, job_id: str, snapshot: Snapshot) -> None:
        self._verify_project_snapshot(snapshot)

    def _verify_project_snapshot(self, snapshot: Snapshot) -> None:
        target = snapshot.path / self.run.scenario.target_file
        if (
            tree_digest(snapshot.path) != snapshot.sha256
            or hashlib.sha256(target.read_bytes()).hexdigest() != snapshot.source_sha256
        ):
            raise RuntimeUnavailable("snapshot_identity_mismatch")

    async def _launch_service(
        self, owned: SessionResources, snapshot: Snapshot, session_id: str
    ) -> None:
        backend = owned.backend
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        backend.listener = listener
        address = "\0faultline-" + session_id
        listener.bind(address)
        listener.listen(16)
        port = 8765  # Private network namespace; every session can use the same port.
        backend.process = await ManagedProcess.start(
            *self._sandbox(snapshot.path, unit=backend.unit),
            "/python/bin/python3.13",
            "-I",
            "-u",
            "/trusted_backend.py",
            str(listener.fileno()),
            str(port),
            json.dumps(self.run.command(port)),
            env=self.scope_environment(backend.unit),
            pass_fds=(listener.fileno(),),
        )
        backend.client = httpx.AsyncClient(
            transport=BoundedUDSTransport(address),
            base_url="http://service",
            timeout=3,
            follow_redirects=False,
        )
        if backend.unit is not None:
            await self._await_scope(backend.unit, backend.process)
        backend.resource_limits = await self.verify_scope(backend.unit, backend.process)
        until = time.monotonic() + 10
        while time.monotonic() < until:
            if backend.process.process.returncode is not None:
                raise RuntimeUnavailable("dev_service_exited")
            try:
                response = await backend.client.get(self.run.project.health)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
        raise RuntimeUnavailable("dev_service_readiness_timeout")

    async def _start_bridge(self, owned: SessionResources) -> str:
        async def forward(request: Request) -> Response:
            if request.headers.get("host") != authority:
                return Response(status_code=403)
            body = bytearray()
            async for part in request.stream():
                body.extend(part)
                if len(body) > 65536:
                    return Response(status_code=413)
            client = owned.backend.client
            assert client is not None
            # Build a relative URL from the raw path: never accept an absolute
            # URL or a scheme-relative request that could redirect the transport.
            path = request.scope["raw_path"].decode("ascii")
            query = request.scope["query_string"].decode("ascii")
            headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower() not in {"host", "connection", "content-length", "transfer-encoding"}
            }
            headers["accept-encoding"] = "identity"
            try:
                response = await client.request(
                    request.method,
                    "http://service" + path + ("?" + query if query else ""),
                    content=bytes(body),
                    headers=headers,
                )
            except httpx.HTTPError:
                return Response(status_code=502)
            excluded = {"connection", "transfer-encoding", "content-encoding", "content-length"}
            result = Response(content=response.content, status_code=response.status_code)
            result.raw_headers = [
                (k, v) for k, v in response.headers.raw if k.decode().lower() not in excluded
            ]
            return result

        listener = socket.socket()
        owned.bridge_socket = listener
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        listener.setblocking(False)
        authority = f"127.0.0.1:{listener.getsockname()[1]}"
        application = Starlette(
            routes=[
                Route(
                    "/{path:path}",
                    forward,
                    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
                )
            ]
        )
        server = BridgeServer(
            uvicorn.Config(
                application,
                log_level="error",
                access_log=False,
                lifespan="off",
                timeout_keep_alive=1,
            )
        )
        owned.bridge = server
        owned.bridge_task = asyncio.create_task(server.serve(sockets=[listener]))
        async with asyncio.timeout(3):
            while not server.started:
                if owned.bridge_task.done():
                    raise RuntimeUnavailable("loopback_bridge_failed")
                await asyncio.sleep(0.01)
        return "http://" + authority

    async def _close_session(self, key: str) -> None:
        owned = self.sessions[key]
        try:
            if owned.browser is not None:
                await owned.browser.stop()
            if owned.bridge is not None:
                owned.bridge.should_exit = True
            if owned.bridge_task is not None:
                try:
                    await asyncio.wait_for(owned.bridge_task, timeout=2)
                except TimeoutError:
                    owned.bridge_task.cancel()
                    await asyncio.gather(owned.bridge_task, return_exceptions=True)
            if owned.bridge_socket is not None:
                owned.bridge_socket.close()
        finally:
            await self._release_session(owned.backend)
        del self.sessions[key]

    @asynccontextmanager
    async def _session(
        self, job_id: str, snapshot: Snapshot, directory: Path, holder: list[BackendResources]
    ) -> AsyncIterator[ReproSession]:
        session_id = str(uuid4())
        key = job_id + "/" + session_id
        owned = SessionResources(BackendResources(unit=self.scope_unit(session_id)))
        self.sessions[key] = owned
        holder.append(owned.backend)
        try:
            await self._launch_service(owned, snapshot, session_id)
            url = await self._start_bridge(owned)
            assert self.node is not None
            owned.browser = await ManagedProcess.start(
                self.node,
                str(self.driver),
                str(self.playwright),
                url,
                str(directory),
                env=self._trusted_environment(),
                interactive=True,
            )
            assert owned.browser.process.stdout is not None
            async with asyncio.timeout(10):
                if json.loads(await owned.browser.process.stdout.readline()) != {"ready": True}:
                    raise RuntimeUnavailable("browser_launch_failed")
            session = BrowserSession(
                owned.browser.process, owned.backend, session_id, self.run.repro.fingerprint
            )
            yield session
            async with asyncio.timeout(5):
                await session.exchange({"action": "finish"})
                assert owned.browser.process.stdin is not None
                owned.browser.process.stdin.close()
                if await owned.browser.process.wait() != 0:
                    raise RuntimeUnavailable("browser_finish_failed")
        finally:
            cleanup = asyncio.create_task(self._close_session(key))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def execute(
        self, job_id: str, execution_id: str, phase: Phase, snapshot: Snapshot, timeout_ms: int
    ) -> RuntimeExecution:
        self._verify_project_snapshot(snapshot)
        directory = snapshot.path.parents[1] / "evidence" / execution_id
        directory.mkdir(parents=True)
        holder: list[BackendResources] = []
        started = time.monotonic()
        engine = ReproEngine(lambda: self._session(job_id, snapshot, directory, holder))
        result = await engine.run(self.run.repro)
        logs = holder[0].logs() if holder else ""
        observations = []
        if result.fingerprint:
            observations.append(
                Observation(
                    id=str(uuid4()),
                    kind=ObservationKind.SERVER_EXCEPTION,
                    source=self.run.scenario.target_file,
                    message=result.fingerprint,
                    data={"case_id": result.session_id},
                    timestamp=utcnow(),
                )
            )
        verdict = (
            ExecutionVerdict.ERROR
            if result.error
            else ExecutionVerdict.FAILED
            if result.failure_signature
            else ExecutionVerdict.PASSED
        )
        report = ExecutionReport(
            execution_id=execution_id,
            case_id=result.session_id or str(uuid4()),
            scenario_id=self.run.scenario.id,
            verdict=verdict,
            duration_ms=(time.monotonic() - started) * 1000,
            observations=observations,
            assertions=result.assertions,
            raw_logs=json.dumps(
                {
                    "error": result.error,
                    "logs": logs,
                    "assertions": [a.model_dump() for a in result.assertions],
                }
            ),
        )
        artifacts = [RuntimeArtifact("logs", "text/plain", (logs or "(no service logs)").encode())]
        for role, name, content_type, limit in (
            ("screenshot", "screenshot.png", "image/png", 10 * 1024 * 1024),
            ("trace", "trace.zip", "application/zip", 25 * 1024 * 1024),
            ("requests", "requests.json", "application/json", 16 * 1024),
        ):
            path = directory / name
            if path.is_file() and path.stat().st_size <= limit:
                artifacts.append(RuntimeArtifact(role, content_type, path.read_bytes()))
        return RuntimeExecution(
            report,
            snapshot.generation_id,
            snapshot.sha256,
            {ExecutionVerdict.PASSED: 0, ExecutionVerdict.FAILED: 1, ExecutionVerdict.ERROR: 2}[
                verdict
            ],
            tuple(artifacts),
            holder[0].resource_limits if holder else None,
        )

    async def cleanup(self, installation_id: str, job_id: str) -> None:
        for key in list(self.sessions):
            if key.startswith(job_id + "/"):
                await self._close_session(key)
