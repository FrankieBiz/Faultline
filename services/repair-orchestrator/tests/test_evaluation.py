"""Corpus integrity, measured gate value, and the verifier-feedback repair loop.

The launcher here runs authored, hash-pinned corpus code on the test host, like
``fixture_probe.py``. It is never selectable by the evaluation command line,
which uses only the isolated runtime.
"""

import asyncio
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app import evaluation
from app.evaluation import (
    BackendSession,
    classify,
    render_markdown,
    run_evaluation,
    summarize_patches,
)
from app.model_adapter import (
    MetaRepairAdapter,
    ModelResponse,
    ModelSettings,
    ProbeResult,
    RepairContext,
)
from app.policy import TARGET_FILE
from app.runtime import CandidateRejected
from app.snapshots import REPOSITORY_ROOT
from fixtures.evaluation.corpus import CASES_PATH, load_corpus
from shared.contracts.models import PatchProposal


@dataclass(frozen=True)
class HostSession:
    client: httpx.AsyncClient
    logs: Callable[[], str]


class HostLauncher:
    """Serve an exported fixture tree with uvicorn over a private UNIX socket."""

    kind = "test-host"

    def session(self, application: Path) -> AbstractAsyncContextManager[BackendSession]:
        return self._session(application)

    @asynccontextmanager
    async def _session(self, application: Path) -> AsyncGenerator[BackendSession]:
        directory = Path(tempfile.mkdtemp(prefix="fl-eval-", dir="/tmp"))
        socket = str(directory / "backend.sock")
        log = directory / "stderr.log"
        with log.open("wb") as stderr:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--uds", socket]
                + ["--log-level", "warning"],
                cwd=application / "apps/buggyshop-backend",
                env={"PATH": os.environ.get("PATH", "/usr/bin"), "PYTHONDONTWRITEBYTECODE": "1"},
                stdout=subprocess.DEVNULL,
                stderr=stderr,
            )
        transport = httpx.AsyncHTTPTransport(uds=socket)
        client = httpx.AsyncClient(transport=transport, base_url="http://test-host", timeout=3)
        try:
            for _ in range(200):
                if process.poll() is not None:
                    # Mirrors the isolated runtime: a backend that exits failed in candidate code.
                    raise CandidateRejected("isolated_backend_failed")
                try:
                    if (await client.get("/healthz")).status_code == 200:
                        break
                except httpx.HTTPError:
                    await asyncio.sleep(0.025)
            else:
                raise AssertionError("test-host backend did not become ready")
            yield HostSession(client, lambda: log.read_text(errors="replace"))
        finally:
            await client.aclose()
            process.kill()
            process.wait()
            shutil.rmtree(directory)


class ScriptedAdapter(MetaRepairAdapter):
    """Return authored proposals in order and retain every context it receives."""

    def __init__(self, diffs: list[str]) -> None:
        super().__init__(ModelSettings(api_key="test", base_url="http://127.0.0.1:9/v1"))
        self.diffs = diffs
        self.contexts: list[RepairContext] = []

    async def probe(self) -> ProbeResult:
        return ProbeResult(True, "local", "scripted-test")

    async def propose_patch(
        self, context: RepairContext, *, fallback: bool = False
    ) -> ModelResponse:
        self.contexts.append(context)
        return ModelResponse(
            PatchProposal(
                decision="patch",
                target_file=TARGET_FILE,
                base_sha256=context.base_sha256,
                unified_diff=self.diffs[len(self.contexts) - 1],
                explanation="Scripted test proposal.",
            ),
            "local",
            "scripted-test",
            prompt_tokens=10,
            completion_tokens=5,
        )


def patch_text(case_id: str) -> str:
    return (REPOSITORY_ROOT / f"fixtures/evaluation/adversarial/{case_id}.diff").read_text()


