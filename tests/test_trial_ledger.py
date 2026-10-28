"""The trial ledger must report only what the controller recorded, labeled honestly."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import socket
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "trial_ledger.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("faultline_trial_ledger", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ledger_tool = _load()

JOB_1 = "00000000-0000-4000-8000-000000000001"
JOB_2 = "00000000-0000-4000-8000-000000000002"
CREATED = "2026-10-27T12:00:00Z"
UPDATED = "2026-10-27T12:00:42.500000Z"
DIFF = (
    "--- a/apps/buggyshop-backend/app/main.py\n"
    "+++ b/apps/buggyshop-backend/app/main.py\n"
    "@@ -40,3 +40,3 @@\n"
    " def total(subtotal, coupon):\n"
    "-    discount = coupon_value(coupon)\n"
    "+    discount = coupon_value(coupon) or 0\n"
    "     return subtotal - discount\n"
)


def ready(
    provider: str = "meta",
    model: str = "muse-spark-1.3",
    *,
    available: bool = True,
    runtime_ready: bool = True,
    quarantined: bool = False,
    model_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "blocked" if quarantined or not runtime_ready else "ready",
        "runtime_ready": runtime_ready,
        "quarantined": quarantined,
        "model": {
            "available": available,
            "provider": provider,
            "model": model,
            "reason": model_reason,
            "prompt_tokens": None,
            "completion_tokens": None,
        },
        "probe_time": "2026-10-27T11:59:00Z",
        "reason": "cleanup_required" if quarantined else None,
    }


def attempt(
    number: int,
    *,
    provider: str | None = "meta",
    model: str | None = "muse-spark-1.3",
    outcome: str | None = "verified",
    prompt: int | None = 1200,
    completion: int | None = 300,
    valid: bool = True,
    error: str | None = None,
    diff: str | None = DIFF,
    prior_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation: dict[str, Any] = {
        "is_valid": valid,
        "target_file": "apps/buggyshop-backend/app/main.py",
        "syntax_valid": valid,
        "error_message": error,
        "ast_safe": valid,
    }
    if provider is not None:
        validation |= {"provider": provider, "model": model}
    if prior_feedback is not None:
        validation["prior_feedback"] = prior_feedback
    return {
        "id": f"attempt-{number}",
        "job_id": JOB_1,
        "attempt_number": number,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "raw_patch": None,
        "parsed_diff": diff,
        "validation_result": validation,
        "outcome": outcome,
    }


def execution(
    phase: str,
    verdict: str,
    passed: int,
    total: int,
    *,
    attempt_id: str | None = None,
    resource_limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "phase": phase,
        "attempt_id": attempt_id,
        "runtime_kind": "isolated-browser",
        "candidate_snapshot_sha256": "0" * 64,
        "artifact_ids": [],
        "report": {
            "execution_id": f"{phase}-{attempt_id}",
            "verdict": verdict,
            "assertions": [{"id": f"a{i}", "passed": i < passed} for i in range(total)],
        },
    }
    if resource_limits is not None:
        record["resource_limits"] = resource_limits
    return record


def detail(
    job_id: str = JOB_1,
    *,
    state: str = "succeeded",
    stage: str = "completed",
    outcome: str | None = "verified",
    cleanup: str = "succeeded",
    baseline: str | None = "failed",
    attempts: list[dict[str, Any]] | None = None,
    verifications: list[dict[str, Any]] | None = None,
    error_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if attempts is None:
        attempts = [attempt(1)]
    if verifications is None:
        verifications = [execution("verification", "passed", 44, 44, attempt_id="attempt-1")]
    baseline_record = None if baseline is None else execution("baseline", baseline, 40, 44)
    return {
        "job": {
            "id": job_id,
            "scenario_id": "scripted_checkout_repair",
            "state": state,
            "stage": stage,
            "outcome": outcome,
            "cleanup_status": cleanup,
            "created_at": CREATED,
            "updated_at": UPDATED,
            "error_details": error_details,
            "requested_mode": "repair",
            "effective_mode": "repair",
            "repair_block_reason": None,
            "cancel_requested": False,
        },
        "baseline": baseline_record,
        "attempts": attempts,
        "executions": ([baseline_record] if baseline_record else []) + verifications,
        "artifacts": [
            {"role": "screenshot", "sha256": "a" * 64, "size_bytes": 2048, "id": "x"},
            {"role": "diff", "sha256": "b" * 64, "size_bytes": 120, "id": "y"},
        ],
        "events": [],
    }


def running(job_id: str = JOB_1) -> dict[str, Any]:
    return detail(
        job_id,
        state="running",
        stage="diagnosing",
        outcome=None,
        cleanup="not_started",
        attempts=[],
        verifications=[],
    )


@dataclass
class JobPlan:
    """Successive job details for one submitted job; the last one repeats."""

    job_id: str
    details: list[dict[str, Any]]
    after_cancel: dict[str, Any] | None = None
    status: int = 200
    cancelled: bool = False
    polls: int = 0

    def next_detail(self) -> tuple[int, dict[str, Any]]:
        if self.status != 200:
            return self.status, {"error": {"message": "Controller unavailable."}}
        if self.cancelled and self.after_cancel is not None:
            return 200, self.after_cancel
        index = min(self.polls, len(self.details) - 1)
        self.polls += 1
        return 200, self.details[index]


@dataclass
class FakeProxy:
    """In-process stand-in for the Inspector's /api/faultline proxy."""

    readiness: list[dict[str, Any]] = field(default_factory=lambda: [ready()])
    plans: list[JobPlan] = field(default_factory=list)
    requests: list[tuple[str, str, Any]] = field(default_factory=list)
    readiness_calls: int = 0
    jobs: dict[str, JobPlan] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def handle(self, method: str, path: str, body: Any) -> tuple[int, dict[str, Any]]:
        with self.lock:
            self.requests.append((method, path, body))
            if (method, path) == ("GET", "/api/faultline/readiness"):
                index = min(self.readiness_calls, len(self.readiness) - 1)
                self.readiness_calls += 1
                return 200, self.readiness[index]
            if (method, path) == ("POST", "/api/faultline/jobs"):
                plan = self.plans[len(self.jobs)]
                self.jobs[plan.job_id] = plan
                return 202, {"job_id": plan.job_id, "state": "queued"}
            match = re.fullmatch(r"/api/faultline/jobs/([\da-f-]+)(/cancel)?", path)
            if match and match.group(1) in self.jobs:
                plan = self.jobs[match.group(1)]
                if match.group(2) and method == "POST":
                    plan.cancelled = True
                    return 202, {"id": plan.job_id, "cancel_requested": True}
                if method == "GET":
                    return plan.next_detail()
            return 404, {"error": {"message": "Unknown controller route."}}

    def paths(self, method: str) -> list[str]:
        return [path for verb, path, _ in self.requests if verb == method]


