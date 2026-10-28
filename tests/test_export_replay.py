"""A shareable replay must contain only verified, escaped, recorded evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import shutil
import struct
import subprocess
import sys
import threading
import zipfile
import zlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
JOB_ID = "6f1c2a7e-3b4d-4e5f-8a9b-0c1d2e3f4a5b"
TARGET = "apps/buggyshop-backend/app/routes/checkout.py"
HOSTILE_SCRIPT = "<script>alert(1)</script>"
HOSTILE_ATTR = '"><img src=x onerror=alert(1)>'
CHECKOUT = [
    "checkout.status_201",
    "checkout.order_id_is_uuid",
    "checkout.line_items_match_cart",
    "checkout.subtotal_matches_catalog",
    "checkout.no_coupon_discount_is_zero",
    "checkout.total_matches_subtotal",
    "checkout.exactly_one_stored_order",
    "checkout.readback_matches_response",
]
REGRESSION = [
    "regression.missing_coupon",
    "regression.null_coupon",
    "regression.empty_coupon",
    "regression.whitespace_coupon",
    "regression.tenoff",
    "regression.fifteen",
    "regression.normalized_coupon",
    "regression.mixed_cart",
    "regression.mixed_cart_coupon",
    "regression.quantity_ten",
    "regression.empty_cart",
]
EXTENSION = {
    "screenshot": "png",
    "trace": "zip",
    "requests": "json",
    "logs": "log",
    "report": "json",
    "proposal": "json",
    "diff": "diff",
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "export_replay", ROOT / "scripts" / "export_replay.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


replay = _load()


# ---------------------------------------------------------------------------
# Recorded fixture


def png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Encode a real, decodable solid-color PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    rows = (b"\x00" + bytes(rgb) * width) * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def trace_zip(label: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("trace.trace"), json.dumps({"run": label}))
    return buffer.getvalue()


def sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def uid(n: int) -> str:
    return f"{n:08x}-5e3d-4c1a-9b2f-{n:012x}"


T0 = datetime(2026, 10, 27, 14, 2, 11, 250000, tzinfo=UTC)


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


BAD_DIFF = f"""--- a/{TARGET}
+++ b/{TARGET}
@@ -41,7 +41,7 @@ def create_checkout(request: CheckoutRequest, namespace: str) -> Order:
     subtotal = sum(line.total_cents for line in lines)
-    discount = subtotal * PERCENT[coupon] // 100
+    discount = 0
     total = subtotal - discount
     order = store.save(namespace, lines, subtotal, discount, total)
     return order
"""
GOOD_DIFF = f"""--- a/{TARGET}
+++ b/{TARGET}
@@ -38,10 +38,11 @@ def create_checkout(request: CheckoutRequest, namespace: str) -> Order:
     lines = price_lines(request.items)
     subtotal = sum(line.total_cents for line in lines)
-    coupon = request.coupon.strip().upper()
-    discount = subtotal * PERCENT[coupon] // 100
+    coupon = (request.coupon or "").strip().upper()
+    if coupon and coupon not in PERCENT:
+        raise HTTPException(status_code=400, detail="unknown_coupon")
+    discount = subtotal * PERCENT.get(coupon, 0) // 100
     total = subtotal - discount
     order = store.save(namespace, lines, subtotal, discount, total)
     return order
