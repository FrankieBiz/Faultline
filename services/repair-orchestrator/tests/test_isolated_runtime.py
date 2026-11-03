"""Safe runtime regressions: real fixture snapshots, bounded mock HTTP streams."""

import asyncio
import hashlib
import io
import json
import os
import shutil
import socket
import time
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from app.isolated_runtime import REPORT_LIMIT, BoundedUDSTransport, IsolatedRuntime, ManagedProcess
from app.policy import TARGET_FILE
from app.runtime import REGRESSION_ASSERTIONS, CandidateRejected, Phase, RuntimeUnavailable
from app.snapshots import Snapshot
from app.worker import matches_fingerprint
from shared.config import REGISTRY

ROOT = Path(
    os.environ.get("FAULTLINE_TEST_REPOSITORY_ROOT", str(Path(__file__).resolve().parents[3]))
)


class MockStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.read = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(100):
            self.read += 1
            yield b"x" * 8192

    async def aclose(self) -> None:
        self.closed = True


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, stream: MockStream, headers: dict[str, str] | None = None) -> None:
        self.stream = stream
        self.headers = headers or {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=self.stream, headers=self.headers)


@pytest.mark.asyncio
async def test_response_limit_is_enforced_during_iteration() -> None:
    stream = MockStream()
    transport = BoundedUDSTransport("/nonexistent-test-socket")
    await transport.inner.aclose()
    transport.inner = MockTransport(stream)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(RuntimeUnavailable, match="backend_response_limit"):
            await client.get("/")
    assert stream.read == REPORT_LIMIT // 8192 + 1
    assert stream.closed


@pytest.mark.asyncio
async def test_compressed_response_rejected_before_any_body_reads() -> None:
    stream = MockStream()
    transport = BoundedUDSTransport("/nonexistent-test-socket")
    await transport.inner.aclose()
    transport.inner = MockTransport(stream, {"content-encoding": "gzip"})
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(RuntimeUnavailable, match="compressed_response"):
            await client.get("/")
    assert stream.read == 0
    assert stream.closed