class Handler(BaseHTTPRequestHandler):
    fake: FakeProxy

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        status, payload = self.fake.handle(self.command, self.path, body)
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _respond
    do_POST = _respond

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def proxy() -> Iterator[tuple[FakeProxy, str]]:
    fake = FakeProxy()
    handler = type("BoundHandler", (Handler,), {"fake": fake})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield fake, f"http://127.0.0.1:{server.server_address[1]}/api/faultline"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run(api: str, out: Path, *extra: str, cancel_grace: float = 1.0) -> int:
    status: int = ledger_tool.main(
        ["--api", api, "--out", str(out), *extra],
        poll_interval=0.01,
        cancel_grace=cancel_grace,
    )
    return status


def read(out: Path) -> tuple[dict[str, Any], str]:
    return json.loads(out.read_text()), out.with_suffix(".md").read_text()


def test_verified_trial_is_recorded_from_controller_evidence(
    proxy: tuple[FakeProxy, str], tmp_path: Path
) -> None:
    fake, api = proxy
    limits = {"memory_bytes": 536870912, "processes": 64}
    fake.plans = [
        JobPlan(
            JOB_1,
            [
                running(),
                detail(
                    verifications=[
                        execution(
                            "verification",
                            "passed",
                            44,
                            44,
                            attempt_id="attempt-1",
                            resource_limits=limits,
                        )
                    ]
                ),
            ],
        )
    ]
    out = tmp_path / "ledger.json"
    assert run(api, out, "--trials", "1", "--require-provider", "meta") == 0
    ledger, markdown = read(out)

    submitted = [body for verb, path, body in fake.requests if path == "/api/faultline/jobs"]
    assert submitted[0]["scenario_id"] == "scripted_checkout_repair"
    assert submitted[0]["mode"] == "repair"
    assert uuid.UUID(submitted[0]["idempotency_key"]).version == 4

    assert ledger["schema_version"] == "1.0"
    assert ledger["tool"] == "scripts/trial_ledger.py"
    assert ledger["generated_at"].endswith("Z")
    assert ledger["complete"] is True and ledger["stop_reason"] is None
    assert ledger["classification"] == "meta_model_trials"
    assert ledger["readiness"]["provider"] == "meta"
    assert ledger["readiness"]["probe_time"] == "2026-10-27T11:59:00Z"
    assert ledger["readiness"]["resource_limits"] is None

    trial = ledger["trials"][0]
    assert trial["job_id"] == JOB_1
    assert trial["verified"] is True
    assert trial["wall_seconds"] == 42.5
    assert trial["baseline_verdict"] == "failed"
    assert trial["expected_failure_reproduced"] is True
    assert trial["deadline_exceeded"] is False
    assert trial["artifact_count"] == 2
    assert trial["artifacts"][0] == {"role": "screenshot", "sha256": "a" * 64, "size_bytes": 2048}
    first = trial["attempts"][0]
    assert first["provider"] == "meta" and first["model"] == "muse-spark-1.3"
    assert first["policy_valid"] is True and first["policy_error"] is None
    assert first["diff_sha256"] == hashlib.sha256(DIFF.encode()).hexdigest()
    assert first["diff_changed_lines"] == 2
    assert first["prior_feedback"] is None
    check = trial["verification_executions"][0]
    assert (check["assertions_passed"], check["assertions_total"]) == (44, 44)
    assert check["runtime_kind"] == "isolated-browser"
    assert check["resource_limits"] == limits

    summary = ledger["summary"]
    assert summary["verified_count"] == 1 and summary["verified_rate"] == 1.0
    assert summary["verified_on_first_attempt"] == 1
    assert summary["cleanup_confirmed_count"] == 1
    assert summary["prompt_tokens"] == {"attempt_count": 1, "known_count": 1, "total": 1200}
    assert summary["completion_tokens"]["total"] == 300
    assert summary["wall_seconds"]["median"] == 42.5
    assert summary["provider_models"] == [{"provider": "meta", "model": "muse-spark-1.3"}]
    assert "live Meta model trials" in markdown
    assert "| 1 | 00000000 | verified | yes | 1 | 42.5 | 44/44 | 1200+300 | succeeded |" in (
        markdown
    )
    assert "/api/faultline/reset" not in fake.paths("POST")


def test_unresolved_trial_keeps_both_attempts_and_feedback(
    proxy: tuple[FakeProxy, str], tmp_path: Path
) -> None:
    fake, api = proxy
    feedback = {"gate": "patch_policy_rejected", "failed_check_count": 0}
    fake.plans = [
        JobPlan(
            JOB_1,
            [
                detail(
                    state="failed",
                    outcome="unresolved",
                    attempts=[
                        attempt(
                            1,
                            outcome="patch_policy_rejected",
                            valid=False,
                            error="import of os is not allowed",
                        ),
                        attempt(
                            2,
                            outcome="verification_failed",
                            prompt=None,
                            completion=410,
                            prior_feedback=feedback,
                        ),
                    ],
                    verifications=[
                        execution("verification", "failed", 40, 44, attempt_id="attempt-2")
                    ],
                    error_details={"code": "verification_failed", "failed_stage": "verification"},
                )
            ],
        )
    ]
    out = tmp_path / "ledger.json"
    assert run(api, out, "--trials", "1") == 0
    ledger, markdown = read(out)
    trial = ledger["trials"][0]
    assert trial["verified"] is False
    assert (trial["outcome"], trial["error_code"], trial["failed_stage"]) == (
        "unresolved",
        "verification_failed",
        "verification",
    )
    assert [item["attempt_number"] for item in trial["attempts"]] == [1, 2]
    assert trial["attempts"][0]["policy_valid"] is False
    assert trial["attempts"][0]["policy_error"] == "import of os is not allowed"
    assert trial["attempts"][1]["prior_feedback"] == feedback
    summary = ledger["summary"]
    assert summary["outcome_counts"] == {"unresolved": 1}
    assert summary["verified_count"] == 0 and summary["verified_rate"] == 0.0
    assert summary["policy_rejected_attempts"] == 1
    assert summary["prompt_tokens"] == {"attempt_count": 2, "known_count": 1, "total": None}
    assert summary["completion_tokens"]["total"] == 710
    assert "| 1 | 00000000 | unresolved | no | 2 | 42.5 | 40/44 | unrecorded |" in markdown


