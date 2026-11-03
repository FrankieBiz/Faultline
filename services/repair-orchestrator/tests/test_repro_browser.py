"""Exercise the trusted browser driver's non-HTTP egress policy."""

import asyncio
import json
import os
import shutil
import socket
from pathlib import Path

import pytest

from app import project_runtime


@pytest.mark.parametrize("channel_available", [True, False])
async def test_browser_preflight_falls_back_with_sandbox_and_webrtc_policy(
    tmp_path: Path, channel_available: bool
) -> None:
    driver = Path(project_runtime.__file__).with_name("repro_browser.mjs")
    playwright = tmp_path / "playwright.mjs"
    playwright.write_text(
        "import assert from 'node:assert/strict';\n"
        "let attempts = 0;\n"
        "export const chromium = { executablePath() { return '/trusted/chromium'; },\n"
        "async launch(options) {\n"
        "  attempts++;\n"
        "  assert.equal(options.headless, true);\n"
        "  assert.equal(options.chromiumSandbox, true);\n"
        "  assert.deepEqual(options.args, ['--disable-webrtc',\n"
        "    '--webrtc-ip-handling-policy=disable_non_proxied_udp',\n"
        "    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',\n"
        "    '--disable-features=WebRtcHideLocalIpsWithMdns,WebRTC',\n"
        "    '--js-flags=--max-old-space-size=128']);\n"
        "  assert.equal(options.channel, attempts === 1 ? 'chromium' : undefined);\n"
        "  assert.equal(options.executablePath,\n"
        "    attempts === 1 ? undefined : '/trusted/chromium');\n"
        f"  if (attempts === 1 && {json.dumps(not channel_available)}) {{\n"
        "    throw new Error('Chromium channel unavailable');\n"
        "  }\n"
        f"  assert.equal(attempts, {1 if channel_available else 2});\n"
        "  return { async close() {} };\n"
        "} };\n"
    )
    node = shutil.which("node")
    assert node is not None, "Install Node first"
    process = await asyncio.create_subprocess_exec(
        node,
        str(driver),
        str(playwright),
        "--preflight",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    assert json.loads(stdout) == {"ready": True}


@pytest.mark.parametrize("fallback", [False, True])
async def test_project_browser_webrtc_cannot_send_stun_udp(tmp_path: Path, fallback: bool) -> None:
    driver = Path(project_runtime.__file__).with_name("repro_browser.mjs")
    repository = driver.parents[3]
    playwright = repository / "tools/browser-runner/node_modules/playwright/index.mjs"
    if fallback:
        wrapper = tmp_path / "fallback.mjs"
        wrapper.write_text(
            "import { chromium as real } from " + json.dumps(playwright.as_uri()) + ";\n"
            "export const chromium = { executablePath: () => real.executablePath(),\n"
            "launch(options) { if (options.channel) throw new Error('force fallback');\n"
            "return real.launch(options); } };\n"
        )
        playwright = wrapper
    node = shutil.which("node")
    assert node is not None and playwright.is_file(), "Build the browser runner first"
    preflight = await asyncio.create_subprocess_exec(
        node,
        str(driver),
        str(playwright),
        "--preflight",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(preflight.communicate(), timeout=10)
    except TimeoutError:
        preflight.kill()
        stdout, stderr = await preflight.communicate()
    if preflight.returncode != 0 or stdout.strip() != b'{"ready":true}':
        if os.environ.get("FAULTLINE_REQUIRE_ISOLATED_TESTS") == "1":
            pytest.fail(
                "Required sandboxed browser is unavailable: " + stderr.decode(errors="replace")
            )
        pytest.skip("sandboxed_browser_unavailable")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind(("127.0.0.1", 0))
        udp.setblocking(False)
        page = f"""<!doctype html><body><script>
            document.body.textContent = 'probe-started';
            if (typeof RTCPeerConnection === 'undefined') {{
                document.body.textContent = 'rtc-disabled';
            }} else {{
            window.pc = new RTCPeerConnection({{
                iceServers: [{{urls: 'stun:127.0.0.1:{udp.getsockname()[1]}'}}]
            }});
            pc.createDataChannel('regression');
            pc.createOffer().then(offer => pc.setLocalDescription(offer))
                .then(() => document.body.textContent = 'rtc-started');
            }}
        </script>""".encode()

        async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                    + f"Content-Length: {len(page)}\r\nConnection: close\r\n\r\n".encode()
                    + page
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            process = await asyncio.create_subprocess_exec(
                node,
                str(driver),
                str(playwright),
                f"http://127.0.0.1:{port}",
                str(tmp_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert process.stdin is not None and process.stdout is not None

            async def read_line() -> bytes:
                assert process.stdout is not None and process.stderr is not None
                line = await process.stdout.readline()
                if not line:
                    stderr = await process.stderr.read()
                    pytest.fail(
                        "Browser driver exited before a response: "
                        + stderr.decode(errors="replace")
                    )
                return line

            try:
                async with asyncio.timeout(10):
                    assert json.loads(await read_line()) == {"ready": True}
                    process.stdin.write(b'{"action":"navigate","path":"/","timeout_ms":3000}\n')
                    await process.stdin.drain()
                    assert json.loads(await read_line()) == {"result": None}
                    try:
                        packet = await asyncio.wait_for(
                            asyncio.get_running_loop().sock_recvfrom(udp, 2048), timeout=1.5
                        )
                    except TimeoutError:
                        pass
                    else:
                        raise AssertionError(
                            f"WebRTC leaked a STUN datagram: {len(packet[0])} bytes"
                        )
                    # Confirm the page actually ran its WebRTC probe; a failed
                    # navigation or disabled JavaScript must not produce a pass.
                    process.stdin.write(
                        b'{"action":"capture","kind":"text","selector":"body","timeout_ms":3000}\n'
                    )
                    await process.stdin.drain()
                    response = json.loads(await read_line())
                    assert response["result"]["value"] in {"rtc-started", "rtc-disabled"}
            finally:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await process.wait()


async def test_browser_aborts_when_isolated_launches_are_unavailable(tmp_path: Path) -> None:
    driver = Path(project_runtime.__file__).with_name("repro_browser.mjs")
    playwright = tmp_path / "unavailable.mjs"
    playwright.write_text(
        "export const chromium = { executablePath: () => '/missing/chromium',\n"
        "async launch() { throw new Error('sandbox unavailable'); } };\n"
    )
    node = shutil.which("node")
    assert node is not None
    process = await asyncio.create_subprocess_exec(
        node,
        str(driver),
        str(playwright),
        "--preflight",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode != 0
    assert not stdout
    assert b"sandboxed_browser_isolation_unavailable" in stderr


@pytest.mark.parametrize("kind", ["text", "value"])
async def test_browser_rejects_oversized_dom_before_protocol_serialization(
    tmp_path: Path, kind: str
) -> None:
    """Run the production capture callback; forbid the unbounded Playwright APIs."""
    driver = Path(project_runtime.__file__).with_name("repro_browser.mjs")
    playwright = tmp_path / "bounded.mjs"
    playwright.write_text(
        "const element = { innerText: 'x'.repeat(200000), value: 'x'.repeat(200000) };\n"
        "const page = { on() {}, locator() { return {\n"
        "  async innerText() { return element.innerText; },\n"
        "  async inputValue() { return element.value; },\n"
        "  async evaluate(fn, arg) { return fn(element, arg); }\n"
        "}; } };\n"
        "const context = { async route() {}, async routeWebSocket() {},\n"
        "  tracing: { async start() {} }, async newPage() { return page; } };\n"
        "export const chromium = { async launch() { return {\n"
        "  async close() {}, async newContext() { return context; } }; } };\n"
    )
    process = await asyncio.create_subprocess_exec(
        "node",
        str(driver),
        str(playwright),
        "http://127.0.0.1:1",
        str(tmp_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(
        json.dumps(
            {"action": "capture", "kind": kind, "selector": "body", "timeout_ms": 100}
        ).encode()
        + b"\n"
    )
    assert process.returncode == 0, stderr.decode()
    ready, result = stdout.splitlines()
    assert json.loads(ready) == {"ready": True}
    assert json.loads(result) == {"error": "browser_step_failed"}


@pytest.mark.parametrize("action", ["capture", "finish"])
async def test_browser_bounds_screenshot_pixels_and_trace_export(
    tmp_path: Path, action: str
) -> None:
    driver = Path(project_runtime.__file__).with_name("repro_browser.mjs")
    playwright = tmp_path / "artifacts.mjs"
    playwright.write_text(
        "import assert from 'node:assert/strict';\n"
        "import { writeFileSync, truncateSync } from 'node:fs';\n"
        "const page = { on() {}, async screenshot(options) {\n"
        "  writeFileSync(process.argv[4] + '/options.json', JSON.stringify(options));\n"
        "  assert.deepEqual(options.clip, {x:0,y:0,width:1280,height:720});\n"
        "  assert.equal(options.fullPage, false); assert.equal(options.scale, 'css');\n"
        "  if (options.path) writeFileSync(options.path, 'png');\n"
        "  return Buffer.alloc(600 * 1024);\n"
        "} };\n"
        "const context = { async route() {}, async routeWebSocket() {},\n"
        "  tracing: { async start() {}, async stop({path}) {\n"
        "    writeFileSync(path, ''); truncateSync(path, 26 * 1024 * 1024);\n"
        "  } }, async newPage() { return page; } };\n"
        "export const chromium = { async launch() { return {\n"
        "  async close() {}, async newContext() { return context; } }; } };\n"
    )
    process = await asyncio.create_subprocess_exec(
        "node",
        str(driver),
        str(playwright),
        "http://127.0.0.1:1",
        str(tmp_path),
        "--stream-artifacts",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(
        json.dumps({"action": action, "kind": "screenshot", "timeout_ms": 100}).encode() + b"\n"
    )
    assert process.returncode == 0, stderr.decode()
    options = json.loads((tmp_path / "options.json").read_text())
    assert options["clip"] == {"x": 0, "y": 0, "width": 1280, "height": 720}
    assert options["fullPage"] is False
    assert options["scale"] == "css"
    messages = [json.loads(line) for line in stdout.splitlines()]
    assert messages[-1] == {"error": "browser_step_failed"}
    assert not any(message.get("artifact") == "trace.zip" for message in messages)


async def test_browser_rejects_command_growth_while_reading(tmp_path: Path) -> None:
    driver = Path(project_runtime.__file__).with_name("repro_browser.mjs")
    playwright = tmp_path / "input.mjs"
    playwright.write_text(
        "const context = { async route() {}, async routeWebSocket() {},\n"
        "tracing: { async start() {} }, async newPage() { return {on() {}}; } };\n"
        "export const chromium = { async launch() { return {\n"
        "async newContext() { return context; }, async close() {} }; } };\n"
    )
    process = await asyncio.create_subprocess_exec(
        "node",
        str(driver),
        str(playwright),
        "http://127.0.0.1:1",
        str(tmp_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # No newline: readline would continue accumulating without ever parsing.
    stdout, stderr = await process.communicate(b"x" * 70000)
    assert process.returncode != 0
    assert stdout.strip() == b'{"ready":true}'
    assert b"command_limit" in stderr