def snapshot(root: Path, healthy: bool) -> Snapshot:
    generation = str(uuid4())
    directory = root / "runtime/snapshots" / generation
    target = directory / "apps/buggyshop-backend/app"
    shutil.copytree(
        ROOT / "apps/buggyshop-backend/app", target, ignore=shutil.ignore_patterns("__pycache__")
    )
    if healthy:
        shutil.copyfile(ROOT / "fixtures/seeds/checkout_healthy.py", directory / TARGET_FILE)
    source = (directory / TARGET_FILE).read_text()
    entries = [
        (str(path.relative_to(directory)), "100644", hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(target.rglob("*.py"))
    ]
    digest = hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
    return Snapshot(
        directory,
        directory,
        generation,
        digest,
        source,
        hashlib.sha256(source.encode()).hexdigest(),
        "safe-fixture-test",
    )


def test_snapshot_identity_is_rechecked_before_mount(tmp_path: Path) -> None:
    snap = snapshot(tmp_path, False)
    IsolatedRuntime._verify_snapshot(snap)
    with (snap.path / TARGET_FILE).open("a") as stream:
        stream.write("\n# Safe test-only byte change\n")
    with pytest.raises(CandidateRejected, match="identity_mismatch"):
        IsolatedRuntime._verify_snapshot(snap)


@pytest.mark.asyncio
async def test_actual_browser_baseline_and_healthy_fixture_in_bubblewrap(tmp_path: Path) -> None:
    runtime = IsolatedRuntime(ROOT)
    installation, job = str(uuid4()), str(uuid4())
    await runtime.reconcile(installation)
    if not runtime.ready:
        if os.environ.get("FAULTLINE_REQUIRE_ISOLATED_TESTS") == "1":
            pytest.fail("Required isolated browser runtime is unavailable")
        pytest.skip("bubblewrap/real Chromium/compiled frontend unavailable")
    try:
        cases: list[tuple[Phase, bool]] = [("baseline", False), ("verification", True)]
        for phase, healthy in cases:
            snap = snapshot(tmp_path / phase, healthy)
            if phase == "baseline":
                await runtime.prepare(installation, job, snap)
            else:
                await runtime.activate(job, snap)
            result = await runtime.execute(job, str(uuid4()), phase, snap, 20000)
            assert result.report.duration_ms > 0
            assert result.snapshot_sha256 == snap.sha256
            limits = result.resource_limits
            assert limits is not None
            assert limits.verified is (runtime.aggregate_mode == "required")
            evidence = {item.role: item for item in result.artifacts}
            assert set(evidence) == {"screenshot", "trace", "requests", "logs"}
            assert evidence["screenshot"].content.startswith(b"\x89PNG\r\n\x1a\n")
            assert len(evidence["screenshot"].content) > 1000
            trace = zipfile.ZipFile(io.BytesIO(evidence["trace"].content))
            assert trace.testzip() is None
            if phase == "baseline":
                assert result.report.verdict.value == "failed"
                assert matches_fingerprint(result.report, REGISTRY["scripted_checkout_repair"])
            else:
                assert result.report.verdict.value == "passed"
                assert all(item.passed for item in result.report.assertions)
                assert REGRESSION_ASSERTIONS <= {item.id for item in result.report.assertions}
            assert runtime.generations[job].directory.is_relative_to(snap.path.parents[1])
    finally:
        await runtime.cleanup(installation, job)
    assert runtime.generations == {}


def process_tree(ancestor: int) -> dict[int, tuple[int, str, str]]:
    """Read only nonsecret process IDs/state; never inspect arguments or env."""
    states = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            states[int(entry.name)] = (int(fields[1]), fields[0], fields[19])
        except (OSError, IndexError, ValueError):
            pass
    descendants = {ancestor}
    while True:
        added = {pid for pid, state in states.items() if state[0] in descendants}
        if added <= descendants:
            return {pid: states[pid] for pid in descendants if pid in states}
        descendants.update(added)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_mode", ["eof", "cancel"])
async def test_trusted_browser_cleanup_on_liveness_eof_or_cancellation(stop_mode: str) -> None:
    runtime = IsolatedRuntime(ROOT)
    await runtime.reconcile("lifecycle-test")
    if not runtime.ready or runtime.node is None:
        if os.environ.get("FAULTLINE_REQUIRE_ISOLATED_TESTS") == "1":
            pytest.fail("Required trusted browser runtime is unavailable")
        pytest.skip("trusted real Chromium runtime unavailable")
    process = await ManagedProcess.start(
        runtime.node,
        "--input-type=module",
        "-e",
        "import {chromium} from '@playwright/test'; "
        "const browser=await chromium.launch({headless:true}); "
        "const page=await browser.newPage(); await page.setContent('<p>Lifecycle check</p>'); "
        "console.log('browser-ready'); await new Promise(resolve=>setTimeout(resolve,20000)); "
        "await browser.close();",
        cwd=ROOT / "tools/browser-runner",
        env=runtime._trusted_environment(),
    )
    try:
        until = time.monotonic() + 5
        while b"browser-ready" not in process.stdout and time.monotonic() < until:
            assert process.process.returncode is None
            await asyncio.sleep(0.02)
        assert b"browser-ready" in process.stdout
        descendants = process_tree(process.process.pid)
        assert len(descendants) >= 3, "supervisor, trusted Node, and Chromium must actually run"
        if stop_mode == "eof":
            # This closes the sole parent connection, exactly as process exit does.
            process.request_stop()
            await process.stop()
        else:
            wait = asyncio.create_task(process.wait(20))
            await asyncio.sleep(0)
            wait.cancel()
            with pytest.raises(asyncio.CancelledError):
                await wait
        assert process.process.returncode is not None
        for pid, (_, _, started) in descendants.items():
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            except FileNotFoundError:
                continue
            assert fields[19] != started or fields[0] == "Z", (
                f"owned browser process {pid} remains active"
            )
    finally:
        await process.stop()


@pytest.mark.asyncio
async def test_idle_reconcile_retries_transient_resource_cleanup(tmp_path: Path) -> None:
    from app.isolated_runtime import Generation

    runtime = IsolatedRuntime(ROOT)
    runtime._installation = "test-installation"
    runtime.bwrap = None  # This test exercises cleanup, not external preflight.
    snap = snapshot(tmp_path, False)
    directory = tmp_path / "owned-generation"
    directory.mkdir()
    runtime.generations["test-job"] = Generation(snap, directory)
    with patch(
        "app.isolated_runtime.shutil.rmtree", side_effect=OSError("test-only busy resource")
    ):
        with pytest.raises(OSError, match="busy resource"):
            await runtime.reconcile("test-installation")
    assert "test-job" in runtime.generations
    assert directory.is_dir()
    await runtime.reconcile("test-installation")
    assert not directory.exists()
    assert not runtime.generations
    assert not runtime.ready


@pytest.mark.parametrize("extra", ["unhashed-extra.txt", "apps/sibling.py", "empty", "fifo"])
def test_snapshot_rejects_unhashed_mount_entries(tmp_path: Path, extra: str) -> None:
    snap = snapshot(tmp_path, False)
    path = snap.path / extra
    if extra == "empty":
        path.mkdir()
    elif extra == "fifo":
        os.mkfifo(path)
    else:
        path.write_text("unattested bytes")
    with pytest.raises(CandidateRejected, match="snapshot_nonapplication_file"):
        IsolatedRuntime._verify_snapshot(snap)


@pytest.mark.parametrize("failure", [TimeoutError, OSError, asyncio.CancelledError])
async def test_backend_stop_failure_releases_scope_and_local_handles(
    tmp_path: Path, failure: type[BaseException], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.isolated_runtime import BackendResources

    runtime = IsolatedRuntime(ROOT)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    socket_path = tmp_path / "backend.sock"
    listener.bind(str(socket_path))
    process = AsyncMock(spec=ManagedProcess)
    process.stop.side_effect = failure("stop failed")
    client = httpx.AsyncClient()
    backend = BackendResources(
        unit="owned.scope",
        listener=listener,
        process=process,
        client=client,
        socket_path=socket_path,
    )
    release = AsyncMock()
    monkeypatch.setattr(runtime, "release_scope", release)
    with pytest.raises(failure):
        await runtime._release_session(backend)
    release.assert_awaited_once_with("owned.scope")
    assert listener.fileno() == -1
    assert client.is_closed
    assert not socket_path.exists()


async def test_release_session_closes_handles_when_stop_backend_itself_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.isolated_runtime import BackendResources

    runtime = IsolatedRuntime(ROOT)
    backend = BackendResources(listener=socket.socket(), client=httpx.AsyncClient())
    monkeypatch.setattr(
        runtime, "_stop_backend", AsyncMock(side_effect=RuntimeError("stop failed"))
    )
    with pytest.raises(RuntimeError, match="stop failed"):
        await runtime._release_session(backend)
    assert backend.listener is not None and backend.listener.fileno() == -1
    assert backend.client is not None and backend.client.is_closed


@pytest.mark.parametrize("failed_step", ["runner", "frontend", "backend", "bridge"])
async def test_generation_cleanup_attempts_every_owned_resource(
    tmp_path: Path, failed_step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.isolated_runtime import BackendResources, BridgeServer, Generation

    runtime = IsolatedRuntime(ROOT)
    directory = tmp_path / "generation"
    directory.mkdir()
    backend = BackendResources(listener=socket.socket(), client=httpx.AsyncClient())
    owned = Generation(snapshot(tmp_path, False), directory, backend)
    owned.runner = AsyncMock(spec=ManagedProcess)
    owned.frontend = AsyncMock(spec=ManagedProcess)
    owned.bridge_server = AsyncMock(spec=BridgeServer)
    owned.bridge_socket = socket.socket()

    async def bridge() -> None:
        if failed_step == "bridge":
            raise RuntimeError("teardown failed")

    owned.bridge_task = asyncio.create_task(bridge())
    stop_backend = AsyncMock()
    monkeypatch.setattr(runtime, "_stop_backend", stop_backend)
    stops = {
        "runner": owned.runner.stop,
        "frontend": owned.frontend.stop,
        "backend": stop_backend,
    }
    if failed_step != "bridge":
        stops[failed_step].side_effect = RuntimeError("teardown failed")
    runtime.generations["job"] = owned
    with pytest.raises(RuntimeError, match="teardown failed"):
        await runtime.cleanup("installation", "job")
    for stop in stops.values():
        stop.assert_awaited_once()
    assert owned.bridge_server.should_exit
    assert owned.bridge_task.done()
    assert owned.bridge_socket.fileno() == -1
    assert backend.listener is not None and backend.listener.fileno() == -1
    assert backend.client is not None and backend.client.is_closed
    assert runtime.generations["job"] is owned
    assert directory.exists()
