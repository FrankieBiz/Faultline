"""Linux bubblewrap backend isolation with an external trusted browser oracle.

Only candidate Python executes in the private namespace. Trusted HTTP regression,
the frontend proxy, Chromium, and the fixed browser CLI execute outside it. This
is process/filesystem/network isolation, not a VM or a production deployer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
import sysconfig
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response

from app.database import utcnow
from app.http_regression import regression
from app.runtime import (
    CandidateRejected,
    Phase,
    RuntimeArtifact,
    RuntimeExecution,
    RuntimeUnavailable,
)
from app.snapshots import REPOSITORY_ROOT, Snapshot, contained_path
from shared.config import REGISTRY
from shared.contracts.models import (
    AssertionResult,
    ExecutionReport,
    ExecutionVerdict,
    Observation,
    ObservationKind,
)

LOG_LIMIT = 256 * 1024
REPORT_LIMIT = 64 * 1024


class BoundedUDSTransport(httpx.AsyncBaseTransport):
    """Bound every untrusted backend response before HTTPX buffers or decodes it."""

    def __init__(self, uds: str) -> None:
        self.inner: httpx.AsyncBaseTransport = httpx.AsyncHTTPTransport(uds=uds)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async with asyncio.timeout(3):
            return await self._bounded_request(request)

    async def _bounded_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        try:
            # Compressed bodies could expand after a raw-byte cap; the fixture
            # requires plain JSON, so reject unsupported compression outright.
            if response.headers.get("content-encoding", "identity") != "identity":
                raise RuntimeUnavailable("backend_compressed_response_forbidden")
            content = bytearray()
            async for chunk in response.aiter_raw():
                if len(content) + len(chunk) > REPORT_LIMIT:
                    raise RuntimeUnavailable("backend_response_limit")
                content.extend(chunk)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=request,
            )
        finally:
            await response.aclose()

    async def aclose(self) -> None:
        await self.inner.aclose()


@dataclass
class ManagedProcess:
    """Own every process and pipe task until an observed, reaped exit."""

    process: asyncio.subprocess.Process
    pumps: list[asyncio.Task[None]] = field(default_factory=list)
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    overflow: bool = False
    liveness_fd: int | None = None

    @classmethod
    async def start(
        cls,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        pass_fds: tuple[int, ...] = (),
    ) -> ManagedProcess:
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
        supervisor = Path(__file__).with_name("process_supervisor.py")
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(supervisor),
                str(read_fd),
                ",".join(str(fd) for fd in pass_fds),
                *args,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                pass_fds=(read_fd, *pass_fds),
            )
        )
        try:
            process = await asyncio.shield(spawn)
        except BaseException:
            os.close(write_fd)
            try:
                process = await spawn
                await process.communicate()
            finally:
                os.close(read_fd)
            raise
        os.close(read_fd)
        owned = cls(process, liveness_fd=write_fd)

        async def drain(stream: asyncio.StreamReader, target: bytearray) -> None:
            while chunk := await stream.read(8192):
                remaining = LOG_LIMIT - len(target)
                target.extend(chunk[: max(0, remaining)])
                if len(chunk) > remaining:
                    owned.overflow = True
                    owned.request_stop()

        assert process.stdout is not None and process.stderr is not None
        owned.pumps = [
            asyncio.create_task(drain(process.stdout, owned.stdout)),
            asyncio.create_task(drain(process.stderr, owned.stderr)),
        ]
        return owned

    def request_stop(self) -> None:
        if self.liveness_fd is not None:
            os.close(self.liveness_fd)
            self.liveness_fd = None

    async def stop(self) -> None:
        """Close the sole liveness writer, then confirm supervisor cleanup/reap."""
        self.request_stop()
        async with asyncio.timeout(4):
            await self.process.wait()
            await asyncio.gather(*self.pumps)

    async def wait(self, timeout: float) -> int:
        try:
            async with asyncio.timeout(timeout):
                result = await self.process.wait()
                await asyncio.gather(*self.pumps)
                if self.overflow:
                    raise RuntimeUnavailable("trusted_process_output_limit")
                return result
        finally:
            await asyncio.shield(self.stop())


@dataclass
class Generation:
    snapshot: Snapshot
    directory: Path
    backend: ManagedProcess | None = None
    frontend: ManagedProcess | None = None
    runner: ManagedProcess | None = None
    bridge_server: uvicorn.Server | None = None
    bridge_task: asyncio.Task[None] | None = None
    bridge_socket: socket.socket | None = None
    backend_socket: socket.socket | None = None
    client: httpx.AsyncClient | None = None
    frontend_url: str = ""


class IsolatedRuntime:
    """Execute only application exports in a fresh Linux namespace per generation."""

    kind = "isolated-browser"

    def __init__(self, repository_root: Path = REPOSITORY_ROOT) -> None:
        self.root = repository_root.resolve()
        self.launcher = Path(__file__).with_name("isolated_backend.py")
        self.python = Path(sys.base_prefix).resolve()
        self.packages = Path(sysconfig.get_path("purelib")).resolve()
        self.bwrap = shutil.which("bwrap")
        self.node = shutil.which("node")
        self.next_cli = self.root / "apps/buggyshop-frontend/node_modules/next/dist/bin/next"
        self.runner_cli = self.root / "tools/browser-runner/dist/cli.js"
        self.generations: dict[str, Generation] = {}
        self._preflight = False
        self._installation: str | None = None

    @property
    def ready(self) -> bool:
        return self._preflight

    def _sandbox(self, snapshot: Path) -> list[str]:
        if self.bwrap is None:
            raise RuntimeUnavailable("bubblewrap_unavailable")
        args = [
            self.bwrap,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--cap-drop",
            "ALL",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--size",
            "16777216",
            "--tmpfs",
            "/tmp",
            "--size",
            "1048576",
            "--tmpfs",
            "/run",
            "--ro-bind",
            "/usr",
            "/usr",
        ]
        for name in ("/lib", "/lib64"):
            if Path(name).exists():
                args.extend(("--ro-bind", name, name))
        args.extend(
            (
                "--ro-bind",
                str(self.python),
                "/python",
                "--ro-bind",
                str(self.packages),
                "/packages",
                "--ro-bind",
                str(snapshot),
                "/snapshot",
                "--ro-bind",
                str(self.launcher),
                "/trusted_backend.py",
                "--setenv",
                "PATH",
                "/python/bin:/usr/bin",
                "--setenv",
                "HOME",
                "/tmp",
                "--setenv",
                "PYTHONDONTWRITEBYTECODE",
                "1",
                "--remount-ro",
                "/dev",
                "--remount-ro",
                "/proc",
                "--remount-ro",
                "/",
                "--chdir",
                "/tmp",
            )
        )
        return args

    async def reconcile(self, installation_id: str) -> None:
        """Run an isolated interpreter preflight before admitting any jobs."""
        self._preflight = False
        if self._installation is not None and self._installation != installation_id:
            raise RuntimeUnavailable("installation_identity_mismatch")
        for job_id in tuple(self.generations):
            await self.cleanup(installation_id, job_id)
        self._installation = installation_id
        required = [
            self.launcher,
            self.next_cli,
            self.runner_cli,
            self.root / "apps/buggyshop-frontend/.next/BUILD_ID",
        ]
        if not self.bwrap or not self.node or not all(path.is_file() for path in required):
            return
        # The exact interpreter profile must launch without mounting project/home.
        with tempfile.TemporaryDirectory(prefix="faultline-preflight-") as directory:
            empty = Path(directory)
            process = await ManagedProcess.start(
                *self._sandbox(empty),
                "/python/bin/python3.13",
                "-I",
                "-c",
                "import os,socket; assert not os.path.exists('/home'); "
                "assert not os.path.exists('/snapshot/.env'); "
                "assert os.statvfs('/').f_flag & os.ST_RDONLY; "
                "assert os.statvfs('/dev').f_flag & os.ST_RDONLY; "
                "assert os.statvfs('/tmp').f_blocks * os.statvfs('/tmp').f_frsize <= 16777216; "
                "assert os.statvfs('/run').f_blocks * os.statvfs('/run').f_frsize <= 1048576; "
                "print('isolated-profile-ready')",
                env={},
            )
            if (
                await process.wait(5) != 0
                or bytes(process.stdout).strip() != b"isolated-profile-ready"
            ):
                return
        # Query actual Chromium availability without launching or importing candidate code.
        process = await ManagedProcess.start(
            self.node,
            "--input-type=module",
            "-e",
            "import {chromium} from '@playwright/test'; "
            "const browser=await chromium.launch({headless:true}); await browser.close();",
            cwd=self.root / "tools/browser-runner",
            env=self._trusted_environment(),
        )
        self._preflight = await process.wait(5) == 0

    def _trusted_environment(self) -> dict[str, str]:
        # Never propagate control/model credentials or load a project environment file.
        env = {"PATH": os.defpath, "NODE_ENV": "production", "NEXT_TELEMETRY_DISABLED": "1"}
        # Playwright uses HOME only to locate its installed, trusted browser cache.
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(Path.home() / ".cache/ms-playwright")
        return env

    async def prepare(self, installation_id: str, job_id: str, snapshot: Snapshot) -> None:
        if not self.ready or installation_id != self._installation:
            raise RuntimeUnavailable("isolated_runtime_unavailable")
        if job_id in self.generations:
            raise RuntimeUnavailable("job_runtime_already_exists")
        await self._activate(job_id, snapshot)

    async def activate(self, job_id: str, snapshot: Snapshot) -> None:
        await self.cleanup(self._installation or "", job_id)
        await self._activate(job_id, snapshot)

    async def _activate(self, job_id: str, snapshot: Snapshot) -> None:
        if not self.ready or str(UUID(job_id)) != job_id:
            raise RuntimeUnavailable("isolated_runtime_unavailable")
        self._verify_snapshot(snapshot)
        if snapshot.path.parent.name != "snapshots" or snapshot.path.name != snapshot.generation_id:
            raise RuntimeUnavailable("snapshot_owned_layout_required")
        directory = contained_path(snapshot.path.parents[1], f"isolated/{snapshot.generation_id}")
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        owned = Generation(snapshot, directory)
        self.generations[job_id] = owned  # Register intent before creating resources.
        try:
            # Abstract sockets avoid Linux's 108-byte filesystem pathname limit
            # and cannot be redirected with an untrusted filesystem symlink.
            socket_name = "\0faultline-" + snapshot.generation_id
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            owned.backend_socket = listener
            listener.bind(socket_name)
            listener.listen(16)
            owned.backend = await ManagedProcess.start(
                *self._sandbox(snapshot.path),
                "/python/bin/python3.13",
                "-I",
                "/trusted_backend.py",
                str(listener.fileno()),
                env={},
                pass_fds=(listener.fileno(),),
            )
            owned.client = httpx.AsyncClient(
                transport=BoundedUDSTransport(socket_name),
                base_url="http://isolated-backend",
                timeout=3,
                follow_redirects=False,
            )
            await self._wait_backend(owned)
            bridge_url = await self._bridge(owned)
            port = self._free_port()
            assert self.node is not None
            owned.frontend = await ManagedProcess.start(
                self.node,
                str(self.next_cli),
                "start",
                "-p",
                str(port),
                "-H",
                "127.0.0.1",
                cwd=self.root / "apps/buggyshop-frontend",
                env={**self._trusted_environment(), "BUGGYSHOP_BACKEND_URL": bridge_url},
            )
            owned.frontend_url = f"http://127.0.0.1:{port}"
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    if owned.frontend.process.returncode is not None:
                        raise CandidateRejected("trusted_frontend_failed")
                    try:
                        response = await client.get(f"{owned.frontend_url}/api/products")
                        if (
                            response.status_code == 200
                            and response.json() == (await owned.client.get("/api/products")).json()
                        ):
                            return
                    except (httpx.HTTPError, ValueError):
                        pass
                    await asyncio.sleep(0.1)
                raise CandidateRejected("trusted_frontend_readiness_timeout")
        except BaseException:
            await asyncio.shield(self.cleanup(self._installation or "", job_id))
            raise

    @staticmethod
    def _verify_snapshot(snapshot: Snapshot) -> None:
        """Recompute the application export identity immediately before mounting."""
        application = contained_path(snapshot.path, "apps/buggyshop-backend/app")
        entries: list[tuple[str, str, str]] = []
        for path in sorted(application.rglob("*")):
            if path.is_symlink():
                raise CandidateRejected("snapshot_symlink_forbidden")
            if path.is_file():
                if path.suffix != ".py":
                    raise CandidateRejected("snapshot_nonapplication_file")
                entries.append(
                    (
                        path.relative_to(snapshot.path).as_posix(),
                        "100644",
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
        actual = hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
        target = contained_path(snapshot.path, REGISTRY["scripted_checkout_repair"].target_file)
        if (
            actual != snapshot.sha256
            or hashlib.sha256(target.read_bytes()).hexdigest() != snapshot.source_sha256
        ):
            raise CandidateRejected("snapshot_identity_mismatch")

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    async def _wait_backend(self, owned: Generation) -> None:
        assert owned.client is not None and owned.backend is not None
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if owned.backend.process.returncode is not None:
                raise CandidateRejected("isolated_backend_failed")
            try:
                response = await owned.client.get("/healthz")
                if response.status_code == 200 and response.json() == {
                    "status": "ok",
                    "app": "buggyshop-api",
                }:
                    return
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(0.05)
        raise CandidateRejected("isolated_backend_readiness_timeout")

    async def _bridge(self, owned: Generation) -> str:
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        client = owned.client
        assert client is not None

        @app.api_route("/{path:path}", methods=["GET", "POST"])
        async def forward(path: str, request: Request) -> Response:
            # Only backend API/health requests are ever forwarded to the private UDS.
            if not (path.startswith("api/") or path == "healthz"):
                return Response(status_code=404)
            body = bytearray()
            async with asyncio.timeout(3):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 16 * 1024:
                        return Response(status_code=413)
                    body.extend(chunk)
            response = await client.request(
                request.method,
                "/" + path,
                params=request.query_params,
                content=bytes(body),
                headers={
                    key: value
                    for key, value in request.headers.items()
                    if key.lower() in {"content-type", "x-faultline-case-id"}
                },
            )
            if len(response.content) > REPORT_LIMIT:
                return Response(status_code=502)
            return Response(
                response.content,
                status_code=response.status_code,
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() in {"content-type", "x-request-id"}
                },
            )

        listener = socket.socket()
        owned.bridge_socket = listener
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        listener.setblocking(False)
        server = BridgeServer(
            uvicorn.Config(
                app,
                log_level="warning",
                access_log=False,
                lifespan="off",
                log_config=None,
            )
        )
        # The controller owns process-wide signal handlers, not the embedded bridge.
        owned.bridge_server = server
        owned.bridge_task = asyncio.create_task(server.serve(sockets=[listener]))
        until = time.monotonic() + 3
        while not server.started:
            if owned.bridge_task.done():
                owned.bridge_task.result()
                raise RuntimeUnavailable("bridge_failed")
            if time.monotonic() > until:
                raise RuntimeUnavailable("bridge_readiness_timeout")
            await asyncio.sleep(0.01)
        return f"http://127.0.0.1:{listener.getsockname()[1]}"

    async def execute(
        self, job_id: str, execution_id: str, phase: Phase, snapshot: Snapshot, timeout_ms: int
    ) -> RuntimeExecution:
        owned = self.generations.get(job_id)
        if owned is None or owned.snapshot != snapshot or owned.client is None:
            raise RuntimeUnavailable("generation_not_active")
        assert self.node is not None and owned.backend is not None
        started = time.monotonic()
        case_id = str(uuid4())
        evidence_dir = owned.directory / f"evidence-{execution_id}"
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                owned.runner = await ManagedProcess.start(
                    self.node,
                    str(self.runner_cli),
                    "--base-url",
                    owned.frontend_url,
                    "--execution-id",
                    execution_id,
                    "--case-id",
                    case_id,
                    "--artifacts-dir",
                    str(evidence_dir),
                    "--timeout-ms",
                    str(min(timeout_ms, 20000)),
                    cwd=self.root / "tools/browser-runner",
                    env=self._trusted_environment(),
                )
                code = await owned.runner.wait(timeout_ms / 1000)
                if code not in {0, 1, 2, 3}:
                    raise RuntimeUnavailable("browser_runner_failed")
                report_path = contained_path(evidence_dir, "report.json")
                if not report_path.is_file() or report_path.stat().st_size > REPORT_LIMIT:
                    raise RuntimeUnavailable("browser_report_missing_or_oversized")
                report = ExecutionReport.model_validate_json(report_path.read_bytes())
                if report.execution_id != execution_id or report.case_id != case_id:
                    raise RuntimeUnavailable("browser_identity_mismatch")
                expected = {0: "passed", 1: "failed", 2: "error", 3: "error"}[code]
                if report.verdict.value != expected:
                    raise RuntimeUnavailable("browser_exit_disagreement")
                artifacts = self._artifacts(evidence_dir, execution_id)
                if code == 3:
                    report = report.model_copy(update={"verdict": ExecutionVerdict.TIMED_OUT})
                if phase == "baseline" and code == 1:
                    await self._baseline(report, owned, case_id)
                elif phase == "verification" and code == 0:
                    report.assertions.extend(await regression(owned.client))
                    checks = {item.id: item.passed for item in report.assertions}
                    report.assertions.append(
                        AssertionResult(
                            id="confirmation.checkout",
                            passed=checks.get("checkout.confirmation_shown") is True
                            and checks.get("checkout.confirmation_matches_order") is True,
                            expected="actual browser confirmation matches created order",
                            observed="browser oracle confirmation assertions",
                            duration_ms=0.0,
                        )
                    )
                    if not all(item.passed for item in report.assertions):
                        report = report.model_copy(update={"verdict": ExecutionVerdict.FAILED})
                        code = 1
                report = report.model_copy(
                    update={"duration_ms": (time.monotonic() - started) * 1000}
                )
                logs = bytes(owned.backend.stderr).decode("utf-8", errors="replace")
                artifacts.append(
                    RuntimeArtifact(
                        "logs", "text/plain", logs.encode() or b"No backend exceptions observed.\n"
                    )
                )
                return RuntimeExecution(
                    report, snapshot.generation_id, snapshot.sha256, code, tuple(artifacts)
                )
        finally:
            if owned.runner is not None:
                await asyncio.shield(owned.runner.stop())
                owned.runner = None

    def _artifacts(self, root: Path, execution_id: str) -> list[RuntimeArtifact]:
        manifest_path = contained_path(root, "artifacts.json")
        if not manifest_path.is_file() or manifest_path.stat().st_size > REPORT_LIMIT:
            raise RuntimeUnavailable("artifact_manifest_missing_or_oversized")
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("execution_id") != execution_id:
            raise RuntimeUnavailable("artifact_manifest_identity_mismatch")
        roles = {
            "failure_screenshot": "screenshot",
            "final_screenshot": "screenshot",
            "trace": "trace",
            "network_log": "requests",
        }
        limits = {"screenshot": 10 * 1024 * 1024, "trace": 25 * 1024 * 1024, "requests": 16 * 1024}
        results: list[RuntimeArtifact] = []
        seen: set[str] = set()
        for entry in manifest.get("artifacts", []):
            role = roles.get(entry.get("role"))
            if role is None:
                continue
            path = contained_path(root, entry["relative_path"])
            if role in seen or not path.is_file() or not 0 < path.stat().st_size <= limits[role]:
                raise RuntimeUnavailable("artifact_missing_duplicate_or_oversized")
            content = path.read_bytes()
            if (
                len(content) != entry["size_bytes"]
                or hashlib.sha256(content).hexdigest() != entry["sha256"]
            ):
                raise RuntimeUnavailable("artifact_checksum_mismatch")
            results.append(RuntimeArtifact(role, entry["content_type"], content))
            seen.add(role)
        if seen != {"screenshot", "trace", "requests"}:
            raise RuntimeUnavailable("required_browser_evidence_missing")
        return results

    async def _baseline(self, report: ExecutionReport, owned: Generation, case_id: str) -> None:
        """Correlate actual browser HTTP failure with actual server JSON logs."""
        assert owned.client is not None and owned.backend is not None
        confirmation = next(
            (item for item in report.assertions if item.id == "checkout.confirmation_shown"), None
        )
        visible = (
            confirmation is not None
            and not confirmation.passed
            and confirmation.observed.startswith("failure alert:")
        )
        response = await owned.client.get("/api/orders", headers={"X-Faultline-Case-Id": case_id})
        no_order = response.status_code == 200 and response.json() == {"orders": []}
        for name, passed, observed in (
            (
                "checkout.failure_visible",
                visible,
                confirmation.observed if confirmation else "UI outcome missing",
            ),
            ("checkout.no_order_on_failure", no_order, response.text[:1024]),
        ):
            report.assertions.append(
                AssertionResult(
                    id=name,
                    passed=passed,
                    expected="measured baseline failure evidence",
                    observed=observed,
                    duration_ms=0.0,
                )
            )
        fingerprint = REGISTRY[report.scenario_id].error_fingerprint
        # Let the independent stderr reader drain logs already emitted with the response.
        await asyncio.sleep(0)
        for line in bytes(owned.backend.stderr).decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (
                event.get("case_id") != case_id
                or event.get("route") != "/api/checkout"
                or event.get("exception_type") != "TypeError"
                or fingerprint not in event.get("message", "")
            ):
                continue
            request_id = event.get("request_id")
            http = next(
                (
                    entry
                    for entry in report.observations
                    if entry.kind == ObservationKind.HTTP_ERROR
                    and isinstance(entry.data.get("request"), dict)
                    and entry.data["request"].get("request_id") == request_id
                    and entry.data["request"].get("status") == 500
                ),
                None,
            )
            if http is None:
                continue
            http.source = "POST /api/checkout"
            http.data.update(status=500, request_id=request_id, case_id=case_id)
            report.observations.append(
                Observation(
                    id=str(uuid4()),
                    kind=ObservationKind.SERVER_EXCEPTION,
                    source=REGISTRY[report.scenario_id].target_file,
                    message=event["message"],
                    timestamp=utcnow(),
                    data={
                        "request_id": request_id,
                        "case_id": case_id,
                        "exception_type": "TypeError",
                        "traceback": event.get("traceback"),
                    },
                )
            )

    async def cleanup(self, installation_id: str, job_id: str) -> None:
        if self._installation is not None and installation_id != self._installation:
            raise RuntimeUnavailable("installation_identity_mismatch")
        owned = self.generations.get(job_id)
        if owned is None:
            return
        # Do not forget ownership or remove the directory until every cleanup succeeds.
        for process in (owned.runner, owned.frontend, owned.backend):
            if process is not None:
                await process.stop()
        if owned.bridge_server is not None:
            owned.bridge_server.should_exit = True
        if owned.bridge_task is not None:
            async with asyncio.timeout(3):
                await owned.bridge_task
        if owned.bridge_socket is not None:
            owned.bridge_socket.close()
        if owned.backend_socket is not None:
            owned.backend_socket.close()
        if owned.client is not None:
            await owned.client.aclose()
        shutil.rmtree(owned.directory)
        self.generations.pop(job_id)


class BridgeServer(uvicorn.Server):
    """Leave controller signal ownership intact."""

    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield
