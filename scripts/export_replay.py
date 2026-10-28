#!/usr/bin/env python3
"""Export one terminal FaultLine job as a static, read-only, checksummed replay.

Run from the repository root while the demo stack is up:

    uv run --project apps/buggyshop-backend --python 3.13 --locked \\
        python scripts/export_replay.py --latest

The exporter reads the controller through the Inspector's server-side proxy, so it
never handles the control credential. Every artifact must match the size and SHA-256
the controller registered; any mismatch aborts before a single file is written. The
page is rendered only from the recorded job, with every recorded value HTML-escaped.
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import secrets
import shlex
import shutil
import struct
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSPECTOR = "http://127.0.0.1:4000"
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
TIMEOUT_SECONDS = 30.0
CSP = (
    "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
    "base-uri 'none'; form-action 'none'"
)

# Fixed extensions keep hosted evidence inert: nothing exported is ever .html or .svg.
EXTENSIONS = {"image/png": "png", "application/zip": "zip", "application/json": "json"}
TEXT_EXTENSIONS = {"diff": "diff", "logs": "log"}

# fetch(path, limit) returns at most limit + 1 bytes; callers decide what an excess means.
Fetch = Callable[[str, int], bytes]
JsonMap = dict[str, Any]


class ExportError(RuntimeError):
    """The replay cannot be exported faithfully; nothing has been written."""


@dataclass(frozen=True)
class EvidenceFile:
    """One registered artifact, verified and held in memory, or deliberately omitted."""

    artifact: JsonMap
    extension: str
    content: bytes | None

    @property
    def id(self) -> str:
        return str(self.artifact["id"])

    @property
    def path(self) -> str:
        return f"artifacts/{self.id}.{self.extension}"


@dataclass(frozen=True)
class ReplaySummary:
    """What an export wrote, for the command-line report."""

    out: Path
    job_id: str
    outcome: str
    provider: str | None
    files: tuple[str, ...]
    omitted: tuple[str, ...]


# ---------------------------------------------------------------------------
# Controller access


def http_fetcher(api: str, timeout: float = TIMEOUT_SECONDS) -> Fetch:
    """Return a bounded GET client for the controller API base (no proxies, no auth)."""
    parsed = urllib.parse.urlsplit(api)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ExportError(f"--api must be an http(s) URL, got {api!r}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ExportError("--api cannot contain credentials, a query, or a fragment")
    base = api.rstrip("/") + "/"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def fetch(path: str, limit: int) -> bytes:
        request = urllib.request.Request(base + path, headers={"Cache-Control": "no-store"})
        try:
            with opener.open(request, timeout=timeout) as response:
                body: bytes = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            code = _error_code(exc)
            exc.close()
            raise ExportError(f"GET {path} failed: HTTP {exc.code}{code}") from None
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ExportError(
                f"GET {path} failed: {reason}. Is the demo stack running? "
                "Set --api or FAULTLINE_INSPECTOR_URL for alternate ports."
            ) from None
        return body

    return fetch


def _error_code(exc: urllib.error.HTTPError) -> str:
    """Name the controller's error code without echoing an arbitrary response body."""
    try:
        error = json.loads(exc.read(4096)).get("error", {})
        code = error.get("code") if isinstance(error, dict) else None
    except (ValueError, AttributeError, OSError):
        return ""
    return f" ({code})" if isinstance(code, str) and SAFE_ID.fullmatch(code) else ""


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value}")


