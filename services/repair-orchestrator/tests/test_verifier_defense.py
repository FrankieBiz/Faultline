"""Adversarial verification I/O and subprocess ownership regressions."""

import asyncio
import os
import subprocess
import sys
import textwrap
import tracemalloc
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app import repro
from app.isolated_runtime import (
    HEADER_COUNT_LIMIT,
    HEADER_LIMIT,
    REPORT_LIMIT,
    BoundedBackendTransport,
    ManagedProcess,
)
from app.runtime import RuntimeUnavailable


class CandidateStream(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes, error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.reads = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.reads += 1
            yield chunk
        if self.error:
            raise self.error

    async def aclose(self) -> None:
        self.closed = True


def candidate_client(
    stream: CandidateStream, headers: list[tuple[bytes, bytes]] | None = None
) -> httpx.AsyncClient:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers, stream=stream)

    return httpx.AsyncClient(
        transport=BoundedBackendTransport(httpx.MockTransport(respond)), base_url="http://candidate"
    )


@pytest.mark.parametrize("size", [0, REPORT_LIMIT - 1, REPORT_LIMIT])
async def test_accepts_body_at_or_below_limit(size: int) -> None:
    stream = CandidateStream(b"x" * size)
    async with candidate_client(stream) as client:
        response = await client.get("/")
    assert response.content == b"x" * size
    assert stream.closed


@pytest.mark.parametrize("chunks", [(REPORT_LIMIT + 1,), (REPORT_LIMIT, 1), (8192,) * 9])
async def test_rejects_body_over_limit_without_reading_tail(chunks: tuple[int, ...]) -> None:
    stream = CandidateStream(*(b"x" * size for size in chunks), b"unread")
    async with candidate_client(stream) as client:
        with pytest.raises(RuntimeUnavailable, match="backend_response_limit"):
            await client.get("/")
    assert stream.reads == len(chunks)
    assert stream.closed


async def test_giant_chunk_is_rejected_before_copying() -> None:
    stream = CandidateStream(b"x" * (8 * 1024 * 1024))
    async with candidate_client(stream) as client:
        tracemalloc.start()
        try:
            with pytest.raises(RuntimeUnavailable, match="backend_response_limit"):
                await client.get("/")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert peak < 1024 * 1024
    assert stream.closed


@pytest.mark.parametrize(
    "headers",
    [
        [(b"x-huge", b"x" * (16 * 1024))],
        [(b"x" * (16 * 1024), b"v")],
        [(b"x-repeat", b"x" * 1024)] * 20,
        [(b"x", b"v")] * 101,
        [(b"content-encoding", b"identity"), (b"content-encoding", b"gzip")],
    ],
    ids=["value", "name", "aggregate-duplicates", "count", "duplicate-encoding"],
)
async def test_rejects_hostile_headers_before_body_read(headers: list[tuple[bytes, bytes]]) -> None:
    stream = CandidateStream(b"unread")
    async with candidate_client(stream, headers) as client:
        with pytest.raises(RuntimeUnavailable, match="backend_(header|compressed_response)"):
            await client.get("/")
    assert stream.reads == 0
    assert stream.closed


@pytest.mark.parametrize("encoding", [b"gzip", b"br", b"deflate"])
async def test_compression_bomb_is_rejected_without_decompression(encoding: bytes) -> None:
    stream = CandidateStream(b"unread")
    async with candidate_client(stream, [(b"content-encoding", encoding)]) as client:
        with pytest.raises(RuntimeUnavailable, match="compressed_response"):
            await client.get("/")
    assert stream.reads == 0
    assert stream.closed


async def test_read_fault_closes_response() -> None:
    stream = CandidateStream(b"partial", error=httpx.ReadError("candidate fault"))
    async with candidate_client(stream) as client:
        with pytest.raises(httpx.ReadError):
            await client.get("/")
    assert stream.closed