"""


def sample_job(
    *,
    state: str = "succeeded",
    outcome: str | None = "verified",
    provider: str | None = "deterministic",
    model: str = "deterministic-checkout-v1",
    runtime_kind: str | None = "isolated-browser",
    hostile: bool = False,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """A two-attempt job shaped like the controller's GET jobs/<id> response."""
    script = f" {HOSTILE_SCRIPT}" if hostile else ""
    attr = f" {HOSTILE_ATTR}" if hostile else ""
    repaired = outcome == "verified"
    artifacts: list[dict[str, Any]] = []
    blobs: dict[str, bytes] = {}

    def register(
        role: str,
        content_type: str,
        content: bytes,
        when: float,
        execution_id: str | None = None,
        attempt_id: str | None = None,
    ) -> str:
        artifact_id = uid(1000 + len(artifacts))
        artifacts.append(
            {
                "schema_version": "1.0",
                "id": artifact_id,
                "job_id": JOB_ID,
                "execution_id": execution_id,
                "attempt_id": attempt_id,
                "role": role,
                "content_type": content_type,
                "size_bytes": len(content),
                "sha256": sha(content),
                "created_at": at(when),
            }
        )
        blobs[artifact_id] = content
        return artifact_id

    def assertion(name: str, passed: bool, expected: str, observed: str) -> dict[str, Any]:
        return {
            "id": name,
            "passed": passed,
            "expected": expected,
            "observed": observed,
            "duration_ms": 41.5,
        }

    def execution(
        phase: str,
        number: int,
        verdict: str,
        assertions: list[dict[str, Any]],
        start: float,
        end: float,
        attempt_id: str | None,
        rgb: tuple[int, int, int],
    ) -> dict[str, Any]:
        execution_id = uid(100 + number)
        observations = []
        if verdict == "failed" and phase == "baseline":
            observations = [
                {
                    "id": "obs-http",
                    "kind": "http_error",
                    "source": "browser",
                    "message": f"POST /api/checkout returned HTTP 500{attr}",
                    "data": {"status": 500},
                    "timestamp": at(start + 2.1),
                },
                {
                    "id": "obs-server",
                    "kind": "server_exception",
                    "source": TARGET,
                    "message": "AttributeError: 'NoneType' object has no attribute 'strip'",
                    "data": {},
                    "timestamp": at(start + 2.2),
                },
            ]
        report = {
            "execution_id": execution_id,
            "case_id": f"case-{number}",
            "scenario_id": "scripted_checkout_repair",
            "verdict": verdict,
            "duration_ms": (end - start) * 1000 - 87.4,
            "observations": observations,
            "assertions": assertions,
            "raw_logs": "Traceback (most recent call last): ...",
        }
        ids = [
            register("screenshot", "image/png", png(640, 400, rgb), end, execution_id),
            register("trace", "application/zip", trace_zip(phase), end, execution_id),
            register("requests", "application/json", b'[{"method":"POST"}]', end, execution_id),
            register("logs", "text/plain", b"No backend exceptions observed.\n", end, execution_id),
            register("report", "application/json", json.dumps(report).encode(), end, execution_id),
        ]
        record: dict[str, Any] = {
            "schema_version": "1.0",
            "job_id": JOB_ID,
            "phase": phase,
            "attempt_id": attempt_id,
            "app_generation_id": f"gen-{number:04d}",
            "candidate_snapshot_sha256": sha(f"snapshot-{number}"),
            "runtime_kind": runtime_kind,
            "artifact_ids": ids,
            "started_at": at(start),
            "finished_at": at(end),
            "report": report,
        }
        if runtime_kind is None:
            del record["runtime_kind"]
        return record

    baseline = execution(
        "baseline",
        1,
        "failed",
        [
            assertion("checkout.status_201", False, "201", f"500{script}"),
            assertion(
                "checkout.confirmation_shown", False, "order confirmation", "HTTP 500 error banner"
            ),
        ],
        0.4,
        4.8,
        None,
        (58, 30, 32),
    )

    def checks(failed: set[str]) -> list[dict[str, Any]]:
        return [
            assertion(name, name not in failed, "matches contract", "as expected")
            if name not in failed
            else assertion(name, False, "discount 10% of subtotal", f"discount 0{script}")
            for name in CHECKOUT + REGRESSION
        ]

    attempts = []
    executions = [baseline]
    for number, diff in ((1, BAD_DIFF), (2, GOOD_DIFF)):
        attempt_id = uid(200 + number)
        passed = repaired and number == 2
        start = 6.1 if number == 1 else 13.6
        verification = execution(
            "verification",
            number + 1,
            "passed" if passed else "failed",
            checks(set() if passed else {"regression.tenoff", "regression.fifteen"}),
            start,
            start + 6.2,
            attempt_id,
            (24, 52, 38) if passed else (58, 30, 32),
        )
        executions.append(verification)
        proposal = {
            "decision": "patch",
            "target_file": TARGET,
            "base_sha256": sha("seed"),
            "unified_diff": diff,
            "explanation": f"Treat an absent coupon as no discount.{attr}",
        }
        register(
            "proposal",
            "application/json",
            json.dumps(proposal).encode(),
            start - 1,
            None,
            attempt_id,
        )
        register("diff", "text/plain", diff.encode(), start - 1, None, attempt_id)
        result: dict[str, Any] = {
            "generation_ms": 4,
            "is_valid": True,
            "target_file": TARGET,
            "syntax_valid": True,
            "error_message": None,
            "ast_safe": True,
            "base_sha256": sha("seed"),
            "candidate_sha256": sha(f"candidate-{number}"),
            "target_sha256": sha(f"target-{number}"),
            "app_generation_id": f"gen-{number + 1:04d}",
            "verification_execution_id": verification["report"]["execution_id"],
        }
        if provider is not None:
            result = {"provider": provider, "model": model, **result}
        if number == 2:
            result = {
                "prior_feedback": {
                    "gate": "verification_failed",
                    "policy_error": None,
                    "failed_check_count": 2,
                    "failed_checks": ["regression.tenoff", f"regression.fifteen{script}"],
                    "included_rejected_diff": True,
                },
                **result,
            }
        attempts.append(
            {
                "id": attempt_id,
                "job_id": JOB_ID,
                "attempt_number": number,
                "prompt_tokens": None if provider == "deterministic" else 1840,
                "completion_tokens": None if provider == "deterministic" else 312,
                "raw_patch": json.dumps(proposal),
                "parsed_diff": diff + (f"+# {HOSTILE_SCRIPT}\n" if hostile else ""),
                "validation_result": result,
                "outcome": "verified" if passed else "verification_failed",
            }
        )

    terminal = state in {"succeeded", "failed", "cancelled", "interrupted"}
    timeline = [
        ("preparing", "queued", "Job accepted.", 0.0),
        ("preparing", "preparing", "Entered preparing.", 0.1),
        ("baseline", "baseline", "Entered baseline.", 0.4),
        ("diagnosing", "diagnosing", f"Entered diagnosing.{attr}", 4.9),
        ("patch_validation", "patch_validation", "Entered patch_validation.", 4.95),
        ("activating", "activating", "Entered activating.", 5.0),
        ("verification", "verification", "Entered verification.", 6.1),
        ("diagnosing", "diagnosing", "Entered diagnosing.", 12.4),
        ("patch_validation", "patch_validation", "Entered patch_validation.", 12.45),
        ("activating", "activating", "Entered activating.", 12.5),
        ("verification", "verification", "Entered verification.", 13.6),
    ]
    if terminal:
        timeline += [
            ("cleanup", "cleanup", "Entered cleanup.", 19.9),
            ("completed", str(outcome), f"Job completed: {outcome}.", 20.6),
        ]
    events = [
        {
            "schema_version": "1.0",
            "job_id": JOB_ID,
            "sequence": index + 1,
            "timestamp": at(when),
            "stage": stage,
            "message_code": code,
            "message": message,
        }
        for index, (stage, code, message, when) in enumerate(timeline)
    ]
    job = {
        "id": JOB_ID,
        "scenario_id": "scripted_checkout_repair",
        "state": state,
        "stage": "completed" if terminal else "verification",
        "outcome": outcome,
        "cleanup_status": "succeeded" if terminal else "not_started",
        "created_at": at(0),
        "updated_at": at(20.6 if terminal else 13.6),
        "error_details": {"note": HOSTILE_SCRIPT} if hostile else None,
        "schema_version": "1.0",
        "idempotency_key": "00000000-0000-4000-8000-000000000001",
        "request_fingerprint": sha("request"),
        "requested_mode": "repair",
        "effective_mode": "repair",
        "repair_block_reason": None,
        "cancel_requested": False,
        "deadline_at": at(190),
        "seed_commit": "4d2c9f0b7a1e3c5d8f6a2b4c6d8e0f1a3b5c7d9e",
        "seed_source_hash": sha("seed"),
        "fixture_version": "1.0",
        "scenario_version": "1.0",
        "baseline_execution_id": baseline["report"]["execution_id"],
    }
    detail = {
        "job": job,
        "baseline": baseline,
        "attempts": attempts,
        "executions": executions,
        "artifacts": artifacts,
        "events": events,
    }
    return detail, blobs