def test_deadline_cancels_and_records_the_terminal_record(
    proxy: tuple[FakeProxy, str], tmp_path: Path
) -> None:
    fake, api = proxy
    cancelled = detail(
        state="cancelled",
        outcome="cancelled",
        attempts=[],
        verifications=[],
        error_details={"code": "cancelled", "failed_stage": "diagnosing"},
    )
    fake.plans = [JobPlan(JOB_1, [running()], after_cancel=cancelled)]
    out = tmp_path / "ledger.json"
    assert run(api, out, "--trials", "1", "--deadline", "0.1") == 0
    ledger, markdown = read(out)
    assert f"/api/faultline/jobs/{JOB_1}/cancel" in fake.paths("POST")
    trial = ledger["trials"][0]
    assert trial["deadline_exceeded"] is True
    assert trial["cancel_requested_by_ledger"] is True
    assert (trial["state"], trial["outcome"], trial["verified"]) == (
        "cancelled",
        "cancelled",
        False,
    )
    assert ledger["summary"]["deadline_exceeded_count"] == 1
    assert ledger["complete"] is True
    assert "cancelled (deadline exceeded)" in markdown


def test_job_that_never_terminates_after_cancel_stops_the_run(
    proxy: tuple[FakeProxy, str], tmp_path: Path
) -> None:
    fake, api = proxy
    fake.plans = [JobPlan(JOB_1, [running()])]
    out = tmp_path / "ledger.json"
    assert run(api, out, "--trials", "2", "--deadline", "0.05", cancel_grace=0.1) == 1
    ledger, _ = read(out)
    assert ledger["complete"] is False
    assert "did not reach a terminal state" in ledger["stop_reason"]
    trial = ledger["trials"][0]
    assert (trial["terminal"], trial["state"], trial["wall_seconds"]) == (False, "running", None)
    assert len(fake.paths("POST")) == 2  # one submission, one cancellation, no second job