def test_empty_infinite_stream_cannot_starve_deadline() -> None:
    # An outer process deadline keeps a broken cooperative timeout from hanging pytest.
    script = textwrap.dedent("""
        import asyncio
        import httpx
        from app.isolated_runtime import BoundedBackendTransport

        class Stream(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                while True:
                    yield b""
            async def aclose(self):
                self.closed = True

        async def main():
            stream = Stream()
            async def respond(request):
                return httpx.Response(200, stream=stream)
            transport = BoundedBackendTransport(httpx.MockTransport(respond))
            async with httpx.AsyncClient(transport=transport) as client:
                try:
                    async with asyncio.timeout(0.02):
                        await client.get("http://candidate/")
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("infinite stream accepted")
            assert stream.closed

        asyncio.run(main())
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr.decode()


async def test_regex_repeated_cancellation_waits_for_reap(monkeypatch: pytest.MonkeyPatch) -> None:
    reaping = asyncio.Event()
    release = asyncio.Event()
    process = AsyncMock()
    process.kill = Mock()
    process.returncode = None

    async def communicate(data: bytes) -> tuple[bytes, bytes]:
        await asyncio.Event().wait()
        return b"", b""

    async def wait() -> int:
        reaping.set()
        await release.wait()
        process.returncode = -1
        return -1

    process.communicate.side_effect = communicate
    process.wait.side_effect = wait
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(repro._regex_search("a", "a"))
    try:
        while not process.communicate.called:
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.wait_for(reaping.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done(), "cancellation abandoned the owned subprocess before reap"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert process.returncode == -1


@pytest.mark.parametrize("exit_kind", ["cancel", "timeout"])
async def test_regex_owns_process_when_spawn_is_interrupted(
    monkeypatch: pytest.MonkeyPatch, exit_kind: str
) -> None:
    spawned = asyncio.Event()
    release = asyncio.Event()
    process = AsyncMock()
    process.kill = Mock()
    process.returncode = None

    async def spawn(*args: object, **kwargs: object) -> object:
        spawned.set()
        await release.wait()
        return process

    async def run() -> None:
        async with asyncio.timeout(0.02 if exit_kind == "timeout" else 1):
            await repro._regex_search("a", "a")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(run())
    try:
        await spawned.wait()
        if exit_kind == "cancel":
            task.cancel()
        else:
            await asyncio.sleep(0.04)
        await asyncio.sleep(0)
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
        expected = asyncio.CancelledError if exit_kind == "cancel" else TimeoutError
        assert isinstance(result[0], expected)
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_managed_stop_survives_repeated_cancellation() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    process = AsyncMock()
    process.returncode = None

    async def wait() -> int:
        entered.set()
        await release.wait()
        process.returncode = 0
        return 0

    process.wait.side_effect = wait
    owned = ManagedProcess(process)
    task = asyncio.create_task(owned.stop())
    try:
        await entered.wait()
        task.cancel()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "stop returned before the candidate was reaped"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert process.returncode == 0


@pytest.mark.parametrize(
    "headers",
    [[(b"x", b"v")] * HEADER_COUNT_LIMIT, [(b"x", b"v" * (HEADER_LIMIT - 5))]],
    ids=["count-boundary", "byte-boundary"],
)
async def test_headers_at_limit_are_accepted(headers: list[tuple[bytes, bytes]]) -> None:
    stream = CandidateStream(b"ok")
    async with candidate_client(stream, headers) as client:
        assert (await client.get("/")).content == b"ok"
    assert stream.closed


@asynccontextmanager
async def candidate_server(payload: bytes) -> AsyncIterator[str]:
    clients: list[asyncio.Task[None]] = []

    async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        clients.append(task)
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(payload)
            await writer.drain()
            await reader.read()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async with await asyncio.start_server(respond, "127.0.0.1", 0) as server:
        try:
            yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        finally:
            for task in clients:
                task.cancel()
            await asyncio.gather(*clients, return_exceptions=True)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (b"HTTP/1.1 200 OK\r\nX-Huge: " + b"x" * 20000 + b"\r\n\r\n", RuntimeUnavailable),
        (b"HTTP/1.1 200 OK\r\n" + b"X: y\r\n" * 101 + b"\r\n", RuntimeUnavailable),
        (b"HTTP/1.1 200 OK\r\nX-Huge: " + b"x" * (1024 * 1024), httpx.RemoteProtocolError),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"fffffffffffffff\r\n" + b"x" * (REPORT_LIMIT + 8192),
            RuntimeUnavailable,
        ),
    ],
    ids=["giant-header", "many-headers", "unterminated-header", "giant-wire-chunk"],
)
async def test_hostile_wire_response_is_bounded(payload: bytes, error: type[Exception]) -> None:
    async with candidate_server(payload) as origin:
        transport = BoundedBackendTransport(httpx.AsyncHTTPTransport())
        async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
            async with asyncio.timeout(2):
                with pytest.raises(error):
                    await client.get("/")


@pytest.mark.parametrize("phase", ["headers", "body"])
async def test_transport_deadline_closes_stalled_connection(phase: str) -> None:
    payload = b"" if phase == "headers" else b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n"
    async with candidate_server(payload) as origin:
        transport = BoundedBackendTransport(httpx.AsyncHTTPTransport())
        async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
            started = asyncio.get_running_loop().time()
            with pytest.raises(TimeoutError):
                await client.get("/")
            assert asyncio.get_running_loop().time() - started < 4
            # The failed exchange must not leave the connection leased in the pool.
            assert isinstance(transport.inner, httpx.AsyncHTTPTransport)
            assert not transport.inner._pool.connections


@pytest.mark.skipif(sys.platform != "linux", reason="process-state check requires Linux procfs")
@pytest.mark.parametrize("exit_kind", ["timeout", "cancel", "repeated_cancel"])
async def test_deadline_kills_sigterm_ignoring_candidate_tree(exit_kind: str) -> None:
    child_script = (
        "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "print(os.getpid(),flush=True); time.sleep(60)"
    )
    script = textwrap.dedent(f"""
        import os, signal, subprocess, sys, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        child = subprocess.Popen([sys.executable, '-c', {child_script!r}], stdout=subprocess.PIPE)
        print(str(os.getpid()) + ',' + child.stdout.readline().decode().strip(), flush=True)
        time.sleep(60)
    """)
    owned = await ManagedProcess.start(sys.executable, "-I", "-c", script)
    try:
        async with asyncio.timeout(3):
            while b"\n" not in owned.stdout:
                await asyncio.sleep(0.005)
        pids = [int(value) for value in owned.stdout.decode().strip().split(",")]
        started = asyncio.get_running_loop().time()
        task = asyncio.create_task(owned.wait(0.02 if exit_kind == "timeout" else 10))
        if exit_kind != "timeout":
            await asyncio.sleep(0)
            task.cancel()
            if exit_kind == "repeated_cancel":
                async with asyncio.timeout(1):
                    while owned.liveness_fd is not None:
                        await asyncio.sleep(0)
                task.cancel()
        expected = TimeoutError if exit_kind == "timeout" else asyncio.CancelledError
        with pytest.raises(expected):
            await asyncio.wait_for(task, 4)
        assert asyncio.get_running_loop().time() - started < 3
        assert owned.process.returncode is not None
        assert all(pump.done() for pump in owned.pumps)
        for pid in pids:
            stat = Path(f"/proc/{pid}/stat")
            try:
                state = stat.read_text().split(")", 1)[1].split()[0]
            except FileNotFoundError:
                continue
            assert state == "Z", f"candidate process {pid} is still running"
    finally:
        await owned.stop()


async def test_managed_spawn_cancellation_retains_and_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX supervisor startup regression")
    spawn = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    release = asyncio.Event()
    processes: list[asyncio.subprocess.Process] = []

    async def delayed_spawn(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        process = await spawn(*args, **kwargs)
        processes.append(process)
        spawned.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
    task = asyncio.create_task(
        ManagedProcess.start(sys.executable, "-I", "-c", "import time; time.sleep(60)")
    )
    try:
        await asyncio.wait_for(spawned.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 4)
        assert processes and all(process.returncode is not None for process in processes)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        for process in processes:
            if process.returncode is None:
                process.kill()
            await process.wait()


async def test_infinite_byte_stream_stops_at_first_overflow() -> None:
    class InfiniteStream(CandidateStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            while True:
                self.reads += 1
                yield b"x" * 8192

    stream = InfiniteStream()
    async with candidate_client(stream) as client:
        async with asyncio.timeout(1):
            with pytest.raises(RuntimeUnavailable, match="backend_response_limit"):
                await client.get("/")
    assert stream.reads == REPORT_LIMIT // 8192 + 1
    assert stream.closed


async def test_windows_start_cancellation_keeps_stop_request_until_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned = asyncio.Event()
    release = asyncio.Event()
    stop_paths: list[Path] = []
    process = AsyncMock()
    process.returncode = None
    for name in ("stdout", "stderr"):
        reader = asyncio.StreamReader()
        reader.feed_eof()
        setattr(process, name, reader)

    async def spawn(*args: str, **kwargs: object) -> Any:
        stop_paths.append(Path(args[3]))
        spawned.set()
        await release.wait()
        return process

    async def wait() -> int:
        assert stop_paths[0].exists(), "shutdown request was revoked before supervisor exit"
        process.returncode = 0
        return 0

    process.wait.side_effect = wait
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        ManagedProcess._start_windows("candidate", cwd=None, env=None, interactive=False)
    )
    try:
        await spawned.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert stop_paths[0].exists()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        process.wait.assert_awaited_once()
        assert not stop_paths[0].parent.exists()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
