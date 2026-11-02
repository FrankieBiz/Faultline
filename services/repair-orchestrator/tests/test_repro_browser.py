"""Exercise the trusted browser driver's non-HTTP egress policy."""

import asyncio
import json
import shutil
import socket
from pathlib import Path

from app import project_runtime


async def test_project_browser_webrtc_cannot_send_stun_udp(tmp_path: Path) -> None:
    driver = Path(project_runtime.__file__).with_name("repro_browser.mjs")
    repository = driver.parents[3]
    playwright = repository / "tools/browser-runner/node_modules/playwright/index.mjs"
    node = shutil.which("node")
    assert node is not None and playwright.is_file(), "Build the browser runner first"
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
            try:
                async with asyncio.timeout(10):
                    assert json.loads(await process.stdout.readline()) == {"ready": True}
                    process.stdin.write(b'{"action":"navigate","path":"/","timeout_ms":3000}\n')
                    await process.stdin.drain()
                    assert json.loads(await process.stdout.readline()) == {"result": None}
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
                    response = json.loads(await process.stdout.readline())
                    assert response["result"]["value"] in {"rtc-started", "rtc-disabled"}
            finally:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await process.wait()
