#!/usr/bin/env python3
"""Run repeated FaultLine repair jobs and record what the controller measured.

The tool talks only to the Inspector's same-origin proxy, which adds the
controller credential server-side, so this process never handles a token. Every
per-trial value is copied or derived from the controller's recorded job
evidence. Values the controller did not record are null, never estimated.

Run from the repository root:

    uv run --project apps/buggyshop-backend --python 3.13 --locked \\
        python scripts/trial_ledger.py --trials 5 --require-provider meta \\
        --out data/trials/ledger.json

Exit status is 0 when every requested trial reached a recorded result, whatever
that result was, and 1 when readiness refused the run or a transport/protocol
error stopped it. A partial ledger marked ``"complete": false`` is still written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

SCHEMA_VERSION = "1.0"
TOOL_NAME = "scripts/trial_ledger.py"
SCENARIO_ID = "scripted_checkout_repair"
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
PROVIDERS = ("meta", "local", "openai-compatible", "deterministic")
MAX_TRIALS = 50
DEFAULT_TRIALS = 5
DEFAULT_DEADLINE_SECONDS = 190.0
REQUEST_TIMEOUT_SECONDS = 10.0
CANCEL_GRACE_SECONDS = 30.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
JOB_ID = re.compile(r"[\da-f-]{1,64}", re.IGNORECASE)
HUNK_HEADER = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


class LedgerError(Exception):
    """A transport or protocol failure that stops the run; the message is printable."""


@dataclass(frozen=True)
class ProxyClient:
    """JSON requests to the Inspector proxy, bypassing any environment HTTP proxy."""

    base_url: str
    timeout: float = REQUEST_TIMEOUT_SECONDS

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a decoded JSON object or raise LedgerError with a safe summary."""
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}/{path}", data=data, headers=headers, method=method)
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw: bytes = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            try:
                detail = _error_detail(exc.read(64 * 1024))
            except OSError:
                detail = "no readable error body"
            finally:
                exc.close()
            raise LedgerError(f"{method} {path} returned HTTP {exc.code}: {detail}") from None
        except URLError as exc:
            raise LedgerError(f"{method} {path} failed: {exc.reason}") from None
        except OSError as exc:
            raise LedgerError(f"{method} {path} failed: {exc}") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise LedgerError(f"{method} {path} response exceeded {MAX_RESPONSE_BYTES} bytes")
        try:
            value = json.loads(raw)
        except ValueError:
            raise LedgerError(f"{method} {path} returned a non-JSON response") from None
        if not isinstance(value, dict):
            raise LedgerError(f"{method} {path} returned JSON that is not an object")
        return value


def _error_detail(raw: bytes) -> str:
    """Prefer the controller's error code, then the proxy's message."""
    try:
        error = json.loads(raw).get("error")
    except (ValueError, AttributeError):
        return "no JSON error body"
    if isinstance(error, dict):
        for key in ("code", "message"):
            value = error.get(key)
            if isinstance(value, str) and value:
                return value[:200]
    return "no error code"


