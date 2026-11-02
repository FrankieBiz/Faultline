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
        "export const chromium = { async launch(options) {\n"
        "  attempts++;\n"
        "  assert.equal(options.headless, true);\n"
        "  assert.equal(options.chromiumSandbox, true);\n"
        "  assert.deepEqual(options.args, ['--disable-webrtc',\n"
        "    '--webrtc-ip-handling-policy=disable_non_proxied_udp']);\n"
        "  assert.equal(options.channel, attempts === 1 ? 'chromium' : undefined);\n"
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


async def test_project_browser_webrtc_cannot_send_stun_udp(tmp_path: Path) -> None:
    driver = Path(project_runtime.__file__).with_name("repro_browser.mjs")
    repository = driver.parents[3]
    playwright = repository / "tools/browser-runner/node_modules/playwright/index.mjs"
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