def detection_only(detail: dict[str, Any], blobs: dict[str, bytes]) -> None:
    """Reshape a sample into a detect-mode job with no repair attempt."""
    baseline_id = detail["baseline"]["report"]["execution_id"]
    detail["job"].update(outcome="detected", requested_mode="detect", effective_mode="detect")
    detail["attempts"] = []
    detail["executions"] = [detail["baseline"]]
    detail["artifacts"] = [a for a in detail["artifacts"] if a["execution_id"] == baseline_id]
    for artifact_id in set(blobs) - {a["id"] for a in detail["artifacts"]}:
        del blobs[artifact_id]


# ---------------------------------------------------------------------------
# Fake Inspector proxy


class Proxy:
    """Routes served under /api/faultline/, with a log of requested paths."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.routes: dict[str, tuple[int, str, bytes]] = {}
        self.requests: list[str] = []

    def serve(self, detail: dict[str, Any], blobs: dict[str, bytes]) -> None:
        self.routes[f"jobs/{detail['job']['id']}"] = (
            200,
            "application/json",
            json.dumps(detail).encode(),
        )
        self.routes["jobs?limit=1"] = (
            200,
            "application/json",
            json.dumps({"jobs": [detail["job"]]}).encode(),
        )
        types = {a["id"]: a["content_type"] for a in detail["artifacts"]}
        for artifact_id, content in blobs.items():
            self.routes[f"artifacts/{artifact_id}"] = (200, types[artifact_id], content)


@pytest.fixture
def proxy() -> Iterator[Proxy]:
    holder: list[Proxy] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state = holder[0]
            path = self.path.removeprefix("/api/faultline/")
            state.requests.append(path)
            missing = (404, "application/json", b'{"error":{"code":"not_found"}}')
            status, content_type, body = state.routes.get(path, missing)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    holder.append(Proxy(f"http://127.0.0.1:{server.server_port}/api/faultline"))
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        yield holder[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


Run = Callable[..., tuple[int, str, str]]


@pytest.fixture
def run(proxy: Proxy, capsys: pytest.CaptureFixture[str]) -> Run:
    def invoke(*args: str) -> tuple[int, str, str]:
        code = replay.main(["--api", proxy.base, *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return invoke


def export_sample(
    tmp_path: Path, proxy: Proxy, run: Run, *extra: str, **options: Any
) -> tuple[Path, str, dict[str, Any], dict[str, bytes]]:
    detail, blobs = sample_job(**options)
    proxy.serve(detail, blobs)
    out = tmp_path / "replay"
    code, stdout, stderr = run("--job", JOB_ID, "--out", str(out), *extra)
    assert code == 0, stderr
    return out, (out / "index.html").read_text(encoding="utf-8"), detail, blobs


class Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def parse(page: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = Tags()
    parser.feed(page)
    return parser.tags


def files_in(directory: Path) -> set[str]:
    return {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Tests


def test_export_writes_every_file_with_a_valid_sha256sums(
    tmp_path: Path, proxy: Proxy, run: Run
) -> None:
    out, page, detail, blobs = export_sample(tmp_path, proxy, run)

    expected = {"index.html", "job.json", "SHA256SUMS"} | {
        f"artifacts/{a['id']}.{EXTENSION[a['role']]}" for a in detail["artifacts"]
    }
    assert files_in(out) == expected
    assert json.loads((out / "job.json").read_text(encoding="utf-8")) == detail
    for artifact in detail["artifacts"]:
        path = out / f"artifacts/{artifact['id']}.{EXTENSION[artifact['role']]}"
        assert path.read_bytes() == blobs[artifact["id"]]

    lines = (out / "SHA256SUMS").read_text().splitlines()
    assert all(re.fullmatch(r"[0-9a-f]{64}  [\w./-]+", line) for line in lines)
    listed = {line[66:]: line[:64] for line in lines}
    assert set(listed) == expected - {"SHA256SUMS"}
    for name, digest in listed.items():
        assert sha((out / name).read_bytes()) == digest
    if shutil.which("sha256sum"):
        check = subprocess.run(
            ["sha256sum", "--check", "--strict", "SHA256SUMS"],
            cwd=out,
            capture_output=True,
            text=True,
            check=False,
        )
        assert check.returncode == 0, check.stdout + check.stderr

    assert "Verified repair" in page
    assert 'data-verified="true"' in page
    assert f"{len(CHECKOUT + REGRESSION)} of {len(CHECKOUT + REGRESSION)} assertions passed" in page
    assert "Fed back from the previous attempt" in page
    assert "Rejected by <code>verification_failed</code>" in page
    assert "2 failing checks reported" in page
    assert "A verified candidate is not a production deployment" in page
    assert not list(tmp_path.glob(".replay.*")), "staging directories must not remain"


@pytest.mark.parametrize("tamper", ["sha256", "size"])
def test_artifact_mismatch_aborts_before_writing(
    tmp_path: Path, proxy: Proxy, run: Run, tamper: str
) -> None:
    detail, blobs = sample_job()
    screenshot = next(a for a in detail["artifacts"] if a["role"] == "screenshot")
    original = blobs[screenshot["id"]]
    if tamper == "sha256":
        blobs[screenshot["id"]] = original[:-1] + bytes([original[-1] ^ 1])
    else:
        blobs[screenshot["id"]] = original + b"\x00"
    proxy.serve(detail, blobs)
    out = tmp_path / "replay"

    code, _, stderr = run("--job", JOB_ID, "--out", str(out))

    assert code == 1
    assert "Refusing to export unverified evidence" in stderr
    assert not out.exists()
    assert not (out / "index.html").exists()
    assert list(tmp_path.iterdir()) == []


def test_non_terminal_job_is_refused_without_fetching_evidence(
    tmp_path: Path, proxy: Proxy, run: Run
) -> None:
    detail, blobs = sample_job(state="running", outcome=None)
    proxy.serve(detail, blobs)
    out = tmp_path / "replay"

    code, _, stderr = run("--job", JOB_ID, "--out", str(out))

    assert code == 1
    assert "not terminal" in stderr
    assert not out.exists()
    assert not any(path.startswith("artifacts/") for path in proxy.requests)


def test_untrusted_recorded_strings_are_escaped(tmp_path: Path, proxy: Proxy, run: Run) -> None:
    out, page, detail, _ = export_sample(tmp_path, proxy, run, hostile=True)

    assert "<script" not in page.lower()
    assert "<img src=x" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in page
    tags = parse(page)
    assert not any(name.startswith("on") for _, attrs in tags for name in attrs)
    assert {tag for tag, _ in tags} <= {
        "html", "head", "meta", "title", "style", "body", "a", "header", "div", "span", "p",
        "main", "section", "h1", "h2", "h3", "dl", "dt", "dd", "figure", "figcaption", "img",
        "article", "ul", "li", "code", "pre", "strong", "br", "ol", "time", "table", "caption",
        "thead", "tbody", "tr", "th", "td", "footer", "colgroup", "col", "wbr",
    }  # fmt: skip
    images = [attrs.get("src") for tag, attrs in tags if tag == "img"]
    assert images and all(str(src).startswith("artifacts/") for src in images)
    # The unedited record keeps the raw values; it is served as data, never as markup.
    assert json.loads((out / "job.json").read_text(encoding="utf-8")) == detail


@pytest.mark.parametrize(
    ("provider", "model", "banner"),
    [
        (
            "deterministic",
            "deterministic-checkout-v1",
            "Deterministic fallback — no model call; not a Meta model trial",
        ),
        ("meta", "muse-spark-1.3", "Meta Model API · muse-spark-1.3"),
        (
            "local",
            "qwen2.5-coder:14b",
            "Local model endpoint · qwen2.5-coder:14b — not a Meta-hosted call",
        ),
        (
            "openai-compatible",
            "gpt-test",
            "OpenAI-compatible endpoint · gpt-test — not a Meta-hosted call",
        ),
        (None, "", "No provider response recorded for attempt 2"),
    ],
)
def test_provider_identity_banner(
    tmp_path: Path, proxy: Proxy, run: Run, provider: str | None, model: str, banner: str
) -> None:
    _, page, _, _ = export_sample(tmp_path, proxy, run, provider=provider, model=model)

    assert f"<strong>{banner}</strong>" in page
    if provider != "meta":
        assert "Meta Model API" not in page
    if provider == "deterministic":
        assert "not a Meta model trial" in page
        assert "token usage not reported" in page


def test_detection_job_says_no_repair_attempt_was_recorded(
    tmp_path: Path, proxy: Proxy, run: Run
) -> None:
    detail, blobs = sample_job()
    detection_only(detail, blobs)
    proxy.serve(detail, blobs)
    out = tmp_path / "replay"

    code, _, stderr = run("--job", JOB_ID, "--out", str(out))

    assert code == 0, stderr
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "<strong>No repair attempt recorded</strong>" in page
    assert "Failure detected" in page
    assert "No patched candidate was verified for this job." in page


def test_failed_job_replay_states_plainly_what_happened(
    tmp_path: Path, proxy: Proxy, run: Run
) -> None:
    _, page, _, _ = export_sample(tmp_path, proxy, run, state="failed", outcome="unresolved")

    assert '<h1 id="title">Not repaired</h1>' in page
    assert "A candidate was proposed but did not pass verification." in page
    assert 'data-verified="false"' in page
    assert "17 of 19 assertions passed" in page
    assert "verification failed" in page


def test_omit_traces_skips_archives_but_lists_their_hashes(
    tmp_path: Path, proxy: Proxy, run: Run
) -> None:
    out, page, detail, _ = export_sample(tmp_path, proxy, run, "--omit-traces")

    traces = [a for a in detail["artifacts"] if a["content_type"] == "application/zip"]
    assert len(traces) == 3
    assert not list(out.rglob("*.zip"))
    assert ".zip" not in (out / "SHA256SUMS").read_text()
    for trace in traces:
        assert trace["sha256"] in page.replace("<wbr>", "")
        assert f"artifacts/{trace['id']}" not in proxy.requests
    assert page.count("omitted from this export") >= 3
    assert "3 trace archives were omitted" in page


def test_overwrite_protection(tmp_path: Path, proxy: Proxy, run: Run) -> None:
    out, _, detail, _ = export_sample(tmp_path, proxy, run)
    before = (out / "SHA256SUMS").read_bytes()

    code, _, stderr = run("--job", JOB_ID, "--out", str(out))
    assert code == 1 and "--force" in stderr
    assert (out / "SHA256SUMS").read_bytes() == before

    (out / "artifacts" / "stale.txt").write_text("from an earlier export")
    code, _, stderr = run("--job", JOB_ID, "--out", str(out), "--force")
    assert code == 0, stderr
    assert not (out / "artifacts" / "stale.txt").exists()
    assert json.loads((out / "job.json").read_text(encoding="utf-8")) == detail

    other = tmp_path / "notes"
    other.mkdir()
    (other / "keep.txt").write_text("unrelated")
    code, _, stderr = run("--job", JOB_ID, "--out", str(other), "--force")
    assert code == 1 and "does not look like a FaultLine replay" in stderr
    assert files_in(other) == {"keep.txt"}

    empty = tmp_path / "empty"
    empty.mkdir()
    code, _, stderr = run("--job", JOB_ID, "--out", str(empty))
    assert code == 0, stderr


def test_latest_exports_the_newest_job_to_the_default_directory(
    tmp_path: Path, proxy: Proxy, run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    detail, blobs = sample_job()
    proxy.serve(detail, blobs)
    monkeypatch.setattr(replay, "ROOT", tmp_path)

    code, stdout, stderr = run("--latest")

    assert code == 0, stderr
    out = tmp_path / "replays" / JOB_ID
    assert json.loads((out / "job.json").read_text(encoding="utf-8"))["job"]["id"] == JOB_ID
    assert proxy.requests[0] == "jobs?limit=1"
    assert "not a Meta model trial" in stdout


def test_legacy_runtime_is_labeled_unverified(tmp_path: Path, proxy: Proxy, run: Run) -> None:
    _, page, _, _ = export_sample(tmp_path, proxy, run, runtime_kind=None)

    assert "Unverified historical result" in page
    assert "Unverified runtime — legacy record" in page
    assert "Isolated browser" not in page
    assert 'data-verified="false"' in page
    assert '<h1 id="title">Verified repair</h1>' not in page


def test_resource_limits_are_rendered_when_recorded(tmp_path: Path, proxy: Proxy, run: Run) -> None:
    detail, blobs = sample_job()
    detail["executions"][-1]["resource_limits"] = {
        "mode": "cgroup-v2-scope",
        "memory_max_bytes": 1 << 30,
        "memory_swap_max_bytes": 0,
        "tasks_max": 256,
        "cpu_quota_percent": 100,
        "verified": True,
    }
    detail["executions"][-2]["resource_limits"] = {
        "mode": "disabled",
        "memory_max_bytes": None,
        "memory_swap_max_bytes": None,
        "tasks_max": None,
        "cpu_quota_percent": None,
        "verified": False,
    }
    proxy.serve(detail, blobs)
    out = tmp_path / "replay"

    code, _, stderr = run("--job", JOB_ID, "--out", str(out))

    assert code == 0, stderr
    page = (out / "index.html").read_text(encoding="utf-8")
    assert (
        "cgroup-v2-scope · memory 1 GiB · swap 0 B · tasks 256 · CPU quota 100% · "
        '<span data-tone="ok">limits verified</span>'
    ) in page
    assert "aggregate limits disabled; no quota applied" in page
    assert page.count("not recorded for this execution") == 1


def test_page_only_references_files_inside_the_export(
    tmp_path: Path, proxy: Proxy, run: Run
) -> None:
    out, page, _, _ = export_sample(tmp_path, proxy, run)

    tags = parse(page)
    references = [
        str(value)
        for _, attrs in tags
        for name, value in attrs.items()
        if name in {"src", "href", "srcset", "action", "poster", "data"}
    ]
    assert references
    for reference in references:
        assert not re.match(r"^[a-z][a-z0-9+.-]*:|^/", reference, re.IGNORECASE), reference
        if not reference.startswith("#"):
            assert (out / reference).is_file(), reference
    assert not re.search(r"(?:src|href)\s*=\s*[\"']?\s*(?:https?:)?//", page, re.IGNORECASE)
    assert "url(" not in page and "@import" not in page
    meta = {attrs.get("http-equiv") or attrs.get("name"): attrs.get("content") for t, attrs in tags}
    assert "default-src 'none'" in str(meta["Content-Security-Policy"])
    assert meta["referrer"] == "no-referrer"


def test_unsafe_job_id_and_missing_job_fail_cleanly(tmp_path: Path, proxy: Proxy, run: Run) -> None:
    code, _, stderr = run("--job", "../../etc", "--out", str(tmp_path / "x"))
    assert code == 1 and "Unsafe" in stderr

    code, _, stderr = run("--job", JOB_ID, "--out", str(tmp_path / "x"))
    assert code == 1 and "HTTP 404 (not_found)" in stderr
    assert list(tmp_path.iterdir()) == []


def test_provider_error_attempt_is_not_presented_as_model_output() -> None:
    attempt = {
        "attempt_number": 1,
        "validation_result": {"dispatched_provider": "meta", "dispatched_model": "muse-spark-1.3"},
    }
    banner = replay._provider_banner([attempt])
    assert "No provider response recorded for attempt 1" in banner
    assert "sent to Meta Model API · muse-spark-1.3" in banner
    assert "<strong>Meta Model API" not in banner