def test_corpus_is_hash_pinned_and_tampering_fails_closed(tmp_path: Path) -> None:
    corpus = load_corpus()
    assert len(corpus["holdout"]) == 10 and len(corpus["patches"]) == 11
    for case in [*corpus["holdout"], *corpus["patches"]]:
        source = REPOSITORY_ROOT / case["path"]
        copy = tmp_path / case["path"]
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, copy)
    (tmp_path / CASES_PATH).write_text((REPOSITORY_ROOT / CASES_PATH).read_text())
    assert load_corpus(tmp_path) == corpus
    tampered = tmp_path / corpus["patches"][0]["path"]
    tampered.write_text(tampered.read_text() + " ")
    with pytest.raises(ValueError, match="differ"):
        load_corpus(tmp_path)


async def test_gates_reject_every_wrong_patch_that_a_symptom_check_accepts(
    tmp_path: Path,
) -> None:
    adapter = MetaRepairAdapter(ModelSettings())
    report = await run_evaluation(
        launcher=HostLauncher(),
        adapter=adapter,
        work_root=tmp_path,
        suites={"patches"},
    )
    summary = report["patches"]["summary"]
    assert summary == {
        "correct": 2,
        "correct_accepted_by_faultline": 2,
        "correct_accepted_by_symptom_check": 2,
        "wrong": 6,
        "wrong_accepted_by_faultline": 0,
        "wrong_accepted_by_symptom_check": 5,
        "out_of_policy": 3,
        "out_of_policy_rejected_by_policy": 3,
        "all_match_corpus": True,
    }
    null_only = next(
        case for case in report["patches"]["cases"] if case["id"] == "null_coupon_only"
    )
    # The incident replay sends a null coupon, exactly as the storefront does.
    assert null_only["symptom_check_accepts"] is True
    assert null_only["failing"] == ["regression.empty_coupon", "regression.whitespace_coupon"]
    assert report["classification"] == "deterministic_fallback_no_model_call"
    markdown = render_markdown(report)
    assert "accepted 5 of 6 incorrect patches. FaultLine accepted 0." in markdown
    assert "FaultLine accepted 2 of 2 correct patches; policy rejected 3 of 3" in markdown
    assert "| `null_coupon_only` | wrong | pass | accept | reject | 2 |" in markdown


async def test_holdout_baselines_match_and_deterministic_mode_does_not_generalize(
    tmp_path: Path,
) -> None:
    report = await run_evaluation(
        launcher=HostLauncher(),
        adapter=MetaRepairAdapter(ModelSettings()),
        work_root=tmp_path,
        suites={"holdout"},
    )
    cases = {case["id"]: case for case in report["holdout"]["cases"]}
    assert all(case["baseline_matches_corpus"] for case in cases.values())
    assert cases["seeded_missing_coupon"]["outcome"] == "verified"
    unfamiliar = [case for key, case in cases.items() if key != "seeded_missing_coupon"]
    assert {case["outcome"] for case in unfamiliar} == {"model_error"}
    assert {case["attempts"][0]["outcome"] for case in unfamiliar} == {
        "unsupported_fallback_source"
    }
    # Unsupported sources are terminal provider errors, not crashes or pointless retries.
    assert all(len(case["attempts"]) == 1 for case in unfamiliar)
    seeded_attempt = cases["seeded_missing_coupon"]["attempts"][0]
    assert seeded_attempt["policy"]["is_valid"] is True
    assert seeded_attempt["failing_after"] == []
    assert seeded_attempt["provider"] == "deterministic"
    assert report["complete"] is True
    summary = report["holdout"]["summary"]
    assert (summary["runs"], summary["verified"], summary["verified_first_attempt"]) == (10, 1, 1)
    markdown = render_markdown(report)
    assert "makes no model call" in markdown and "Meta" not in markdown