def _json(fetch: Fetch, path: str) -> Any:
    body = fetch(path, MAX_JSON_BYTES)
    if len(body) > MAX_JSON_BYTES:
        raise ExportError(f"GET {path} returned more than {MAX_JSON_BYTES} bytes")
    try:
        return json.loads(body, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ExportError(f"GET {path} did not return valid JSON") from exc


def latest_job_id(fetch: Fetch) -> str:
    """Resolve the newest job in the controller's latest-first history."""
    jobs = _map(_json(fetch, "jobs?limit=1")).get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ExportError("The controller has no recorded jobs to export")
    job_id = _map(jobs[0]).get("id")
    if not isinstance(job_id, str):
        raise ExportError("The newest job record has no id")
    return job_id


# ---------------------------------------------------------------------------
# Export


def export_replay(
    fetch: Fetch,
    job_id: str,
    out: Path,
    *,
    force: bool = False,
    omit_traces: bool = False,
    exported_at: datetime | None = None,
) -> ReplaySummary:
    """Fetch, verify, render, and atomically write one replay directory."""
    _require_id(job_id, "job id")
    _check_destination(out, force)
    detail = _json(fetch, f"jobs/{urllib.parse.quote(job_id, safe='')}")
    job = _validate_detail(detail, job_id)

    evidence: list[EvidenceFile] = []
    seen: set[str] = set()
    for item in detail["artifacts"]:
        artifact = _validate_artifact(item, job_id, seen)
        extension = _extension(artifact)
        if omit_traces and artifact["content_type"] == "application/zip":
            evidence.append(EvidenceFile(artifact, extension, None))
            continue
        size, digest = artifact["size_bytes"], artifact["sha256"]
        if size > MAX_ARTIFACT_BYTES:
            raise ExportError(f"Artifact {artifact['id']} exceeds the {MAX_ARTIFACT_BYTES} B cap")
        content = fetch(f"artifacts/{urllib.parse.quote(artifact['id'], safe='')}", size)
        label = f"Artifact {artifact['id']} ({artifact['role']})"
        if len(content) != size:
            received = f"more than {size}" if len(content) > size else str(len(content))
            raise ExportError(
                f"{label}: registered {size} bytes, received {received}. "
                "Refusing to export unverified evidence."
            )
        if hashlib.sha256(content).hexdigest() != digest:
            raise ExportError(
                f"{label}: SHA-256 does not match the registered {digest}. "
                "Refusing to export unverified evidence."
            )
        evidence.append(EvidenceFile(artifact, extension, content))

    stamp = (exported_at or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    try:
        record = json.dumps(detail, indent=2, ensure_ascii=False).encode()
    except UnicodeEncodeError:  # Lone surrogates survive only as JSON escapes.
        record = json.dumps(detail, indent=2).encode()
    files: dict[str, bytes] = {"job.json": record + b"\n"}
    for file in evidence:
        if file.content is not None:
            files[file.path] = file.content
    files["index.html"] = render_page(detail, evidence, stamp).encode(errors="backslashreplace")
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n" for name in sorted(files)
    ).encode()
    _write_tree(out, files, force)

    provider = _map(_last(_list(detail["attempts"])).get("validation_result")).get("provider")
    return ReplaySummary(
        out=out,
        job_id=job_id,
        outcome=str(job.get("outcome")),
        provider=provider if isinstance(provider, str) else None,
        files=tuple(sorted(files)),
        omitted=tuple(file.path for file in evidence if file.content is None),
    )


def _require_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ExportError(f"Unsafe or missing {label}: {value!r}")
    return value


def _validate_detail(detail: object, job_id: str) -> JsonMap:
    if not isinstance(detail, dict) or not isinstance(detail.get("job"), dict):
        raise ExportError("The controller returned an unexpected job detail shape")
    for key in ("attempts", "executions", "artifacts", "events"):
        if not isinstance(detail.get(key), list):
            raise ExportError(f"The job detail is missing its {key} list")
    job: JsonMap = detail["job"]
    if job.get("id") != job_id:
        raise ExportError("The controller returned a different job than requested")
    state = job.get("state")
    if state not in TERMINAL_STATES:
        raise ExportError(
            f"Job {job_id} is {state!r}, not terminal. Only finished jobs "
            "(succeeded, failed, cancelled, interrupted) can be exported."
        )
    return job


def _validate_artifact(item: object, job_id: str, seen: set[str]) -> JsonMap:
    artifact = _map(item)
    artifact_id = _require_id(artifact.get("id"), "artifact id")
    if artifact_id in seen:
        raise ExportError(f"Artifact {artifact_id} is registered twice")
    seen.add(artifact_id)
    if artifact.get("job_id", job_id) != job_id:
        raise ExportError(f"Artifact {artifact_id} belongs to a different job")
    size = artifact.get("size_bytes")
    if type(size) is not int or size < 0:
        raise ExportError(f"Artifact {artifact_id} has no valid registered size")
    if not isinstance(artifact.get("sha256"), str) or not SHA256_HEX.fullmatch(artifact["sha256"]):
        raise ExportError(f"Artifact {artifact_id} has no valid registered SHA-256")
    if not isinstance(artifact.get("role"), str):
        raise ExportError(f"Artifact {artifact_id} has no role")
    return artifact


def _extension(artifact: JsonMap) -> str:
    content_type = artifact.get("content_type")
    if content_type == "text/plain":
        return TEXT_EXTENSIONS.get(artifact["role"], "txt")
    if isinstance(content_type, str) and content_type in EXTENSIONS:
        return EXTENSIONS[content_type]
    raise ExportError(f"Artifact {artifact['id']} has unsupported content type {content_type!r}")


def _check_destination(out: Path, force: bool) -> None:
    if out.is_symlink() or (out.exists() and not out.is_dir()):
        raise ExportError(f"{out} exists and is not a directory")
    if not out.is_dir() or not any(out.iterdir()):
        return
    if not force:
        raise ExportError(f"{out} is not empty. Pass --force to replace an earlier replay.")
    if not (out / "SHA256SUMS").is_file() or not (out / "job.json").is_file():
        raise ExportError(
            f"{out} does not look like a FaultLine replay; refusing to replace it even with --force"
        )


def _write_tree(out: Path, files: Mapping[str, bytes], force: bool) -> None:
    """Write into a sibling staging directory, then swap it into place."""
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.", suffix=".partial", dir=out.parent))
    retired: Path | None = None
    try:
        for name, content in files.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(content)
        for directory in (staging, staging / "artifacts"):
            if directory.is_dir():
                directory.chmod(0o755)
        _check_destination(out, force)  # The directory may have changed while fetching.
        if out.is_dir():
            if any(out.iterdir()):
                retired = out.parent / f".{out.name}.{secrets.token_hex(4)}.replaced"
                out.rename(retired)
            else:
                out.rmdir()
        staging.rename(out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if retired is not None and not out.exists():
            retired.rename(out)
        raise
    if retired is not None:
        shutil.rmtree(retired)


# ---------------------------------------------------------------------------
# Recorded-data helpers


def _map(value: object) -> JsonMap:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _last(items: list[Any]) -> JsonMap:
    return _map(items[-1]) if items else {}


def e(value: object) -> str:
    """Escape any recorded value for HTML text or a quoted attribute."""
    return html.escape(str(value), quote=True)


def _hash(value: object) -> str:
    """Escape a digest, letting a SHA-256 wrap evenly at its midpoint."""
    if isinstance(value, str) and SHA256_HEX.fullmatch(value):
        return f"{value[:32]}<wbr>{value[32:]}"
    return e(value)


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _time(value: object, fmt: str = "%Y-%m-%d %H:%M:%S UTC") -> str:
    parsed = _when(value)
    if parsed is None:
        return '<span class="muted">not recorded</span>' if value is None else e(value)
    return f'<time datetime="{e(value)}">{parsed.strftime(fmt)}</time>'


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KB" if n < 1048576 else f"{n / 1048576:.1f} MB"


def _png_size(content: bytes | None) -> tuple[int, int] | None:
    if not content or len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if content[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", content[16:24])
    return (width, height) if 0 < width <= 32768 and 0 < height <= 32768 else None


def _words(value: object) -> str:
    return str(value).replace("_", " ")


OUTCOME: dict[str, tuple[str, str, str]] = {
    "verified": (
        "ok",
        "Verified repair",
        "The baseline reproduced the seeded failure, and the patched candidate passed "
        "verification.",
    ),
    "detected": (
        "warn",
        "Failure detected",
        "Detection run: the seeded failure reproduced. No patch was requested.",
    ),
    "no_failure": (
        "idle",
        "No failure reproduced",
        "The baseline passed, so there was nothing to repair.",
    ),
    "repair_unavailable": (
        "warn",
        "Reproduced; repair unavailable",
        "The failure reproduced, but no repair provider was available for this job.",
    ),
    "unexpected_failure": (
        "bad",
        "Unexpected failure",
        "The baseline failed with a signature that does not match the seeded defect, so repair "
        "was not attempted.",
    ),
    "invalid_patch": (
        "bad",
        "Patch rejected",
        "The proposed patch failed scope, syntax, or safety policy and was not activated.",
    ),
    "model_error": (
        "bad",
        "Model error",
        "The repair provider failed or returned an unusable proposal.",
    ),
    "unresolved": (
        "bad",
        "Not repaired",
        "A candidate was proposed but did not pass verification.",
    ),
    "infrastructure_error": (
        "bad",
        "Infrastructure error",
        "The runner or runtime failed. This result says nothing about the code under test.",
    ),
    "artifact_error": (
        "bad",
        "Evidence integrity error",
        "Recorded artifacts failed verification, so the result is not trusted.",
    ),
    "timeout": ("bad", "Timed out", "The job exceeded its work deadline."),
    "cleanup_failed": (
        "bad",
        "Cleanup failed",
        "Disposal of job resources could not be confirmed.",
    ),
    "cancelled": ("warn", "Cancelled", "Cancellation was requested and honored."),
    "interrupted": (
        "warn",
        "Interrupted",
        "The orchestrator stopped while this job was running.",
    ),
}
LEGACY_OUTCOME = (
    "warn",
    "Unverified historical result",
    "This record predates isolated browser evidence. Its previous success label cannot "
    "establish that a repair was verified.",
)
VERDICT = {
    "passed": "Passed",
    "failed": "Failed",
    "error": "Runner error",
    "timed_out": "Timed out",
}
STAGE_LABEL = {
    "preparing": "Prepare",
    "baseline": "Reproduce",
    "diagnosing": "Propose patch",
    "patch_validation": "Policy check",
    "activating": "Activate candidate",
    "verification": "Verify",
    "cleanup": "Clean up",
    "completed": "Done",
}


def provider_label(provider: str, model: object) -> tuple[str, str]:
    """Return (tone, label) for a recorded provider identity, never upgrading its claim."""
    name = model if isinstance(model, str) and model else "model not recorded"
    if provider == "deterministic":
        return "warn", "Deterministic fallback — no model call; not a Meta model trial"
    if provider == "meta":
        return "idle", f"Meta Model API · {name}"
    if provider == "local":
        return "warn", f"Local model endpoint · {name} — not a Meta-hosted call"
    if provider == "openai-compatible":
        return "idle", f"OpenAI-compatible endpoint · {name} — not a Meta-hosted call"
    return "warn", f"Unrecognized provider “{provider}” · {name} — not identified as Meta"


def _provider_banner(attempts: list[Any]) -> str:
    if not attempts:
        tone, label = "idle", "No repair attempt recorded"
        note = "No model or fallback was asked for a patch in this job."
    else:
        last = _last(attempts)
        result = _map(last.get("validation_result"))
        number = e(last.get("attempt_number", "?"))
        provider = result.get("provider")
        if isinstance(provider, str):
            tone, label = provider_label(provider, result.get("model"))
            note = f"Recorded by the controller for attempt {number}"
            if provider == "deterministic" and isinstance(result.get("model"), str):
                note += f" · adapter <code>{e(result['model'])}</code>"
        else:
            tone, label = "warn", f"No provider response recorded for attempt {number}"
            note = "The attempt ended before any provider answered"
            dispatched = result.get("dispatched_provider")
            if isinstance(dispatched, str):
                sent = provider_label(dispatched, result.get("dispatched_model"))[1]
                note += f"; it was sent to {e(sent)}"
    return (
        f'<div class="callout" data-tone="{tone}"><p class="eyebrow">Repair provider</p>'
        f'<p><strong>{e(label)}</strong></p><p class="muted note">{note}.</p></div>'
    )


def _belongs(artifact: JsonMap, run: JsonMap) -> bool:
    report = _map(run.get("report"))
    return artifact.get("execution_id") == report.get("execution_id") or artifact.get(
        "id"
    ) in _list(run.get("artifact_ids"))


def _failure_signal(report: JsonMap) -> str:
    observations = [_map(item) for item in _list(report.get("observations"))]
    observation = next((o for o in observations if o.get("kind") != "assertion"), None)
    observation = observation or (observations[0] if observations else None)
    if observation is not None:
        return str(observation.get("message", ""))
    assertions = [_map(a) for a in _list(report.get("assertions"))]
    failed = next((a for a in assertions if a.get("passed") is not True), None)
    if failed is not None:
        expected, observed = failed.get("expected"), failed.get("observed")
        return f"{failed.get('id')}: expected {expected}, observed {observed}"
    return "No failure detail recorded."


def _runtime(run: JsonMap) -> tuple[str, str]:
    if run.get("runtime_kind") == "isolated-browser":
        return "ok", "Isolated browser"
    return "warn", "Unverified runtime — legacy record"


# ---------------------------------------------------------------------------
# Page


STYLE = """
:root {
  color-scheme: dark;
  --bg: #0b0c0e; --well: #08090b;
  --line: rgba(255, 255, 255, 0.08); --line-strong: rgba(255, 255, 255, 0.16);
  --ink: #e9ebee; --ink-2: #a5abb4; --ink-3: #949ba6;
  --red: #f0565b; --red-wash: rgba(240, 86, 91, 0.08);
  --green: #3fca83; --green-wash: rgba(63, 202, 131, 0.08); --amber: #dba54a;
  --add: #93e2b8; --del: #f4a5a8;
  --sans: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", "SF Mono", ui-monospace, Menlo, Consolas, monospace;
}
*, ::before, ::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 var(--sans);
  font-feature-settings: "tnum" 1; -webkit-font-smoothing: antialiased;
}
code, pre, time, dd, td, .eyebrow, .tag { font-family: var(--mono); }
code { font-size: 0.92em; overflow-wrap: anywhere; }
a { color: var(--ink); text-underline-offset: 3px; }
:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; border-radius: 4px; }
.muted { color: var(--ink-3); }
.sr-only {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip-path: inset(50%); white-space: nowrap;
}
.skip { position: absolute; left: -9999px; }
.skip:focus { left: 16px; top: 12px; z-index: 20; padding: 8px 12px; background: var(--ink);
  color: var(--bg); }
.shell { max-width: 1120px; margin: 0 auto; padding: 0 24px; }
main, section, figure, .facts div, .cols > * { min-width: 0; }
[data-tone="ok"]:is(span, strong, dd, td) { color: var(--green); }
[data-tone="bad"]:is(span, strong, dd, td) { color: var(--red); }
[data-tone="warn"]:is(span, strong, dd, td) { color: var(--amber); }

.top { border-bottom: 1px solid var(--line); }
.top-row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 8px 16px; min-height: 56px; }
.wordmark { display: inline-flex; align-items: center; gap: 10px; font-weight: 600;
  letter-spacing: -0.01em; }
.glyph { width: 14px; height: 14px; border-radius: 3px;
  background: linear-gradient(135deg, var(--red) 0 46%, transparent 46% 54%, var(--green) 54%); }
.tag { margin: 0; padding: 3px 8px; border: 1px solid var(--line-strong); border-radius: 4px;
  font-size: 11.5px; color: var(--ink-2); }

.intro { padding: 40px 0 0; }
.eyebrow { margin: 0 0 12px; font-size: 12px; color: var(--ink-3); overflow-wrap: anywhere; }
h1 { margin: 0; max-width: 24ch; font-size: clamp(30px, 4.4vw, 46px); line-height: 1.08;
  font-weight: 600; letter-spacing: -0.025em; }
h2 { display: flex; align-items: baseline; gap: 12px; margin: 0 0 24px; font-size: 20px;
  line-height: 1.25; font-weight: 600; letter-spacing: -0.015em; }
h2 .idx { font: 12px var(--mono); color: var(--ink-3); }
h3 { margin: 0 0 12px; font-size: 14px; font-weight: 600; }
h3 .muted, h3 [data-tone] { margin-left: 8px; font: 400 12.5px var(--mono); }
.lede { max-width: 68ch; margin: 16px 0 0; color: var(--ink-2); }
.callout { max-width: 76ch; margin: 28px 0 0; padding: 2px 0 2px 14px;
  border-left: 2px solid var(--line-strong); }
.callout[data-tone="warn"] { border-color: var(--amber); }
.callout[data-tone="bad"] { border-color: var(--red); }
.callout p { margin: 0; }
.callout .eyebrow { margin-bottom: 4px; }
.callout strong { font-weight: 600; }
.note { margin-top: 4px !important; font-size: 13px; }
.facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 16px 24px; margin: 32px 0 0; padding: 20px 0 0; border-top: 1px solid var(--line);
  font-size: 13px; }
.facts dt { font-size: 12px; color: var(--ink-3); }
.facts dd { margin: 2px 0 0; overflow-wrap: anywhere; }
.detail { max-width: 80ch; margin: 16px 0 0; font-size: 13px; color: var(--ink-3); }

.block { margin-top: 56px; padding-top: 24px; border-top: 1px solid var(--line); }
.block > p { max-width: 76ch; color: var(--ink-2); }
.seam { display: grid; grid-template-columns: 1fr 1px 1fr; border: 1px solid var(--line);
  border-radius: 12px; overflow: hidden; }
.seam-rule { background: var(--line); }
.seam[data-verified="true"] .seam-rule { background: linear-gradient(var(--red), var(--green)); }
.side { margin: 0; padding: 24px; }
.side .eyebrow { margin-bottom: 16px; }
.side[data-tone="bad"] { background: var(--red-wash); }
.side[data-tone="ok"] { background: var(--green-wash); }
.verdict { margin: 0; font-size: 28px; font-weight: 600; letter-spacing: -0.02em;
  color: var(--ink-3); }
.side[data-tone="bad"] .verdict { color: var(--red); }
.side[data-tone="ok"] .verdict { color: var(--green); }
.side[data-tone="warn"] .verdict { color: var(--amber); }
.signal { margin: 8px 0 0; font: 13px/1.5 var(--mono); overflow-wrap: anywhere; }
.meta { margin: 12px 0 0; font: 12px/1.5 var(--mono); color: var(--ink-3);
  overflow-wrap: anywhere; }
.shot { display: block; margin-top: 16px; }
.shot img { display: block; width: 100%; height: auto; border: 1px solid var(--line);
  border-radius: 6px; background: #000; }

.attempt { padding: 20px 0 24px; border-bottom: 1px solid var(--line); }
.attempt:first-of-type { padding-top: 0; }
.attempt:last-of-type { padding-bottom: 0; border-bottom: 0; }
.inline { display: flex; flex-wrap: wrap; gap: 6px 20px; margin: 0 0 16px; padding: 0;
  list-style: none; font: 12.5px/1.5 var(--mono); color: var(--ink-2); }
.inline li { min-width: 0; overflow-wrap: anywhere; }
.inline [data-tone="ok"] { color: var(--green); }
.inline [data-tone="bad"] { color: var(--red); }
.explain, .feedback { max-width: 80ch; margin: 0 0 16px; color: var(--ink-2); }
.explain .eyebrow, .feedback .eyebrow { display: block; margin-bottom: 4px; }
.feedback { padding-left: 14px; border-left: 2px solid var(--line-strong); }
.feedback p { margin: 0 0 6px; font-size: 13.5px; }
.feedback .inline { margin: 8px 0 0; }
.code { margin: 0; padding: 14px 0; max-height: 560px; overflow: auto; background: var(--well);
  border: 1px solid var(--line); border-radius: 8px; font: 12.5px/1.65 var(--mono); }
.code span { display: block; padding: 0 16px; white-space: pre; color: var(--ink-2); }
.code [data-kind="add"] { background: var(--green-wash); color: var(--add); }
.code [data-kind="del"] { background: var(--red-wash); color: var(--del); }
.code :is([data-kind="hunk"], [data-kind="file"]) { color: var(--ink-3); }

.group + .group { margin-top: 32px; }
.scroll { position: relative; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; line-height: 1.5; }
th { padding: 0 16px 8px 0; border-bottom: 1px solid var(--line-strong); text-align: left;
  font-size: 12px; font-weight: 500; color: var(--ink-3); white-space: nowrap; }
td { padding: 8px 16px 8px 0; border-bottom: 1px solid var(--line); vertical-align: top;
  color: var(--ink-2); overflow-wrap: anywhere; }
td:first-child { color: var(--ink); }
.stack { table-layout: fixed; }
.asserts col:nth-child(1) { width: 36%; }
.asserts col:nth-child(2) { width: 9%; }
.asserts col:nth-child(n + 3) { width: 27.5%; }
.files col:nth-child(1) { width: 21%; }
.files col:nth-child(2) { width: 17%; }
.files col:nth-child(3) { width: 52%; }
.files col:nth-child(4) { width: 10%; }
td[data-tone="bad"] { font-weight: 600; }

.events { margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--line); }
.events li { display: grid; grid-template-columns: 4ch 9ch 9ch 19ch 1fr; gap: 12px;
  padding: 7px 0; border-bottom: 1px solid var(--line); font: 12.5px/1.5 var(--mono); }
.events li > * { min-width: 0; overflow-wrap: anywhere; }

.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
.kv { display: grid; grid-template-columns: minmax(11ch, max-content) 1fr; margin: 0;
  font-size: 13px; }
.kv dt, .kv dd { padding: 7px 0; border-bottom: 1px solid var(--line); }
.kv dt { padding-right: 20px; color: var(--ink-3); }
.kv dd { margin: 0; min-width: 0; font-size: 12.5px; overflow-wrap: anywhere; }
.verify { margin-top: 32px; }
.verify pre { margin: 12px 0; padding: 12px 16px; background: var(--well);
  border: 1px solid var(--line); border-radius: 8px; overflow-x: auto; font-size: 12.5px; }
.verify p { max-width: 76ch; margin: 0 0 8px; color: var(--ink-2); font-size: 13.5px; }

.foot { margin-top: 96px; padding-bottom: 48px; font-size: 12.5px; color: var(--ink-3); }
.foot > div { padding-top: 24px; border-top: 1px solid var(--line); }
.foot p { max-width: 80ch; margin: 0 0 8px; }
.foot strong { color: var(--ink-2); font-weight: 600; }

@media (max-width: 760px) {
  .shell { padding: 0 16px; }
  .cols { grid-template-columns: 1fr; gap: 24px; }
  .seam { grid-template-columns: 1fr; }
  .seam-rule { height: 1px; }
  .seam[data-verified="true"] .seam-rule {
    background: linear-gradient(90deg, var(--red), var(--green)); }
  .side { padding: 20px 16px; }
  .facts { grid-template-columns: 1fr 1fr; }
  .events li { grid-template-columns: 4ch 1fr; gap: 2px 12px; }
  .events li > :nth-child(n + 3) { grid-column: 2; }
  .events li > :nth-child(3), .events li > :nth-child(4) { color: var(--ink-3); }
  .kv { grid-template-columns: 1fr; }
  .kv dt { padding-bottom: 0; border-bottom: 0; }
  .stack, .stack tbody, .stack td { display: block; }
  .stack colgroup { display: none; }
  .stack thead { position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip-path: inset(50%); white-space: nowrap; }
  .stack tr { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 12px;
    padding: 9px 0; border-bottom: 1px solid var(--line); }
  .stack td { min-width: 0; padding: 0; border: 0; }
  .asserts td:nth-child(n + 3), .files td:nth-child(2), .files td:nth-child(3) {
    grid-column: 1 / -1; color: var(--ink-3); }
  .asserts td:nth-child(3)::before { content: "expected "; }
  .asserts td:nth-child(4)::before { content: "observed "; }
  .files td:nth-child(3)::before { content: "sha256 "; }
  .files td:nth-child(4) { grid-row: 1; grid-column: 2; }
}
@media print {
  :root {
    color-scheme: light; --bg: #fff; --well: #f6f7f8; --line: #d9dce1; --line-strong: #a9afb8;
    --ink: #111; --ink-2: #2b2f36; --ink-3: #555b64; --red: #b3261e; --red-wash: #fdf0ef;
    --green: #1d6f42; --green-wash: #edf7f1; --amber: #8a5300; --add: #1d6f42; --del: #b3261e;
  }
  body { font-size: 12px; }
  .skip { display: none; }
  .code { max-height: none; overflow: visible; }
  .code span { white-space: pre-wrap; overflow-wrap: anywhere; }
  .block { break-inside: auto; }
  tr, .events li, .side, .attempt h3 { break-inside: avoid; }
}
"""


def _section(index: int, key: str, title: str, body: str) -> str:
    return (
        f'<section class="block" aria-labelledby="{key}-h">'
        f'<h2 id="{key}-h"><span class="idx" aria-hidden="true">{index:02d}</span>{title}</h2>'
        f"{body}</section>"
    )


def _side(
    label: str,
    run: JsonMap | None,
    tone: str,
    empty: str,
    shot: EvidenceFile | None,
    phase: str,
) -> str:
    parts = [
        f'<figure class="side" data-tone="{tone}">'
        f'<figcaption class="eyebrow">{e(label)}</figcaption>'
    ]
    if run is None:
        parts.append(f'<p class="signal muted">{e(empty)}</p></figure>')
        return "".join(parts)
    report = _map(run.get("report"))
    verdict = report.get("verdict")
    assertions = [_map(a) for a in _list(report.get("assertions"))]
    passed = sum(1 for a in assertions if a.get("passed") is True)
    count = f"{passed} of {len(assertions)} assertions passed"
    parts.append(f'<p class="verdict">{e(VERDICT.get(str(verdict), _words(verdict)))}</p>')
    if verdict == "passed":
        parts.append(f'<p class="signal">{count}</p>')
    else:
        parts.append(f'<p class="signal">{e(_failure_signal(report))}</p>')
        if assertions:
            parts.append(f'<p class="meta">{count}</p>')
    _, runtime = _runtime(run)
    duration = report.get("duration_ms")
    meta = [e(runtime)]
    if isinstance(duration, int | float):
        meta.append(f"{round(duration)} ms")
    snapshot = run.get("candidate_snapshot_sha256")
    if isinstance(snapshot, str):
        meta.append(f"snapshot {e(snapshot[:12])}")
    parts.append(f'<p class="meta">{" · ".join(meta)}</p>')
    if shot is not None and shot.content is not None:
        dims = _png_size(shot.content)
        size = f' width="{dims[0]}" height="{dims[1]}"' if dims else ""
        parts.append(
            f'<a class="shot" href="{e(shot.path)}"><img src="{e(shot.path)}"{size} '
            f'alt="Browser screenshot captured during the {phase} run" loading="lazy"></a>'
            f'<p class="meta">screenshot · sha256 {e(str(shot.artifact["sha256"])[:12])}</p>'
        )
    parts.append("</figure>")
    return "".join(parts)


def _diff(text: str, label: str) -> str:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    spans = []
    for line in lines:
        if line.startswith("@@"):
            kind = "hunk"
        elif line.startswith(("+++", "---")):
            kind = "file"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "del"
        else:
            kind = "ctx"
        spans.append(f'<span data-kind="{kind}">{e(line) or " "}</span>')
    return f'<pre class="code" tabindex="0" aria-label="{e(label)}">{"".join(spans)}</pre>'


def _policy(result: JsonMap) -> str:
    if not isinstance(result.get("is_valid"), bool):
        return '<p class="muted inline">Patch policy did not evaluate this attempt.</p>'

    def flag(label: str, value: object) -> str:
        ok = value is True
        return f'<li data-tone="{"ok" if ok else "bad"}">{label} {"pass" if ok else "fail"}</li>'

    items = [
        flag("Policy", result.get("is_valid")),
        flag("Syntax", result.get("syntax_valid")),
        flag("AST safety", result.get("ast_safe")),
    ]
    if isinstance(result.get("target_file"), str):
        items.append(f"<li><code>{e(result['target_file'])}</code></li>")
    if isinstance(result.get("error_message"), str):
        items.append(f'<li data-tone="bad">{e(result["error_message"])}</li>')
    if result.get("diff_recounted") is True:
        items.append("<li>hunk headers recounted from the model's diff</li>")
    return f'<ul class="inline" aria-label="Patch policy result">{"".join(items)}</ul>'


def _feedback(value: object) -> str:
    """Show what the controller fed back to this attempt from the rejected previous one."""
    head = '<div class="feedback"><span class="eyebrow">Fed back from the previous attempt</span>'
    feedback = _map(value)
    if not feedback:
        raw = json.dumps(value, ensure_ascii=False, indent=2)
        return f'{head}<pre class="code" tabindex="0"><span>{e(raw)}</span></pre></div>'
    facts = []
    if "gate" in feedback:
        facts.append(f"Rejected by <code>{e(feedback['gate'])}</code>")
    checks = _list(feedback.get("failed_checks"))
    total = feedback.get("failed_check_count")
    if isinstance(total, int):
        shown = f" (showing {len(checks)})" if len(checks) < total else ""
        facts.append(f"{total} failing check{'s' if total != 1 else ''} reported{shown}")
    included = feedback.get("included_rejected_diff")
    if isinstance(included, bool):
        facts.append("rejected diff included" if included else "rejected diff not included")
    parts = [head, f"<p>{' · '.join(facts) or 'Feedback recorded.'}</p>"]
    if isinstance(feedback.get("policy_error"), str):
        parts.append(f"<p>Policy error: <code>{e(feedback['policy_error'])}</code></p>")
    if checks:
        items = []
        for check in checks:
            if isinstance(check, dict):
                text = f"<code>{e(check.get('id'))}</code>"
                if "expected" in check or "observed" in check:
                    text += (
                        f' <span class="muted">expected {e(check.get("expected"))} · '
                        f"observed {e(check.get('observed'))}</span>"
                    )
                items.append(f"<li>{text}</li>")
            else:
                items.append(f"<li><code>{e(check)}</code></li>")
        parts.append(
            f'<ul class="inline" aria-label="Failing checks fed back">{"".join(items)}</ul>'
        )
    known = {
        "gate",
        "failed_checks",
        "failed_check_count",
        "included_rejected_diff",
        "policy_error",
    }
    extra = {key: item for key, item in feedback.items() if key not in known}
    if extra:
        parts.append(f'<p class="muted">Also recorded: <code>{e(json.dumps(extra))}</code></p>')
    parts.append("</div>")
    return "".join(parts)


def _attempt(attempt: JsonMap, index: int) -> str:
    number = attempt.get("attempt_number", index + 1)
    result = _map(attempt.get("validation_result"))
    outcome = attempt.get("outcome")
    tone = "ok" if outcome == "verified" else "bad" if isinstance(outcome, str) else "idle"
    status = _words(outcome) if isinstance(outcome, str) else "no outcome recorded"
    parts = [
        f'<article class="attempt" aria-labelledby="attempt-{index}-h">'
        f'<h3 id="attempt-{index}-h">Attempt {e(number)}'
        f'<span data-tone="{tone}">{e(status)}</span></h3>'
    ]
    facts = []
    provider = result.get("provider")
    if isinstance(provider, str):
        facts.append(e(provider_label(provider, result.get("model"))[1]))
    elif isinstance(result.get("dispatched_provider"), str):
        sent = provider_label(str(result["dispatched_provider"]), result.get("dispatched_model"))
        facts.append(f"no provider response · sent to {e(sent[1])}")
    else:
        facts.append("provider not recorded")
    prompt, completion = attempt.get("prompt_tokens"), attempt.get("completion_tokens")
    if prompt is None and completion is None:
        facts.append("token usage not reported")
    else:
        facts.append(
            f"{e(prompt if prompt is not None else 'not reported')} prompt · "
            f"{e(completion if completion is not None else 'not reported')} completion tokens"
        )
    if isinstance(result.get("generation_ms"), int | float):
        facts.append(f"generation {e(round(result['generation_ms']))} ms")
    parts.append(f'<ul class="inline">{"".join(f"<li>{fact}</li>" for fact in facts)}</ul>')
    parts.append(_policy(result))
    if "prior_feedback" in result and result["prior_feedback"] is not None:
        parts.append(_feedback(result["prior_feedback"]))
    explanation: object = None
    decision: object = None
    raw = attempt.get("raw_patch")
    if isinstance(raw, str):
        try:
            proposal = json.loads(raw)
        except ValueError:
            proposal = None
        if isinstance(proposal, dict):
            explanation, decision = proposal.get("explanation"), proposal.get("decision")
    if decision == "no_patch":
        parts.append('<p class="explain">The provider declined to propose a patch.</p>')
    if isinstance(explanation, str) and explanation:
        parts.append(
            f'<p class="explain"><span class="eyebrow">Provider explanation</span>'
            f"{e(explanation)}</p>"
        )
    diff = attempt.get("parsed_diff")
    if isinstance(diff, str) and diff:
        parts.append(_diff(diff, f"Unified diff from attempt {number}"))
    else:
        parts.append('<p class="muted">No diff was returned for this attempt.</p>')
    parts.append("</article>")
    return "".join(parts)


def _table(kind: str, label: str, headers: list[str], rows: list[list[tuple[str, str]]]) -> str:
    """Emit a table whose explicit roles survive the stacked narrow-screen layout."""
    head = "".join(f'<th scope="col" role="columnheader">{name}</th>' for name in headers)
    body = "".join(
        '<tr role="row">'
        + "".join(f'<td role="cell"{attrs}>{cell}</td>' for cell, attrs in row)
        + "</tr>"
        for row in rows
    )
    return (
        f'<div class="scroll"><table class="stack {kind}" role="table">'
        f'<caption class="sr-only">{e(label)}</caption>'
        f"<colgroup>{'<col>' * len(headers)}</colgroup>"
        f'<thead role="rowgroup"><tr role="row">{head}</tr></thead>'
        f'<tbody role="rowgroup">{body}</tbody></table></div>'
    )


def _run_label(run: JsonMap, attempts: list[JsonMap]) -> str:
    if run.get("phase") == "baseline":
        return "Baseline run"
    attempt = next((a for a in attempts if a.get("id") == run.get("attempt_id")), None)
    number = attempt.get("attempt_number") if attempt else None
    return f"Verification run · attempt {number}" if number is not None else "Verification run"


def _assertions(runs: list[JsonMap], attempts: list[JsonMap]) -> str:
    if not runs:
        return '<p class="muted">No browser execution was recorded for this job.</p>'
    groups = []
    for run in runs:
        label = _run_label(run, attempts)
        assertions = [_map(a) for a in _list(_map(run.get("report")).get("assertions"))]
        passed = sum(1 for a in assertions if a.get("passed") is True)
        head = f'<h3>{e(label)}<span class="muted">{passed} of {len(assertions)} passed</span></h3>'
        if not assertions:
            empty = '<p class="muted">No assertions recorded.</p>'
            groups.append(f'<div class="group">{head}{empty}</div>')
            continue
        rows = [
            [
                (e(item.get("id")), ""),
                (
                    "pass" if item.get("passed") is True else "fail",
                    f' data-tone="{"ok" if item.get("passed") is True else "bad"}"',
                ),
                (e(item.get("expected")), ""),
                (e(item.get("observed")), ""),
            ]
            for item in assertions
        ]
        headers = ["Assertion", "Result", "Expected", "Observed"]
        table = _table("asserts", f"{label} assertions", headers, rows)
        groups.append(f'<div class="group">{head}{table}</div>')
    return "".join(groups)


def _events(events: list[JsonMap], created: datetime | None) -> str:
    if not events:
        return '<p class="muted">No events were recorded for this job.</p>'
    items = []
    for event in events:
        when = _when(event.get("timestamp"))
        offset = (
            f"+{(when - created).total_seconds():.1f} s" if when is not None and created else ""
        )
        stage = event.get("stage")
        items.append(
            f'<li><span class="muted">{e(str(event.get("sequence", "")).zfill(3))}</span>'
            f"{_time(event.get('timestamp'), '%H:%M:%S')}"
            f"<span>{e(offset)}</span>"
            f"<span>{e(STAGE_LABEL.get(str(stage), stage))}</span>"
            f"<span>{e(event.get('message', ''))} "
            f'<code class="muted">{e(event.get("message_code", ""))}</code></span></li>'
        )
    return (
        "<p>Times are UTC; offsets are measured from job creation.</p>"
        f'<ol class="events" aria-label="Job events">{"".join(items)}</ol>'
    )


def _bytes(value: object) -> str:
    if type(value) is not int:
        return e(value)
    for unit, scale in (("GiB", 1 << 30), ("MiB", 1 << 20), ("KiB", 1 << 10)):
        if value >= scale and value % scale == 0:
            return f"{value // scale} {unit}"
    return f"{value:,} B"


LIMIT_FIELDS = (
    ("memory_max_bytes", "memory", _bytes),
    ("memory_swap_max_bytes", "swap", _bytes),
    ("tasks_max", "tasks", e),
    ("cpu_quota_percent", "CPU quota", lambda value: f"{e(value)}%"),
)


def _limits(value: object) -> str:
    """Render ResourceLimits as recorded; absent means unknown, never enforced."""
    limits = _map(value)
    if not limits:
        return '<span class="muted">not recorded for this execution</span>'
    if limits.get("mode") == "disabled":
        return '<span data-tone="warn">aggregate limits disabled; no quota applied</span>'
    rendered = [e(limits.get("mode", "mode not recorded"))]
    handled = {"mode", "verified"}
    if limits.get("mode") == "cgroup-v2-scope":
        for key, label, render in LIMIT_FIELDS:
            handled.add(key)
            rendered.append(f"{label} {render(limits.get(key))}")
    for key in [k for k in limits if k not in handled] + ["verified"]:
        if key not in limits:
            continue
        item = limits[key]
        if key == "verified" and isinstance(item, bool):
            tone, status = ("ok", "limits verified") if item else ("warn", "limits not verified")
            rendered.append(f'<span data-tone="{tone}">{status}</span>')
            continue
        shown = item if isinstance(item, str | int | float) else json.dumps(item)
        rendered.append(f"{e(_words(key))} {e(shown)}")
    return " · ".join(rendered)


def _runtime_section(job: JsonMap, runs: list[JsonMap], attempts: list[JsonMap]) -> str:
    columns = []
    for run in runs:
        label = _run_label(run, attempts)
        report = _map(run.get("report"))
        tone, runtime = _runtime(run)
        rows = [
            ("Runtime", f'<span data-tone="{tone}">{e(runtime)}</span>'),
            ("Execution", e(report.get("execution_id", "not recorded"))),
            ("Started", _time(run.get("started_at"))),
            ("Finished", _time(run.get("finished_at"))),
        ]
        if isinstance(report.get("duration_ms"), int | float):
            rows.append(("Runner time", f"{e(round(report['duration_ms']))} ms"))
        rows += [
            ("Snapshot sha256", _hash(run.get("candidate_snapshot_sha256", "not recorded"))),
            ("App generation", e(run.get("app_generation_id", "not recorded"))),
            ("Resource limits", _limits(run.get("resource_limits"))),
        ]
        body = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in rows)
        columns.append(f'<div><h3>{e(label)}</h3><dl class="kv">{body}</dl></div>')
    cleanup = job.get("cleanup_status")
    cleanup_tone = "ok" if cleanup == "succeeded" else "bad" if cleanup == "failed" else "warn"
    candidate_attempt = next(
        (a for a in reversed(attempts) if _map(a.get("validation_result")).get("candidate_sha256")),
        None,
    )
    rows = [
        ("Cleanup", f'<span data-tone="{cleanup_tone}">{e(_words(cleanup))}</span>'),
        ("Final state", e(job.get("state"))),
        ("Final stage", e(STAGE_LABEL.get(str(job.get("stage")), job.get("stage")))),
    ]
    if candidate_attempt is not None:
        number = candidate_attempt.get("attempt_number")
        candidate = _map(candidate_attempt.get("validation_result")).get("candidate_sha256")
        rows.append((f"Candidate sha256 (attempt {e(number)})", _hash(candidate)))
    for key, name in (
        ("seed_commit", "Seed commit"),
        ("seed_source_hash", "Seed source sha256"),
        ("fixture_version", "Fixture version"),
        ("scenario_version", "Scenario version"),
    ):
        if job.get(key) is not None:
            rows.append((name, _hash(job[key])))
    body = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in rows)
    columns.append(f'<div><h3>Job resources</h3><dl class="kv">{body}</dl></div>')
    return f'<div class="cols">{"".join(columns)}</div>'


def _evidence_section(
    evidence: list[EvidenceFile], runs: list[JsonMap], attempts: list[JsonMap]
) -> str:
    rows = []
    for file in evidence:
        artifact = file.artifact
        run = next((x for x in runs if _belongs(artifact, x)), None)
        attempt = next((a for a in attempts if a.get("id") == artifact.get("attempt_id")), None)
        origin = (
            _run_label(run, attempts).lower().replace("run · ", "run, ")
            if run is not None
            else f"attempt {attempt.get('attempt_number')}"
            if attempt is not None
            else "job"
        )
        if file.content is not None:
            verb = "Download" if file.extension == "zip" else "Open"
            link = (
                f'<a href="{e(file.path)}">{verb}<span class="sr-only"> '
                f"{e(artifact['role'])} from {e(origin)}</span></a>"
            )
        else:
            link = '<span data-tone="warn">omitted from this export</span>'
        size = int(artifact["size_bytes"])
        exact = f" ({size:,} B)" if size >= 1024 else ""
        rows.append(
            [
                (f'{e(artifact["role"])}<br><span class="muted">{e(origin)}</span>', ""),
                (
                    f"{e(artifact.get('content_type'))}<br>"
                    f'<span class="muted">{_size(size)}{exact}</span>',
                    "",
                ),
                (_hash(artifact["sha256"]), ""),
                (link, ""),
            ]
        )
    omitted = [file for file in evidence if file.content is None]
    headers = ["Role", "Type and size", "Registered SHA-256", "File"]
    table = (
        _table("files", "Registered evidence files", headers, rows)
        if rows
        else '<p class="muted">The controller registered no evidence files for this job.</p>'
    )
    note = ""
    if omitted:
        count = len(omitted)
        note = (
            f"<p>{count} trace archive{'s were' if count != 1 else ' was'} omitted from this "
            "export at the operator's request. Registered sizes and hashes remain listed above "
            "and in <code>job.json</code>; the files are not included.</p>"
        )
    trace_hint = (
        "<p>Playwright traces open with <code>npx playwright show-trace &lt;file&gt;.zip</code>."
        "</p>"
        if any(f.content is not None and f.extension == "zip" for f in evidence)
        else ""
    )
    verify = (
        '<div class="verify"><h3>Verify this replay</h3>'
        "<p>Before this replay was written, every included file was fetched from the controller "
        "and matched the size and SHA-256 registered when it was captured. From this directory, "
        "check that nothing has changed since export:</p>"
        "<pre><code>sha256sum -c SHA256SUMS</code></pre>"
        '<p><a href="SHA256SUMS">SHA256SUMS</a> covers this page, '
        '<a href="job.json">job.json</a> (the controller\'s job record, unedited), and every '
        f"included artifact.</p>{note}{trace_hint}</div>"
    )
    return table + verify


def render_page(detail: JsonMap, evidence: list[EvidenceFile], exported_at: datetime) -> str:
    """Render the static replay from recorded data only; every recorded value is escaped."""
    job = _map(detail.get("job"))
    attempts = [_map(a) for a in _list(detail.get("attempts"))]
    runs = [_map(x) for x in _list(detail.get("executions"))]
    events = [_map(x) for x in _list(detail.get("events"))]
    baseline_value = detail.get("baseline")
    baseline = _map(baseline_value) if isinstance(baseline_value, dict) else None
    if baseline is None:
        baseline = next((x for x in runs if x.get("phase") == "baseline"), None)
    latest = attempts[-1] if attempts else None
    verifications = [x for x in runs if x.get("phase") == "verification"]
    matching = [x for x in verifications if latest and x.get("attempt_id") == latest.get("id")]
    candidates = matching or verifications
    verification = candidates[-1] if candidates else None
    verified_attempt = next(
        (a for a in attempts if verification and a.get("id") == verification.get("attempt_id")),
        None,
    )
    evidence_verified = (
        verification is not None
        and baseline is not None
        and verification.get("runtime_kind") == "isolated-browser"
        and baseline.get("runtime_kind") == "isolated-browser"
    )
    verified = bool(
        evidence_verified
        and verification is not None
        and job.get("state") == "succeeded"
        and job.get("cleanup_status") == "succeeded"
        and job.get("outcome") == "verified"
        and _map(verification.get("report")).get("verdict") == "passed"
    )
    outcome_code = job.get("outcome")
    if outcome_code == "verified" and not evidence_verified:
        tone, title, summary = LEGACY_OUTCOME
    elif isinstance(outcome_code, str) and outcome_code in OUTCOME:
        tone, title, summary = OUTCOME[outcome_code]
    elif outcome_code is None:
        tone, title, summary = "warn", "No outcome recorded", "The job ended without an outcome."
    else:
        tone, title = "warn", _words(outcome_code).capitalize()
        summary = "The controller recorded an outcome this replay does not recognize."

    created, finished = _when(job.get("created_at")), _when(job.get("updated_at"))
    duration = (
        f"{(finished - created).total_seconds():.1f} s" if created and finished else "not recorded"
    )
    job_id = str(job.get("id", ""))
    mode = e(job.get("requested_mode", "not recorded"))
    if job.get("effective_mode") not in (None, job.get("requested_mode")):
        mode += f" → {e(job.get('effective_mode'))}"
    cleanup = job.get("cleanup_status")
    cleanup_tone = "ok" if cleanup == "succeeded" else "bad" if cleanup == "failed" else "warn"
    included = sum(1 for file in evidence if file.content is not None)
    facts = [
        ("Job", e(job_id)),
        ("Scenario", e(job.get("scenario_id", "not recorded"))),
        ("Created", _time(job.get("created_at"))),
        ("Finished", _time(job.get("updated_at"))),
        ("Duration", e(duration)),
        ("State", e(job.get("state"))),
        ("Cleanup", f'<span data-tone="{cleanup_tone}">{e(_words(cleanup))}</span>'),
        ("Mode", mode),
        ("Repair attempts", str(len(attempts))),
        ("Evidence files", f"{included} of {len(evidence)} included"),
    ]
    extra = ""
    if job.get("repair_block_reason"):
        reason = e(job["repair_block_reason"])
        extra += f'<p class="detail">Repair blocked: <code>{reason}</code></p>'
    if job.get("error_details"):
        detail_json = json.dumps(job["error_details"], ensure_ascii=False)
        extra += f'<p class="detail">Error detail: <code>{e(detail_json)}</code></p>'

    def shot(run: JsonMap | None) -> EvidenceFile | None:
        if run is None:
            return None
        shots = (f for f in evidence if f.artifact.get("role") == "screenshot")
        return next((f for f in shots if _belongs(f.artifact, run)), None)

    base_verdict = _map(baseline.get("report")).get("verdict") if baseline else None
    base_tone = (
        "idle"
        if baseline is None or base_verdict == "passed"
        else "bad"
        if base_verdict == "failed"
        else "warn"
    )
    after_verdict = _map(verification.get("report")).get("verdict") if verification else None
    after_tone = (
        "ok"
        if verified
        else "idle"
        if verification is None
        else "warn"
        if after_verdict == "passed"
        else "bad"
    )
    attempt_number = verified_attempt.get("attempt_number") if verified_attempt else None
    after_label = "After · verification" + (f", attempt {attempt_number}" if attempt_number else "")
    seam = (
        f'<div class="seam" data-verified="{"true" if verified else "false"}">'
        + _side(
            "Before · baseline run",
            baseline,
            base_tone,
            "No baseline run was recorded.",
            shot(baseline),
            "baseline",
        )
        + '<div class="seam-rule" aria-hidden="true"></div>'
        + _side(
            after_label,
            verification,
            after_tone,
            "No patched candidate was verified for this job.",
            shot(verification),
            "verification",
        )
        + "</div>"
    )
    patch = (
        "".join(_attempt(a, i) for i, a in enumerate(attempts))
        if attempts
        else '<p class="muted">No repair attempt was recorded, so no patch was proposed.</p>'
    )
    ordered_runs = [x for x in runs if x.get("phase") == "baseline"] + verifications
    stamp = exported_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    stamp_iso = exported_at.isoformat().replace("+00:00", "Z")
    runtime = _runtime_section(job, ordered_runs, attempts)
    files = _evidence_section(evidence, ordered_runs, attempts)
    sections = "".join(
        [
            _section(1, "seam", "Failure and verification", seam),
            _section(2, "patch", "Proposed patch", patch),
            _section(3, "assertions", "Assertions", _assertions(ordered_runs, attempts)),
            _section(4, "events", "Event timeline", _events(events, created)),
            _section(5, "runtime", "Runtime and cleanup", runtime),
            _section(6, "evidence", "Evidence files", files),
        ]
    )
    outcome_text = e(outcome_code if outcome_code is not None else "none")
    facts_html = "".join(f"<div><dt>{name}</dt><dd>{value}</dd></div>" for name, value in facts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="dark light">
<title>FaultLine replay · {e(title)} · job {e(job_id[:8])}</title>
<style>{STYLE}</style>
</head>
<body>
<a class="skip" href="#main">Skip to replay</a>
<header class="top"><div class="shell top-row">
<span class="wordmark"><span aria-hidden="true" class="glyph"></span>FaultLine</span>
<p class="tag">Read-only replay</p>
</div></header>
<main id="main" class="shell">
<section class="intro" aria-labelledby="title">
<p class="eyebrow">FaultLine replay · job {e(job_id)} · outcome \
<span data-tone="{tone}">{outcome_text}</span></p>
<h1 id="title">{e(title)}</h1>
<p class="lede">{e(summary)}</p>
{extra}
{_provider_banner(attempts)}
<dl class="facts" aria-label="Job record">{facts_html}</dl>
</section>
{sections}
</main>
<footer class="shell foot"><div>
<p><strong>A verified candidate is not a production deployment.</strong> \
This replay shows only what the local FaultLine controller recorded for this job \
and makes no claims beyond that record.</p>
<p>Replay exported <time datetime="{stamp_iso}">{stamp}</time> from the local controller. \
Static page: no scripts, no network requests.</p>
<p>FaultLine · Meta Global AI Developer Hackathon 2026 · Francis Bisignano</p>
</div></footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Command line


def default_api() -> str:
    inspector = os.environ.get("FAULTLINE_INSPECTOR_URL", DEFAULT_INSPECTOR)
    return inspector.rstrip("/") + "/api/faultline"


def main(argv: Sequence[str] | None = None, *, fetch: Fetch | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="export_replay.py",
        description="Export one finished FaultLine job as a static, checksummed replay.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job", metavar="JOB_ID", help="job id to export")
    target.add_argument("--latest", action="store_true", help="export the newest recorded job")
    parser.add_argument("--out", type=Path, help="output directory (default: replays/<job-id>)")
    parser.add_argument("--force", action="store_true", help="replace an earlier replay at --out")
    parser.add_argument(
        "--omit-traces",
        action="store_true",
        help="leave Playwright trace archives out (their hashes stay listed)",
    )
    parser.add_argument(
        "--api",
        help="controller API base reached through the Inspector proxy (default: "
        "$FAULTLINE_INSPECTOR_URL/api/faultline, else http://127.0.0.1:4000/api/faultline)",
    )
    args = parser.parse_args(argv)
    try:
        client = fetch or http_fetcher(args.api or default_api())
        job_id = _require_id(latest_job_id(client) if args.latest else args.job, "job id")
        out = args.out or ROOT / "replays" / job_id
        summary = export_replay(client, job_id, out, force=args.force, omit_traces=args.omit_traces)
    except ExportError as exc:
        print(f"export_replay: {exc}", file=sys.stderr)
        return 1
    print(f"Exported job {summary.job_id} (outcome: {summary.outcome}) to {summary.out}")
    print(f"  {len(summary.files)} files written; {len(summary.omitted)} trace(s) omitted")
    if summary.provider == "deterministic":
        print("  Deterministic fallback: this replay is not a Meta model trial.")
    print(f"  Verify: (cd {shlex.quote(str(summary.out))} && sha256sum -c SHA256SUMS)")
    print("  Review screenshots, traces, and logs for private data before publishing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