# Strict accessors: wrong JSON types become null rather than being coerced.
def _obj(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def utc_now() -> str:
    """Current UTC time as an RFC 3339 string with a Z suffix."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def changed_line_count(diff: str) -> int:
    """Count added plus removed lines inside unified-diff hunk ranges.

    Hunk line counts are honoured, so a removed line whose text begins with
    ``--`` is counted while file headers are not.
    """
    count = old = new = 0
    for line in diff.splitlines():
        if old > 0 or new > 0:
            marker = line[:1]
            if marker == "-":
                old, count = old - 1, count + 1
            elif marker == "+":
                new, count = new - 1, count + 1
            elif marker != "\\":
                old, new = old - 1, new - 1
            continue
        match = HUNK_HEADER.match(line)
        if match:
            old = int(match.group(1)) if match.group(1) is not None else 1
            new = int(match.group(2)) if match.group(2) is not None else 1
    return count


def readiness_snapshot(ready: dict[str, Any]) -> dict[str, Any]:
    """Keep the safe readiness fields; the controller exposes no secrets here."""
    model = _obj(ready.get("model"))
    return {
        "checked_at": utc_now(),
        "status": _str(ready.get("status")),
        "runtime_ready": _bool(ready.get("runtime_ready")),
        "quarantined": _bool(ready.get("quarantined")),
        "reason": _str(ready.get("reason")),
        "probe_time": ready.get("probe_time"),
        "provider": _str(model.get("provider")),
        "model": _str(model.get("model")),
        "available": _bool(model.get("available")),
        "model_reason": _str(model.get("reason")),
        "probe_prompt_tokens": _int(model.get("prompt_tokens")),
        "probe_completion_tokens": _int(model.get("completion_tokens")),
        "resource_limits": ready.get("resource_limits"),
    }


def safe_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The operator-facing readiness explanation printed on refusal."""
    return {
        "status": snapshot["status"],
        "reason": snapshot["reason"],
        "runtime_ready": snapshot["runtime_ready"],
        "quarantined": snapshot["quarantined"],
        "model": {
            "provider": snapshot["provider"],
            "model": snapshot["model"],
            "available": snapshot["available"],
            "reason": snapshot["model_reason"],
        },
    }


def refusal_reason(snapshot: dict[str, Any], require_provider: str | None) -> str | None:
    """Return why repair trials must not run, matching the rehearsal's readiness gate."""
    if snapshot["quarantined"] is not False:
        return f"runtime quarantined (reason: {snapshot['reason']})"
    if snapshot["runtime_ready"] is not True:
        return f"runtime not ready (reason: {snapshot['reason']})"
    if snapshot["available"] is not True:
        return (
            f"model unavailable (provider: {snapshot['provider']}, "
            f"reason: {snapshot['model_reason']})"
        )
    if require_provider is not None and snapshot["provider"] != require_provider:
        return (
            f"readiness reports provider {snapshot['provider']!r}, "
            f"but {require_provider!r} is required"
        )
    return None


@dataclass
class TrialProgress:
    """What one trial has observed so far, kept so a stopped run keeps partial evidence."""

    number: int
    idempotency_key: str
    job_id: str | None = None
    detail: dict[str, Any] | None = None
    deadline_exceeded: bool = False
    cancel_requested: bool = False
    last_status: tuple[object, object, object] | None = None


def run_trial(
    client: ProxyClient,
    progress: TrialProgress,
    *,
    deadline: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    poll_interval: float,
    cancel_grace: float,
) -> None:
    """Submit one repair job and poll until it is terminal, cancelling at the deadline."""
    created = client.request(
        "POST",
        "jobs",
        {
            "scenario_id": SCENARIO_ID,
            "mode": "repair",
            "idempotency_key": progress.idempotency_key,
        },
    )
    job_id = created.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise LedgerError("POST jobs response did not include a valid job_id")
    progress.job_id = job_id
    started = clock()
    while True:
        if _poll(client, progress):
            return
        if clock() - started >= deadline:
            break
        sleep(poll_interval)
    progress.deadline_exceeded = True
    print(
        f"Trial {progress.number}: job {job_id} exceeded the {deadline:g}s deadline; "
        "requesting cancellation.",
        file=sys.stderr,
    )
    client.request("POST", f"jobs/{job_id}/cancel")
    progress.cancel_requested = True
    grace_end = clock() + cancel_grace
    while clock() < grace_end:
        sleep(poll_interval)
        if _poll(client, progress):
            return
    raise LedgerError(
        f"job {job_id} did not reach a terminal state within {cancel_grace:g}s of cancellation"
    )


def _poll(client: ProxyClient, progress: TrialProgress) -> bool:
    """Fetch the job detail, report state changes, and say whether it is terminal."""
    detail = client.request("GET", f"jobs/{progress.job_id}")
    job = detail.get("job")
    if not isinstance(job, dict):
        raise LedgerError(f"GET jobs/{progress.job_id} response did not include a job object")
    progress.detail = detail
    status = (job.get("state"), job.get("stage"), job.get("outcome"))
    if status != progress.last_status:
        progress.last_status = status
        print(f"Trial {progress.number}: {status[0]} / {status[1]} / {status[2] or 'pending'}")
    return job.get("state") in TERMINAL_STATES


def attempt_record(attempt: dict[str, Any]) -> dict[str, Any]:
    """One repair attempt: identity, usage, policy result, and diff fingerprint."""
    validation = _obj(attempt.get("validation_result"))
    diff = _str(attempt.get("parsed_diff"))
    return {
        "attempt_id": _str(attempt.get("id")),
        "attempt_number": _int(attempt.get("attempt_number")),
        "outcome": _str(attempt.get("outcome")),
        # provider/model are set only by a returned response; dispatch is separate.
        "provider": _str(validation.get("provider")),
        "model": _str(validation.get("model")),
        "dispatched_provider": _str(validation.get("dispatched_provider")),
        "dispatched_model": _str(validation.get("dispatched_model")),
        "prompt_tokens": _int(attempt.get("prompt_tokens")),
        "completion_tokens": _int(attempt.get("completion_tokens")),
        "policy_valid": _bool(validation.get("is_valid")),
        "policy_error": _str(validation.get("error_message")),
        "diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff is not None else None,
        "diff_changed_lines": changed_line_count(diff) if diff is not None else None,
        "prior_feedback": validation.get("prior_feedback"),
    }


def execution_record(execution: dict[str, Any]) -> dict[str, Any]:
    """One verification execution: verdict, assertion counts, and runtime identity."""
    report = _obj(execution.get("report"))
    assertions = report.get("assertions")
    checks = [_obj(item) for item in assertions] if isinstance(assertions, list) else None
    limits = execution.get("resource_limits", report.get("resource_limits"))
    return {
        "execution_id": _str(report.get("execution_id")),
        "attempt_id": _str(execution.get("attempt_id")),
        "verdict": _str(report.get("verdict")),
        "assertions_passed": None
        if checks is None
        else sum(1 for item in checks if item.get("passed") is True),
        "assertions_total": None if checks is None else len(checks),
        "runtime_kind": _str(execution.get("runtime_kind")),
        "resource_limits": limits,
    }


def trial_record(progress: TrialProgress) -> dict[str, Any]:
    """Derive the ledger entry for one trial from the last recorded job detail."""
    detail = progress.detail
    evidence = _obj(detail)
    job = _obj(evidence.get("job"))
    error = _obj(job.get("error_details"))
    baseline_verdict = _str(_obj(_obj(evidence.get("baseline")).get("report")).get("verdict"))
    raw_attempts = evidence.get("attempts")
    raw_executions = evidence.get("executions")
    raw_artifacts = evidence.get("artifacts")
    attempts = [attempt_record(_obj(item)) for item in _list(raw_attempts)]
    executions = [
        execution_record(item)
        for item in map(_obj, _list(raw_executions))
        if item.get("phase") == "verification"
    ]
    artifacts = [
        {
            "role": _str(item.get("role")),
            "sha256": _str(item.get("sha256")),
            "size_bytes": _int(item.get("size_bytes")),
        }
        for item in map(_obj, _list(raw_artifacts))
    ]
    state = _str(job.get("state"))
    terminal = state in TERMINAL_STATES
    created, updated = _timestamp(job.get("created_at")), _timestamp(job.get("updated_at"))
    wall = (
        round((updated - created).total_seconds(), 3)
        if terminal and created is not None and updated is not None
        else None
    )
    record: dict[str, Any] = {
        "trial": progress.number,
        "idempotency_key": progress.idempotency_key,
        "job_id": progress.job_id,
        "evidence_recorded": detail is not None,
        "scenario_id": _str(job.get("scenario_id")),
        "requested_mode": _str(job.get("requested_mode")),
        "effective_mode": _str(job.get("effective_mode")),
        "repair_block_reason": _str(job.get("repair_block_reason")),
        "created_at": _str(job.get("created_at")),
        "updated_at": _str(job.get("updated_at")),
        "wall_seconds": wall,
        "terminal": terminal,
        "state": state,
        "stage": _str(job.get("stage")),
        "outcome": _str(job.get("outcome")),
        "cleanup_status": _str(job.get("cleanup_status")),
        "error_code": _str(error.get("code")),
        "failed_stage": _str(error.get("failed_stage")),
        "deadline_exceeded": progress.deadline_exceeded,
        "cancel_requested_by_ledger": progress.cancel_requested,
        "baseline_verdict": baseline_verdict,
        "expected_failure_reproduced": None
        if baseline_verdict is None
        else baseline_verdict == "failed",
        "attempts": attempts,
        "verification_executions": executions,
        "artifact_count": len(artifacts) if isinstance(raw_artifacts, list) else None,
        "artifacts": artifacts,
    }
    record["verified"] = is_verified(record)
    return record


def is_verified(record: dict[str, Any]) -> bool:
    """The rehearsal script's rule: measured success plus confirmed cleanup."""
    return (
        record["state"] == "succeeded"
        and record["outcome"] == "verified"
        and record["cleanup_status"] == "succeeded"
        and record["baseline_verdict"] == "failed"
        and any(
            item["verdict"] == "passed"
            and (item["assertions_total"] or 0) > 0
            and item["assertions_passed"] == item["assertions_total"]
            for item in record["verification_executions"]
        )
    )


def provider_counts(trials: list[dict[str, Any]]) -> dict[str, int]:
    """Attempts per responding provider; attempts without a response count as ``no_response``."""
    counts = Counter(
        attempt["provider"] or "no_response" for trial in trials for attempt in trial["attempts"]
    )
    return dict(sorted(counts.items()))


def classify(trials: list[dict[str, Any]]) -> tuple[str, str]:
    """Label the series by the provider that actually answered each attempt.

    The controller records provider/model only from a returned response, so an
    attempt that ended in a provider error can never be counted as inference.
    """
    attempts = [attempt for trial in trials for attempt in trial["attempts"]]
    if not attempts:
        return (
            "no_recorded_attempts",
            "No repair attempts were recorded, so no generated patch was evaluated.",
        )
    answered = [attempt["provider"] for attempt in attempts if attempt["provider"]]
    silent = len(attempts) - len(answered)
    if not answered:
        return (
            "no_model_response",
            f"None of the {len(attempts)} recorded attempts received a provider response, so "
            "no generated patch can be attributed to a model.",
        )
    if len(set(answered)) > 1:
        counts = ", ".join(f"{name}: {count}" for name, count in provider_counts(trials).items())
        return (
            "mixed",
            f"Responses came from more than one provider identity ({counts}). Report results "
            "per provider; do not describe the series as single-provider trials.",
        )
    provider, count = answered[0], len(answered)
    caveat = (
        f" {silent} other attempt(s) ended without a provider response and are not counted "
        "as model output."
        if silent
        else ""
    )
    if provider == "meta":
        return (
            "meta_model_trials",
            f"All {count} provider responses came from provider meta. These are live Meta "
            f"model trials on one controlled scenario.{caveat}",
        )
    if provider == "deterministic":
        return (
            "deterministic_workflow_rehearsals",
            f"All {count} recorded proposals came from provider deterministic. Deterministic "
            "workflow rehearsal: not a Meta model trial. The built-in deterministic generator "
            f"produced every proposal.{caveat}",
        )
    if provider == "local":
        return (
            "local_model_trials",
            f"All {count} provider responses came from provider local, a loopback model "
            f"endpoint. These are local model trials, not Meta model trials.{caveat}",
        )
    return (
        "openai_compatible_trials",
        f"All {count} provider responses came from provider {provider}, an OpenAI-compatible "
        f"endpoint that is not a Meta-operated host. These are not Meta model trials.{caveat}",
    )


def _markdown_classification(classification: str, note: str) -> str:
    """Deterministic summaries never mention a model vendor; the JSON note keeps the caveat."""
    if classification == "deterministic_workflow_rehearsals":
        return (
            "Every recorded attempt reports provider deterministic. These are deterministic "
            "workflow rehearsals: the built-in deterministic generator produced every proposal, "
            "and no language model was called."
        )
    return note


def _distribution(values: list[float]) -> dict[str, Any]:
    """Median and nearest-rank p95 over known values; nulls when nothing is known."""
    ordered = sorted(values)
    if not ordered:
        return {"known_count": 0, "median": None, "p95": None, "min": None, "max": None}
    return {
        "known_count": len(ordered),
        "median": round(statistics.median(ordered), 3),
        "p95": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "min": ordered[0],
        "max": ordered[-1],
    }


def _token_total(attempts: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Sum usage only when every attempt recorded it; otherwise the total is null."""
    values = [attempt[key] for attempt in attempts]
    known = [value for value in values if value is not None]
    return {
        "attempt_count": len(values),
        "known_count": len(known),
        "total": sum(known) if len(known) == len(values) else None,
    }


def summarize(trials: list[dict[str, Any]], requested: int) -> dict[str, Any]:
    """Aggregate counts, rates, latency, and usage from the per-trial records."""
    attempts = [attempt for trial in trials for attempt in trial["attempts"]]
    verified = [trial for trial in trials if trial["verified"]]
    verified_numbers = Counter(
        attempt["attempt_number"]
        for trial in verified
        for attempt in trial["attempts"]
        if attempt["outcome"] == "verified"
    )
    pairs = sorted(
        {(attempt["provider"], attempt["model"]) for attempt in attempts},
        key=lambda pair: (pair[0] or "", pair[1] or ""),
    )
    return {
        "trials_requested": requested,
        "trials_run": len(trials),
        "outcome_counts": dict(
            sorted(Counter(trial["outcome"] or "unrecorded" for trial in trials).items())
        ),
        "verified_count": len(verified),
        "verified_rate": round(len(verified) / len(trials), 4) if trials else None,
        "verified_on_first_attempt": verified_numbers[1],
        "verified_on_second_attempt": verified_numbers[2],
        "cleanup_confirmed_count": sum(
            1 for trial in trials if trial["cleanup_status"] == "succeeded"
        ),
        "expected_failure_reproduced_count": sum(
            1 for trial in trials if trial["expected_failure_reproduced"] is True
        ),
        "deadline_exceeded_count": sum(1 for trial in trials if trial["deadline_exceeded"]),
        "attempts_total": len(attempts),
        "policy_rejected_attempts": sum(
            1 for attempt in attempts if attempt["policy_valid"] is False
        ),
        "wall_seconds": _distribution(
            [trial["wall_seconds"] for trial in trials if trial["wall_seconds"] is not None]
        ),
        "prompt_tokens": _token_total(attempts, "prompt_tokens"),
        "completion_tokens": _token_total(attempts, "completion_tokens"),
        "provider_models": [{"provider": provider, "model": model} for provider, model in pairs],
    }


@dataclass
class RunState:
    """Everything the ledger reports; rewritten to disk after each trial."""

    config: dict[str, Any]
    started_at: str
    readiness: dict[str, Any] | None = None
    stop_readiness: dict[str, Any] | None = None
    trials: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = False
    stop_reason: str | None = None


def build_ledger(state: RunState) -> dict[str, Any]:
    """Assemble the versioned JSON ledger."""
    classification, note = classify(state.trials)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "generated_at": utc_now(),
        "started_at": state.started_at,
        "complete": state.complete,
        "stop_reason": state.stop_reason,
        "classification": classification,
        "classification_note": note,
        "provider_counts": provider_counts(state.trials),
        "config": state.config,
        "readiness": state.readiness,
        "stop_readiness": state.stop_readiness,
        "summary": summarize(state.trials, state.config["trials_requested"]),
        "trials": state.trials,
    }


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _tokens_cell(attempts: list[dict[str, Any]]) -> str:
    if not attempts:
        return "none"
    prompt = _token_total(attempts, "prompt_tokens")["total"]
    completion = _token_total(attempts, "completion_tokens")["total"]
    if prompt is None or completion is None:
        return "unrecorded"
    return f"{prompt}+{completion}"


def _usage_line(usage: dict[str, Any]) -> str:
    known = f"{usage['known_count']} of {usage['attempt_count']} attempts recorded"
    total = "unknown" if usage["total"] is None else str(usage["total"])
    return f"{total} ({known})"


def _seconds(value: object) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def render_markdown(ledger: dict[str, Any], json_name: str) -> str:
    """A concise factual summary of the ledger; the JSON remains authoritative."""
    summary = ledger["summary"]
    lines = [
        "# FaultLine trial ledger",
        "",
        f"Generated {ledger['generated_at']} by `{TOOL_NAME}` from controller job records. "
        f"Full ledger: `{json_name}` (schema {SCHEMA_VERSION}).",
        "",
        "Status: complete."
        if ledger["complete"]
        else f"Status: incomplete. Stop reason: {_cell(ledger['stop_reason']).rstrip('.')}.",
        "",
        f"Classification: `{ledger['classification']}`. "
        + _markdown_classification(ledger["classification"], ledger["classification_note"]),
        "",
    ]
    ready = ledger["readiness"]
    if ready is None:
        lines.append("Readiness was not recorded.")
    else:
        lines.append(
            f"Readiness at start: status `{ready['status']}`, provider `{ready['provider']}`, "
            f"model `{ready['model']}`, probe time {ready['probe_time']}."
        )
    lines += [
        "",
        "| Trial | Job | Outcome | Verified | Attempts | Wall s | Assertions "
        "| Tokens (prompt+completion) | Cleanup |",
        "| ---: | --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for trial in ledger["trials"]:
        outcome = trial["outcome"] or trial["state"] or "unrecorded"
        if trial["deadline_exceeded"]:
            outcome += " (deadline exceeded)"
        assertions = ", ".join(
            f"{item['assertions_passed']}/{item['assertions_total']}"
            for item in trial["verification_executions"]
        )
        cells = [
            trial["trial"],
            (trial["job_id"] or "none")[:8],
            outcome,
            "yes" if trial["verified"] else "no",
            len(trial["attempts"]),
            _seconds(trial["wall_seconds"]),
            assertions or "none",
            _tokens_cell(trial["attempts"]),
            trial["cleanup_status"] or "unrecorded",
        ]
        lines.append("| " + " | ".join(_cell(value) for value in cells) + " |")
    wall = summary["wall_seconds"]
    rate = summary["verified_rate"]
    outcomes = ", ".join(f"{name} {count}" for name, count in summary["outcome_counts"].items())
    pairs = ", ".join(
        f"`{pair['provider']}` / `{pair['model']}`" for pair in summary["provider_models"]
    )
    rows = [
        ("Trials run", f"{summary['trials_run']} of {summary['trials_requested']} requested"),
        (
            "Verified",
            f"{summary['verified_count']}" + ("" if rate is None else f" ({rate:.0%})"),
        ),
        (
            "Verified on attempt 1 / attempt 2",
            f"{summary['verified_on_first_attempt']} / {summary['verified_on_second_attempt']}",
        ),
        ("Outcomes", outcomes or "none"),
        ("Expected failure reproduced", summary["expected_failure_reproduced_count"]),
        ("Cleanup confirmed", summary["cleanup_confirmed_count"]),
        ("Deadline exceeded", summary["deadline_exceeded_count"]),
        (
            "Attempts (policy rejected)",
            f"{summary['attempts_total']} ({summary['policy_rejected_attempts']})",
        ),
        (
            "Wall s median / p95 / min / max",
            " / ".join(_seconds(wall[key]) for key in ("median", "p95", "min", "max"))
            + f" ({wall['known_count']} known)",
        ),
        ("Prompt tokens", _usage_line(summary["prompt_tokens"])),
        ("Completion tokens", _usage_line(summary["completion_tokens"])),
        ("Provider / model", pairs or "none recorded"),
    ]
    lines += ["", "## Summary", "", "| Measure | Value |", "| --- | --- |"]
    lines += [f"| {_cell(name)} | {_cell(value)} |" for name, value in rows]
    lines += [
        "",
        f"Scope: one registered scenario (`{SCENARIO_ID}`); results do not measure other "
        "defects. Wall time is the controller-recorded interval from job creation to its final "
        "update. p95 uses the nearest-rank method. Token totals appear only when every attempt "
        "recorded usage.",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_outputs(path: Path, ledger: dict[str, Any]) -> Path:
    """Write the JSON ledger and its sibling Markdown summary; return the summary path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_path = path.with_suffix(".md")
    _atomic_write(path, json.dumps(ledger, indent=2) + "\n")
    _atomic_write(summary_path, render_markdown(ledger, path.name))
    return summary_path


@dataclass(frozen=True)
class Options:
    """Validated command-line options."""

    trials: int
    out: Path
    deadline: float
    require_provider: str | None
    api: str


def _trial_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if not 1 <= count <= MAX_TRIALS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_TRIALS}")
    return count


def _deadline(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number of seconds") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return seconds


def _ledger_path(value: str) -> Path:
    path = Path(value)
    if path.suffix != ".json":
        raise argparse.ArgumentTypeError("must end in .json (a sibling .md is also written)")
    return path


def _api_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise argparse.ArgumentTypeError("must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("must not contain credentials, a query, or a fragment")
    return value.rstrip("/")


def parse_args(argv: Sequence[str] | None) -> Options:
    """Parse and validate the command line."""
    inspector = os.environ.get("FAULTLINE_INSPECTOR_URL") or "http://127.0.0.1:4000"
    parser = argparse.ArgumentParser(
        prog="trial_ledger.py",
        description="Run repeated repair jobs through the Inspector proxy and record a ledger "
        "of what the controller measured.",
    )
    parser.add_argument(
        "--trials",
        type=_trial_count,
        default=DEFAULT_TRIALS,
        help=f"sequential jobs to run, 1-{MAX_TRIALS} (default {DEFAULT_TRIALS})",
    )
    parser.add_argument(
        "--out",
        type=_ledger_path,
        required=True,
        help="JSON ledger path; a sibling .md summary is written next to it",
    )
    parser.add_argument(
        "--deadline",
        type=_deadline,
        default=DEFAULT_DEADLINE_SECONDS,
        help=f"per-job seconds before cancellation (default {DEFAULT_DEADLINE_SECONDS:g})",
    )
    parser.add_argument(
        "--require-provider",
        choices=PROVIDERS,
        help="refuse to start unless readiness reports this provider",
    )
    parser.add_argument(
        "--api",
        type=_api_url,
        default=inspector.rstrip("/") + "/api/faultline",
        help="Inspector proxy API base (default: $FAULTLINE_INSPECTOR_URL/api/faultline)",
    )
    args = parser.parse_args(argv)
    return Options(args.trials, args.out, args.deadline, args.require_provider, args.api)


def _stop(state: RunState, reason: str) -> int:
    state.stop_reason = reason
    print(f"Stopped: {reason}", file=sys.stderr)
    return 1


def _refuse(state: RunState, snapshot: dict[str, Any], reason: str) -> int:
    print("Repair unavailable; not recording trials. Readiness:", file=sys.stderr)
    print(json.dumps(safe_summary(snapshot), indent=2), file=sys.stderr)
    return _stop(state, reason)


def execute(
    options: Options,
    client: ProxyClient,
    state: RunState,
    *,
    save: Callable[[], object],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    poll_interval: float,
    cancel_grace: float,
) -> int:
    """Check readiness, then run trials sequentially, stopping on refusal or error."""
    try:
        state.readiness = readiness_snapshot(client.request("GET", "readiness"))
    except LedgerError as exc:
        return _stop(state, f"readiness check failed: {exc}")
    refusal = refusal_reason(state.readiness, options.require_provider)
    if refusal is not None:
        return _refuse(state, state.readiness, f"readiness refused: {refusal}")
    print(
        f"Recording {options.trials} trial(s) with provider={state.readiness['provider']} "
        f"model={state.readiness['model']}"
    )
    if state.readiness["provider"] == "deterministic":
        print("Deterministic rehearsal: this is not a live Meta model trial.")
    save()
    for number in range(1, options.trials + 1):
        if number > 1:
            try:
                snapshot = readiness_snapshot(client.request("GET", "readiness"))
            except LedgerError as exc:
                return _stop(state, f"readiness check before trial {number} failed: {exc}")
            refusal = refusal_reason(snapshot, options.require_provider)
            if refusal is not None:
                state.stop_readiness = snapshot
                return _refuse(state, snapshot, f"stopped before trial {number}: {refusal}")
        progress = TrialProgress(number, str(uuid.uuid4()))
        try:
            run_trial(
                client,
                progress,
                deadline=options.deadline,
                sleep=sleep,
                clock=clock,
                poll_interval=poll_interval,
                cancel_grace=cancel_grace,
            )
        except (LedgerError, KeyboardInterrupt) as exc:
            if progress.job_id is not None:
                state.trials.append(trial_record(progress))
            if isinstance(exc, KeyboardInterrupt):
                return _stop(
                    state,
                    f"operator interrupted trial {number}; job {progress.job_id} may still "
                    "be running (cancel it in the Inspector)",
                )
            return _stop(state, f"trial {number}: {exc}")
        state.trials.append(trial_record(progress))
        save()
    state.complete = True
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    poll_interval: float = 1.0,
    cancel_grace: float = CANCEL_GRACE_SECONDS,
) -> int:
    """Run the ledger; see the module docstring for exit codes."""
    options = parse_args(argv)
    state = RunState(
        config={
            "api": options.api,
            "scenario_id": SCENARIO_ID,
            "mode": "repair",
            "trials_requested": options.trials,
            "deadline_seconds": options.deadline,
            "cancel_grace_seconds": cancel_grace,
            "require_provider": options.require_provider,
        },
        started_at=utc_now(),
    )

    def save() -> Path:
        return write_outputs(options.out, build_ledger(state))

    try:
        save()
    except OSError as exc:
        print(f"Cannot write ledger to {options.out}: {exc}", file=sys.stderr)
        return 1
    status = execute(
        options,
        ProxyClient(options.api),
        state,
        save=save,
        sleep=sleep,
        clock=clock,
        poll_interval=poll_interval,
        cancel_grace=cancel_grace,
    )
    summary_path = save()
    classification, _ = classify(state.trials)
    print(
        f"Wrote {options.out} and {summary_path}: {len(state.trials)} of {options.trials} "
        f"trial(s) recorded, complete={str(state.complete).lower()}, "
        f"classification={classification}."
    )
    return status


if __name__ == "__main__":
    sys.exit(main())