def test_gate_comparison_counts_acceptance_independently() -> None:
    cases = [
        {
            "kind": kind,
            "symptom_check_accepts": symptom,
            "faultline_accepts": faultline,
            "policy": {"is_valid": kind != "out_of_policy"},
            "matches_corpus": True,
        }
        for kind, symptom, faultline in (
            ("correct", True, True),
            ("correct", False, True),
            ("wrong", True, False),
            ("wrong", True, False),
            ("wrong", False, False),
            ("out_of_policy", None, False),
        )
    ]
    assert summarize_patches(cases) == {
        "correct": 2,
        "correct_accepted_by_faultline": 2,
        "correct_accepted_by_symptom_check": 1,
        "wrong": 3,
        "wrong_accepted_by_faultline": 0,
        "wrong_accepted_by_symptom_check": 2,
        "out_of_policy": 1,
        "out_of_policy_rejected_by_policy": 1,
        "all_match_corpus": True,
    }


def test_default_command_runs_both_suites_and_refreshes_unified_latest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = HostLauncher()
    monkeypatch.setattr(launcher, "preflight", AsyncMock(), raising=False)
    monkeypatch.setattr(evaluation, "IsolatedBackendLauncher", lambda: launcher)
    monkeypatch.setattr(evaluation, "REPOSITORY_ROOT", tmp_path)
    # Even an invalid configured provider must not affect an unqualified run.
    monkeypatch.setenv("META_API_KEY", "test-unused")
    monkeypatch.setenv("META_BASE_URL", "invalid-provider-url")
    monkeypatch.setattr(sys, "argv", ["evaluation"])
    with pytest.raises(SystemExit) as exit_status:
        evaluation.main()
    assert exit_status.value.code == 0
    latest = tmp_path / "data/evaluations/latest"
    first_run = latest.resolve()
    report = json.loads((latest / "results.json").read_text())
    assert report["complete"] is True
    assert report["classification"] == "deterministic_fallback_no_model_call"
    assert report["holdout"]["summary"]["runs"] == 10
    assert len(report["patches"]["cases"]) == 11
    assert (latest / "summary.md").read_text() == render_markdown(report)

    monkeypatch.setattr(sys, "argv", ["evaluation", "--cases", "seeded_missing_coupon"])
    with pytest.raises(SystemExit) as exit_status:
        evaluation.main()
    assert exit_status.value.code == 0
    assert latest.resolve() != first_run and (first_run / "results.json").is_file()
    refreshed = json.loads((latest / "results.json").read_text())
    assert refreshed["holdout"]["summary"]["runs"] == 1
    assert refreshed["patches"]["cases"] == []
    previous_run = latest.resolve()
    monkeypatch.setattr(
        evaluation, "run_evaluation", AsyncMock(side_effect=RuntimeError("stopped"))
    )
    with pytest.raises(RuntimeError, match="stopped"):
        evaluation.main()
    assert latest.resolve() == previous_run
    assert json.loads((latest / "results.json").read_text()) == refreshed


def test_explicit_suite_preserves_provider_selection_and_custom_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = HostLauncher()
    monkeypatch.setattr(launcher, "preflight", AsyncMock(), raising=False)
    monkeypatch.setattr(evaluation, "IsolatedBackendLauncher", lambda: launcher)
    monkeypatch.setattr(evaluation, "REPOSITORY_ROOT", tmp_path)
    settings_reads: list[bool] = []

    def settings_from_environment(cls: type[ModelSettings]) -> ModelSettings:
        settings_reads.append(True)
        return cls()

    monkeypatch.setattr(ModelSettings, "from_environment", classmethod(settings_from_environment))
    out = tmp_path / "custom"
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluation", "--suite=patches", "--cases", "null_coupon_only", "--out", str(out)],
    )
    with pytest.raises(SystemExit) as exit_status:
        evaluation.main()
    assert exit_status.value.code == 0
    report = json.loads((out / "results.json").read_text())
    assert settings_reads == [True]
    assert "holdout" not in report
    assert len(report["patches"]["cases"]) == 1
    assert not (tmp_path / "data/evaluations/latest").exists()