@pytest.mark.parametrize(
    ("readiness", "expected"),
    [
        (ready(available=False, model_reason="provider_http_401"), "model unavailable"),
        (ready(quarantined=True), "runtime quarantined"),
        (ready(runtime_ready=False), "runtime not ready"),
    ],
)
def test_readiness_refusal_records_no_trials(
    proxy: tuple[FakeProxy, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    readiness: dict[str, Any],
    expected: str,
) -> None:
    fake, api = proxy
    fake.readiness = [readiness]
    out = tmp_path / "ledger.json"
    assert run(api, out) == 1
    ledger, _ = read(out)
    assert fake.paths("POST") == []
    assert ledger["complete"] is False and ledger["trials"] == []
    assert expected in ledger["stop_reason"]
    assert ledger["readiness"]["quarantined"] is readiness["quarantined"]
    stderr = capsys.readouterr().err
    assert '"provider": "meta"' in stderr and expected in stderr


def test_require_meta_refuses_a_deterministic_controller(
    proxy: tuple[FakeProxy, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, api = proxy
    fake.readiness = [ready("deterministic", "deterministic-checkout-v1")]
    out = tmp_path / "ledger.json"
    assert run(api, out, "--require-provider", "meta") == 1
    ledger, _ = read(out)
    assert fake.paths("POST") == []
    assert "'deterministic'" in ledger["stop_reason"] and "'meta'" in ledger["stop_reason"]
    assert ledger["readiness"]["provider"] == "deterministic"
    assert '"provider": "deterministic"' in capsys.readouterr().err


def test_quarantine_between_trials_stops_without_reset(
    proxy: tuple[FakeProxy, str], tmp_path: Path
) -> None:
    fake, api = proxy
    fake.readiness = [ready(), ready(quarantined=True)]
    fake.plans = [JobPlan(JOB_1, [detail()]), JobPlan(JOB_2, [detail(JOB_2)])]
    out = tmp_path / "ledger.json"
    assert run(api, out, "--trials", "3") == 1
    ledger, markdown = read(out)
    assert len(ledger["trials"]) == 1 and ledger["trials"][0]["verified"] is True
    assert ledger["complete"] is False
    assert "stopped before trial 2: runtime quarantined" in ledger["stop_reason"]
    assert ledger["stop_readiness"]["reason"] == "cleanup_required"
    assert fake.paths("POST") == ["/api/faultline/jobs"]
    assert "Status: incomplete." in markdown


def test_transport_error_keeps_a_partial_ledger(
    proxy: tuple[FakeProxy, str], tmp_path: Path
) -> None:
    fake, api = proxy
    fake.plans = [JobPlan(JOB_1, [detail()]), JobPlan(JOB_2, [], status=502)]
    out = tmp_path / "ledger.json"
    assert run(api, out, "--trials", "2") == 1
    ledger, _ = read(out)
    assert ledger["complete"] is False
    assert "HTTP 502" in ledger["stop_reason"] and "trial 2" in ledger["stop_reason"]
    first, second = ledger["trials"]
    assert first["verified"] is True
    assert second["job_id"] == JOB_2
    assert second["evidence_recorded"] is False
    assert (second["state"], second["outcome"], second["verified"]) == (None, None, False)
    assert second["artifact_count"] is None and second["wall_seconds"] is None
    assert ledger["summary"]["trials_run"] == 2 and ledger["summary"]["verified_count"] == 1


def test_unreachable_proxy_writes_an_incomplete_ledger(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    out = tmp_path / "nested" / "ledger.json"
    assert run(f"http://127.0.0.1:{port}/api/faultline", out) == 1
    ledger, markdown = read(out)
    assert ledger["complete"] is False and ledger["readiness"] is None
    assert ledger["stop_reason"].startswith("readiness check failed")
    assert "Readiness was not recorded." in markdown


def test_deterministic_markdown_never_mentions_meta(
    proxy: tuple[FakeProxy, str], tmp_path: Path
) -> None:
    fake, api = proxy
    fake.readiness = [ready("deterministic", "deterministic-checkout-v1")]
    deterministic = attempt(
        1, provider="deterministic", model="deterministic-checkout-v1", prompt=None, completion=None
    )
    fake.plans = [
        JobPlan(JOB_1, [detail(attempts=[deterministic])]),
        JobPlan(JOB_2, [detail(JOB_2, attempts=[deterministic])]),
    ]
    out = tmp_path / "ledger.json"
    assert run(api, out, "--trials", "2", "--require-provider", "deterministic") == 0
    ledger, markdown = read(out)
    assert ledger["classification"] == "deterministic_workflow_rehearsals"
    assert "not a Meta model trial" in ledger["classification_note"]
    assert ledger["summary"]["prompt_tokens"] == {
        "attempt_count": 2,
        "known_count": 0,
        "total": None,
    }
    assert "meta" not in markdown.lower()
    assert "deterministic workflow rehearsals" in markdown


def _trial(*attempts: dict[str, Any]) -> dict[str, Any]:
    return {"attempts": list(attempts)}


def _attempt(provider: str | None) -> dict[str, Any]:
    return {"provider": provider}


@pytest.mark.parametrize(
    ("providers", "expected"),
    [
        (["meta", "meta"], "meta_model_trials"),
        (["deterministic"], "deterministic_workflow_rehearsals"),
        (["local", "local"], "local_model_trials"),
        (["openai-compatible"], "openai_compatible_trials"),
        (["meta", "deterministic"], "mixed"),
        (["meta", None], "meta_model_trials"),
        (["local", "openai-compatible"], "mixed"),
        ([None], "no_model_response"),
        ([], "no_recorded_attempts"),
    ],
)
def test_classification_requires_every_attempt_to_agree(
    providers: list[str | None], expected: str
) -> None:
    trials = [_trial(*(_attempt(provider) for provider in providers)), _trial()]
    classification, note = ledger_tool.classify(trials)
    assert classification == expected
    if expected != "meta_model_trials":
        assert "live Meta model trials" not in note


def test_provider_errors_are_never_counted_as_model_output() -> None:
    trials = [_trial(_attempt("meta"), _attempt(None)), _trial(_attempt("meta"))]
    assert ledger_tool.provider_counts(trials) == {"meta": 2, "no_response": 1}
    classification, note = ledger_tool.classify(trials)
    assert classification == "meta_model_trials"
    assert "All 2 provider responses" in note and "1 other attempt(s)" in note
    mixed = [_trial(_attempt("meta"), _attempt("local"), _attempt(None))]
    assert "local: 1, meta: 1, no_response: 1" in ledger_tool.classify(mixed)[1]


def test_token_totals_are_null_unless_every_attempt_is_known() -> None:
    known = [{"prompt_tokens": 10}, {"prompt_tokens": 5}]
    partial = [{"prompt_tokens": 10}, {"prompt_tokens": None}]
    assert ledger_tool._token_total(known, "prompt_tokens")["total"] == 15
    assert ledger_tool._token_total(partial, "prompt_tokens") == {
        "attempt_count": 2,
        "known_count": 1,
        "total": None,
    }


def test_wall_time_distribution_uses_nearest_rank() -> None:
    values = [float(value) for value in range(1, 21)]
    result = ledger_tool._distribution(values)
    assert (result["median"], result["p95"], result["min"], result["max"]) == (
        10.5,
        19.0,
        1.0,
        20.0,
    )
    assert ledger_tool._distribution([])["median"] is None


def test_changed_lines_ignore_headers_but_count_removed_dash_lines() -> None:
    diff = "--- a/x.sql\n+++ b/x.sql\n@@ -1,2 +1,2 @@\n--- old comment\n+-- new comment\n keep\n"
    assert ledger_tool.changed_line_count(diff) == 2
    assert ledger_tool.changed_line_count("") == 0


@pytest.mark.parametrize(
    ("changes", "verified"),
    [
        ({}, True),
        ({"cleanup": "failed"}, False),
        ({"baseline": "passed"}, False),
        ({"baseline": None}, False),
        ({"state": "failed", "outcome": "unresolved"}, False),
        ({"verifications": [execution("verification", "passed", 43, 44)]}, False),
        ({"verifications": [execution("verification", "passed", 0, 0)]}, False),
        ({"verifications": []}, False),
    ],
)
def test_verified_requires_the_rehearsal_conditions(
    changes: dict[str, Any], verified: bool
) -> None:
    progress = ledger_tool.TrialProgress(1, str(uuid.uuid4()), JOB_1, detail(**changes))
    assert ledger_tool.trial_record(progress)["verified"] is verified


@pytest.mark.parametrize(
    "arguments",
    [
        ["--trials", "0"],
        ["--trials", "51"],
        ["--deadline", "0"],
        ["--out", "ledger.md"],
        ["--api", "http://user:secret@127.0.0.1:4000/api/faultline"],
        ["--require-provider", "gpt"],
    ],
)
def test_invalid_arguments_are_rejected(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        ledger_tool.parse_args(["--out", "ledger.json", *arguments])
    assert raised.value.code == 2


def test_default_api_follows_inspector_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAULTLINE_INSPECTOR_URL", "http://127.0.0.1:4100/")
    options = ledger_tool.parse_args(["--out", "ledger.json"])
    assert options.api == "http://127.0.0.1:4100/api/faultline"
    assert (options.trials, options.deadline, options.require_provider) == (5, 190.0, None)


def test_script_runs_as_a_standalone_program() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--require-provider" in result.stdout
