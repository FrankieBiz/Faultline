"""Audit characterization probe; exit zero does not mean the observed behavior is safe.

Run from the repository root using the locked orchestrator environment.
Uses synthetic inputs and temporary resources; does not call a model provider.
"""

# Repository imports require the orchestrator source path below.
# ruff: noqa: E402

import asyncio
import json
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/repair-orchestrator"))
from app.isolated_runtime import IsolatedRuntime, ManagedProcess, process_parents


async def probe(fallback):
    runtime = IsolatedRuntime()
    with tempfile.TemporaryDirectory(prefix="faultline-audit-browser-") as directory:
        directory = Path(directory)
        playwright = ROOT / "tools/browser-runner/node_modules/playwright/index.mjs"
        if fallback:
            wrapper = directory / "fallback.mjs"
            wrapper.write_text(
                "import { chromium as real } from "
                + json.dumps(playwright.as_uri())
                + ";\nexport const chromium = { launch(options) {\n"
                + 'if(options.channel) throw new Error("force fallback");\n'
                + "return real.launch(options); } };\n"
            )
            playwright = wrapper
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.bind(("127.0.0.1", 0))
            udp.setblocking(False)
            page = f"""<!doctype html><body><script>
            document.body.textContent='probe-started';
            if(typeof RTCPeerConnection==='undefined') document.body.textContent='rtc-disabled';
            else {{
              window.pc=new RTCPeerConnection({{iceServers:[{{
                urls:'stun:127.0.0.1:{udp.getsockname()[1]}'
              }}]}});
              pc.createDataChannel('audit');
              pc.createOffer().then(o=>pc.setLocalDescription(o))
                .then(()=>document.body.textContent='rtc-started');
            }}
            </script>""".encode()

            async def serve(reader, writer):
                try:
                    await reader.readuntil(b"\r\n\r\n")
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                        + str(len(page)).encode()
                        + b"\r\nConnection: close\r\n\r\n"
                        + page
                    )
                    await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()

            server = await asyncio.start_server(serve, "127.0.0.1", 0)
            async with server:
                origin = "http://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
                owned = await ManagedProcess.start(
                    runtime.node,
                    str(ROOT / "services/repair-orchestrator/app/repro_browser.mjs"),
                    str(playwright),
                    origin,
                    str(directory),
                    env=runtime._trusted_environment(),
                    interactive=True,
                )
                try:
                    async with asyncio.timeout(12):
                        process = owned.process
                        assert json.loads(await process.stdout.readline()) == {"ready": True}
                        process.stdin.write(b'{"action":"navigate","path":"/","timeout_ms":3000}\n')
                        await process.stdin.drain()
                        assert json.loads(await process.stdout.readline()) == {"result": None}
                        try:
                            packet = await asyncio.wait_for(
                                asyncio.get_running_loop().sock_recvfrom(udp, 2048), 1.5
                            )
                            leaked = len(packet[0])
                        except TimeoutError:
                            leaked = 0
                        process.stdin.write(
                            b'{"action":"capture","kind":"text","selector":"body","timeout_ms":3000}\n'
                        )
                        await process.stdin.drain()
                        result = json.loads(await process.stdout.readline())
                        children = [
                            pid
                            for pid, parent in process_parents().items()
                            if parent == process.pid
                        ]
                        assert len(children) == 1, "Expected the supervised Node driver"
                        driver_cgroup = Path(f"/proc/{children[0]}/cgroup").read_text()
                        return {
                            "forced_fallback": fallback,
                            "stun_bytes_received": leaked,
                            "page_result": result,
                            "driver_in_faultline_candidate_scope": "faultline-" in driver_cgroup,
                            "driver_shares_controller_cgroup": driver_cgroup
                            == Path("/proc/self/cgroup").read_text(),
                        }
                finally:
                    await owned.stop()


async def main():
    print(json.dumps([await probe(False), await probe(True)], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