async def test_failed_verification_feeds_measured_checks_to_the_second_attempt(
    tmp_path: Path,
) -> None:
    adapter = ScriptedAdapter(
        [patch_text("null_coupon_only"), patch_text("reference_default_zero")]
    )
    report = await run_evaluation(
        launcher=HostLauncher(),
        adapter=adapter,
        work_root=tmp_path,
        suites={"holdout"},
        case_ids={"seeded_missing_coupon"},
    )
    case = report["holdout"]["cases"][0]
    assert case["outcome"] == "verified"
    assert [attempt["outcome"] for attempt in case["attempts"]] == [
        "verification_failed",
        "verified",
    ]
    assert case["attempts"][0]["failing_after"] == [
        "regression.empty_coupon",
        "regression.whitespace_coupon",
    ]
    feedback = adapter.contexts[1].feedback
    assert feedback is not None and feedback.gate == "verification_failed"
    assert [check.id for check in feedback.failed_checks] == case["attempts"][0]["failing_after"]
    assert "regression.missing_coupon" in adapter.contexts[0].failure_traceback
    summary = report["holdout"]["summary"]
    assert summary["verified_after_gate_feedback"] == 1 and summary["total_tokens"] == 30
    assert summary["verified_after_other_retry"] == 0
    assert report["classification"] == "local_model_not_meta_hosted"
    assert json.loads(json.dumps(report)) == report


async def test_policy_rejection_is_fed_back_without_execution(tmp_path: Path) -> None:
    malformed = patch_text("reference_default_zero").replace("@@ -40,7", "@@ -40,9")
    adapter = ScriptedAdapter([malformed, patch_text("reference_default_zero")])
    report = await run_evaluation(
        launcher=HostLauncher(),
        adapter=adapter,
        work_root=tmp_path,
        suites={"holdout"},
        case_ids={"seeded_missing_coupon"},
    )
    first, second = report["holdout"]["cases"][0]["attempts"]
    assert first["outcome"] == "patch_policy_rejected" and "failing_after" not in first
    assert second["prior_feedback"]["gate"] == "patch_policy_rejected"
    feedback: Any = adapter.contexts[1].feedback
    assert "line counts" in feedback.policy_error


def test_classification_never_labels_non_meta_hosts_as_meta() -> None:
    assert classify("meta") == "meta_model"
    assert classify("local") == "local_model_not_meta_hosted"
    assert classify("openai-compatible") == "openai_compatible_model_not_meta_hosted"
    assert classify("deterministic") == "deterministic_fallback_no_model_call"


async def test_candidate_that_cannot_start_is_rejected_with_feedback(tmp_path: Path) -> None:
    # Policy admits an undefined module-level name; the backend fails at import.
    seeded = (REPOSITORY_ROOT / "fixtures/seeds/checkout_seeded.py").read_text()
    broken = (
        seeded.replace("discounts.get(coupon_code))", "discounts.get(coupon_code, 0))")
        + "\n\nROUNDING = Decimal(1)\n"
    )
    crashing = "".join(
        difflib.unified_diff(
            seeded.splitlines(keepends=True),
            broken.splitlines(keepends=True),
            fromfile=f"a/{TARGET_FILE}",
            tofile=f"b/{TARGET_FILE}",
        )
    )
    adapter = ScriptedAdapter([crashing, patch_text("reference_default_zero")])
    checkpoints: list[dict[str, Any]] = []
    report = await run_evaluation(
        launcher=HostLauncher(),
        adapter=adapter,
        work_root=tmp_path,
        suites={"holdout"},
        case_ids={"seeded_missing_coupon"},
        checkpoint=lambda partial: checkpoints.append(json.loads(json.dumps(partial))),
    )
    first, second = report["holdout"]["cases"][0]["attempts"]
    assert first["policy"]["is_valid"] is True
    assert first["outcome"] == "candidate_rejected"
    assert first["rejection"] == "isolated_backend_failed"
    assert second["prior_feedback"]["gate"] == "candidate_rejected"
    assert report["holdout"]["cases"][0]["outcome"] == "verified"
    assert report["holdout"]["summary"]["verified_after_gate_feedback"] == 1
    assert checkpoints and checkpoints[-1]["complete"] is False
    assert report["complete"] is True
