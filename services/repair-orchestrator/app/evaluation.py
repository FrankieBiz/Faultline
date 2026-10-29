"""Measured generalization and gate-value evaluation over the authored corpus.

Both suites use the same independent HTTP oracle that verifies controller
candidates:

* ``holdout``: unfamiliar single-defect checkout variants. The configured
  provider sees only the failing checks and backend logs, proposes one patch,
  and the patched candidate is re-measured in a fresh backend. A rejected first
  attempt sends bounded gate findings to a second attempt.
* ``patches``: plausible repairs of the registered defect, judged by the patch
  policy and oracle and, for comparison, by a naive symptom check that only
  replays the incident request.

Variant and candidate code executes only through the supplied launcher; the
command line selects the isolated runtime. Results describe this authored
corpus, not arbitrary applications or defects.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import statistics
import subprocess
import time
from collections import Counter
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import httpx

from app.http_regression import CANDIDATE_FAULTS, regression
from app.model_adapter import (
    CORRECTABLE_PROPOSAL_ERRORS,
    AttemptFeedback,
    FailedCheck,
    MetaRepairAdapter,
    ModelError,
    ModelSettings,
    RepairContext,
)
from app.policy import TARGET_FILE, PatchPolicy, parse_unified_diff
from app.runtime import CandidateRejected
from app.snapshots import REPOSITORY_ROOT, contained_path
from fixtures.evaluation.corpus import Corpus, HoldoutCase, PatchCase, case_bytes, load_corpus
from fixtures.provenance import verify_manifest
from shared.contracts.models import AssertionResult

BACKEND_APP = "apps/buggyshop-backend/app/"
MAX_LOG_EVIDENCE = 8 * 1024
# Outer guard only; the adapter's own configured timeout normally fires first.
GENERATION_GRACE = 15.0
# Findings from an independent gate, as opposed to retries after provider faults.
GATE_FEEDBACK = frozenset({"verification_failed", "patch_policy_rejected", "candidate_rejected"})


class BackendSession(Protocol):
    """A running backend and a reader for its bounded stderr."""

    @property
    def client(self) -> httpx.AsyncClient:
        """HTTP client bound to this backend only."""
        ...

    @property
    def logs(self) -> Callable[[], str]:
        """Return the backend's bounded stderr so far."""
        ...


class BackendLauncher(Protocol):
    """Start one fresh backend from an exported application tree."""

    kind: str

    def session(self, application: Path) -> AbstractAsyncContextManager[BackendSession]:
        """Yield a ready backend and dispose every owned resource on exit."""
        ...


@dataclass(frozen=True)
class Measurement:
    """Oracle results, the incident replay status, and backend logs for one run."""

    checks: tuple[AssertionResult, ...]
    symptom_status: int | None
    logs: str

    @property
    def failing(self) -> list[AssertionResult]:
        """Checks the candidate did not satisfy, in oracle order."""
        return [check for check in self.checks if not check.passed]


class LimitRecorder:
    """Wrap a launcher and retain the aggregate limits each backend session reported."""

    def __init__(self, inner: BackendLauncher) -> None:
        self.inner = inner
        self.kind = inner.kind
        self.observed: list[dict[str, Any] | None] = []

    def session(self, application: Path) -> AbstractAsyncContextManager[BackendSession]:
        """Delegate to the wrapped launcher, recording its limits once ready."""
        return self._session(application)

    @asynccontextmanager
    async def _session(self, application: Path) -> AsyncGenerator[BackendSession]:
        async with self.inner.session(application) as backend:
            limits = getattr(backend, "resource_limits", None)
            self.observed.append(limits.model_dump(mode="json") if limits is not None else None)
            yield backend

    def summary(self) -> dict[str, Any]:
        """Count sessions whose limits were read back and verified from the kernel."""
        return {
            "sessions": len(self.observed),
            "verified_sessions": sum(
                1 for item in self.observed if item and item.get("verified") is True
            ),
            "limits": next((item for item in self.observed if item), None),
        }


class ApplicationExporter:
    """Write application files from the pinned seed commit with one replaced target."""

    def __init__(self, repository_root: Path, seed_commit: str, work_root: Path) -> None:
        self.work_root = work_root
        self.files: dict[str, bytes] = {}
        listing = subprocess.run(
            ["git", "-C", str(repository_root), "ls-tree", "-r", "-z", seed_commit, "--"]
            + [BACKEND_APP],
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout
        for entry in filter(None, listing.split(b"\x00")):
            metadata, name = entry.decode("utf-8").split("\t", 1)
            mode, kind, blob = metadata.split()
            if mode != "100644" or kind != "blob" or not name.endswith(".py"):
                raise ValueError("Seed export requires ordinary Python application files")
            self.files[name] = subprocess.run(
                ["git", "-C", str(repository_root), "cat-file", "blob", blob],
                check=True,
                capture_output=True,
                timeout=10,
            ).stdout
        if TARGET_FILE not in self.files:
            raise ValueError("Seed commit does not contain the repair target")

    def export(self, target_source: str) -> Path:
        """Create a fresh, owned application tree; nothing is imported here."""
        root = self.work_root / str(uuid4())
        for name, content in self.files.items():
            path = contained_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(target_source.encode() if name == TARGET_FILE else content)
        return root


async def measure(
    launcher: BackendLauncher, exporter: ApplicationExporter, source: str, incident: dict[str, Any]
) -> Measurement:
    """Run the oracle and then replay the incident request in one fresh backend."""
    application = exporter.export(source)
    try:
        async with launcher.session(application) as backend:
            checks = await regression(backend.client)
            status: int | None
            try:
                response = await backend.client.post(
                    "/api/checkout",
                    json=incident,
                    headers={"X-Faultline-Case-Id": str(uuid4())},
                )
                status = response.status_code
            except CANDIDATE_FAULTS:
                status = None
            return Measurement(tuple(checks), status, backend.logs())
    finally:
        shutil.rmtree(application, ignore_errors=True)


def failure_evidence(measurement: Measurement) -> str:
    """Describe the observed failure as a test report plus bounded backend logs."""
    lines = ["Independent HTTP checks failed against the isolated backend:"]
    lines.extend(
        f"FAILED {check.id}: expected {check.expected}; observed {check.observed}"
        for check in measurement.failing
    )
    logs = measurement.logs.encode()[-MAX_LOG_EVIDENCE:].decode("utf-8", errors="ignore")
    if logs.strip():
        lines.extend(("", "Backend log (most recent):", logs))
    return "\n".join(lines)


def _feedback(gate: str, diff: str | None, measurement: Measurement) -> AttemptFeedback:
    failing = measurement.failing
    return AttemptFeedback(
        gate,
        rejected_diff=diff,
        failed_checks=tuple(FailedCheck(item.id, item.expected, item.observed) for item in failing),
        failed_count=len(failing),
    )


async def evaluate_holdout(
    case: HoldoutCase,
    source: str,
    adapter: MetaRepairAdapter,
    launcher: BackendLauncher,
    exporter: ApplicationExporter,
    incident: dict[str, Any],
    *,
    attempts: int = 2,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Reproduce one unfamiliar defect and let the provider repair it under the gates."""
    event_started = time.monotonic()

    def emit(
        stage: str, status: str, number: int | None, message: str, data: dict[str, Any]
    ) -> None:
        if on_event is not None:
            on_event(
                {
                    "t_ms": round((time.monotonic() - event_started) * 1000),
                    "stage": stage,
                    "status": status,
                    "attempt": number,
                    "message": message,
                    "data": data,
                }
            )

    emit("baseline", "running", None, "Measuring the selected defect.", {})
    baseline = await measure(launcher, exporter, source, incident)
    failing = [item.id for item in baseline.failing]
    emit(
        "baseline",
        "failed" if failing else "passed",
        None,
        "Baseline checks completed.",
        {"failing": failing, "total": len(baseline.checks)},
    )
    result: dict[str, Any] = {
        "id": case["id"],
        "defect_class": case["defect_class"],
        "baseline_failures": failing,
        "baseline_matches_corpus": sorted(failing) == sorted(case["expected_failures"]),
        "attempts": [],
    }
    if not failing:
        result["outcome"] = "baseline_passed"
        return result
    evidence = failure_evidence(baseline)
    base_sha256 = hashlib.sha256(source.encode()).hexdigest()
    feedback: AttemptFeedback | None = None
    previous_gate: str | None = None
    outcome = "model_error"
    for number in range(1, attempts + 1):
        record: dict[str, Any] = {
            "attempt_number": number,
            "prior_feedback": feedback.summary() if feedback else None,
        }
        result["attempts"].append(record)
        context = RepairContext(source, evidence, previous_gate, feedback)
        started = time.monotonic()
        emit("propose", "running", number, "Requesting a repair proposal.", {})
        try:
            async with asyncio.timeout(adapter.settings.timeout + GENERATION_GRACE):
                response = await adapter.propose_patch(context)
        except (ModelError, TimeoutError) as exc:
            code = exc.code if isinstance(exc, ModelError) else "provider_timeout"
            retryable = exc.retryable if isinstance(exc, ModelError) else True
            record.update(outcome=code, generation_ms=round((time.monotonic() - started) * 1000))
            emit("propose", "error", number, "Proposal request failed.", {"code": code})
            outcome, previous_gate = "model_error", code
            feedback = AttemptFeedback(code) if code in CORRECTABLE_PROPOSAL_ERRORS else None
            if not retryable:
                break
            continue
        proposal = response.proposal
        record.update(
            provider=response.provider,
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            generation_ms=round((time.monotonic() - started) * 1000),
            decision=proposal.decision,
            explanation=proposal.explanation,
            diff=proposal.unified_diff,
            diff_sha256=hashlib.sha256(proposal.unified_diff.encode()).hexdigest(),
            diff_recounted=response.original_diff is not None,
            model_diff=response.original_diff,
        )
        emit(
            "propose",
            "passed",
            number,
            "Repair proposal received.",
            {
                key: record[key]
                for key in (
                    "provider",
                    "model",
                    "generation_ms",
                    "prompt_tokens",
                    "completion_tokens",
                    "decision",
                )
            },
        )
        if proposal.decision == "no_patch":
            record["outcome"] = outcome = "no_patch"
            break
        validation = PatchPolicy().validate(
            proposal.unified_diff, source, base_sha256=proposal.base_sha256
        )
        record["policy"] = {"is_valid": validation.is_valid, "error": validation.error_message}
        admitted = validation.is_valid and proposal.base_sha256 == base_sha256
        emit(
            "policy",
            "passed" if admitted else "rejected",
            number,
            "Patch policy passed." if admitted else "Patch policy rejected the proposal.",
            {
                "error": validation.error_message
                if admitted
                else validation.error_message or "Source hash does not match."
            },
        )
        if not validation.is_valid or proposal.base_sha256 != base_sha256:
            record["outcome"] = outcome = previous_gate = "patch_policy_rejected"
            feedback = AttemptFeedback(
                previous_gate,
                rejected_diff=proposal.unified_diff,
                policy_error=validation.error_message,
            )
            continue
        candidate = parse_unified_diff(proposal.unified_diff, source).patched_source
        emit("verify", "running", number, "Checking the isolated candidate.", {})
        try:
            verified = await measure(launcher, exporter, candidate, incident)
        except CandidateRejected as exc:
            record["outcome"] = outcome = previous_gate = "candidate_rejected"
            record["rejection"] = str(exc)
            emit("verify", "rejected", number, "Candidate could not run.", {"rejection": str(exc)})
            feedback = AttemptFeedback(
                previous_gate, rejected_diff=proposal.unified_diff, policy_error=str(exc)
            )
            continue
        record["failing_after"] = [item.id for item in verified.failing]
        emit(
            "verify",
            "failed" if verified.failing else "passed",
            number,
            "Candidate checks completed.",
            {"failing": record["failing_after"], "total": len(verified.checks)},
        )
        if not verified.failing:
            record["outcome"] = outcome = "verified"
            break
        record["outcome"] = outcome = previous_gate = "verification_failed"
        feedback = _feedback(previous_gate, proposal.unified_diff, verified)
    result["outcome"] = outcome
    return result


async def evaluate_patch(
    case: PatchCase,
    diff: str,
    seeded: str,
    launcher: BackendLauncher,
    exporter: ApplicationExporter,
    incident: dict[str, Any],
) -> dict[str, Any]:
    """Judge one candidate patch with the gates and with a naive symptom check."""
    validation = PatchPolicy().validate(diff, seeded)
    result: dict[str, Any] = {
        "id": case["id"],
        "kind": case["kind"],
        "policy": {"is_valid": validation.is_valid, "error": validation.error_message},
    }
    if not validation.is_valid:
        result.update(
            symptom_check_accepts=None,
            faultline_accepts=False,
            failing=[],
            matches_corpus=case["kind"] == "out_of_policy",
        )
        return result
    candidate = parse_unified_diff(diff, seeded).patched_source
    try:
        measured = await measure(launcher, exporter, candidate, incident)
    except CandidateRejected as exc:
        result.update(
            rejection=str(exc),
            symptom_status=None,
            symptom_check_accepts=False,
            faultline_accepts=False,
            failing=[],
            matches_corpus=case["kind"] == "wrong",
        )
        return result
    failing = [item.id for item in measured.failing]
    accepts = not failing
    result.update(
        symptom_status=measured.symptom_status,
        symptom_check_accepts=measured.symptom_status == 201,
        faultline_accepts=accepts,
        failing=failing,
        matches_corpus=(accepts if case["kind"] == "correct" else False)
        if case["kind"] != "wrong"
        else (not accepts and sorted(failing) == sorted(case["expected_failures"])),
    )
    return result


def _median(values: list[int]) -> float | None:
    return float(statistics.median(values)) if values else None


def summarize_holdout(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Count outcomes and provider usage without inventing unreported values."""
    attempts = [attempt for case in cases for attempt in case["attempts"]]
    tokens = [
        attempt.get(key)
        for attempt in attempts
        if "provider" in attempt
        for key in ("prompt_tokens", "completion_tokens")
    ]
    verified = [case for case in cases if case["outcome"] == "verified"]

    def after_gate(case: dict[str, Any]) -> bool:
        prior = case["attempts"][-1].get("prior_feedback")
        return bool(prior) and prior["gate"] in GATE_FEEDBACK

    retried = [case for case in verified if case["attempts"][-1]["attempt_number"] > 1]
    return {
        "runs": len(cases),
        "verified": len(verified),
        "verified_first_attempt": len(verified) - len(retried),
        "verified_after_gate_feedback": sum(1 for case in retried if after_gate(case)),
        "verified_after_other_retry": sum(1 for case in retried if not after_gate(case)),
        "outcomes": dict(sorted(Counter(case["outcome"] for case in cases).items())),
        "baseline_matches_corpus": sum(1 for case in cases if case["baseline_matches_corpus"]),
        "model_attempts": len(attempts),
        "total_tokens": sum(value for value in tokens if isinstance(value, int))
        if tokens and all(isinstance(value, int) for value in tokens)
        else None,
        "median_generation_ms": _median(
            [attempt["generation_ms"] for attempt in attempts if "generation_ms" in attempt]
        ),
    }


def summarize_patches(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the gates with a symptom check across correct and incorrect patches."""

    def count(kind: str, key: str) -> int:
        return sum(1 for case in cases if case["kind"] == kind and case[key] is True)

    def total(kind: str) -> int:
        return sum(1 for case in cases if case["kind"] == kind)

    return {
        "correct": total("correct"),
        "correct_accepted_by_faultline": count("correct", "faultline_accepts"),
        "correct_accepted_by_symptom_check": count("correct", "symptom_check_accepts"),
        "wrong": total("wrong"),
        "wrong_accepted_by_faultline": count("wrong", "faultline_accepts"),
        "wrong_accepted_by_symptom_check": count("wrong", "symptom_check_accepts"),
        "out_of_policy": total("out_of_policy"),
        "out_of_policy_rejected_by_policy": sum(
            1
            for case in cases
            if case["kind"] == "out_of_policy" and not case["policy"]["is_valid"]
        ),
        "all_match_corpus": all(case["matches_corpus"] for case in cases),
    }


def classify(provider: str) -> str:
    """Name the evidence honestly; only Meta-hosted calls are Meta model results."""
    return {
        "deterministic": "deterministic_fallback_no_model_call",
        "meta": "meta_model",
        "local": "local_model_not_meta_hosted",
    }.get(provider, "openai_compatible_model_not_meta_hosted")


async def run_evaluation(
    *,
    launcher: BackendLauncher,
    adapter: MetaRepairAdapter,
    work_root: Path,
    suites: set[str],
    case_ids: set[str] | None = None,
    repeat: int = 1,
    attempts: int = 2,
    repository_root: Path = REPOSITORY_ROOT,
    progress: Callable[[str], None] = lambda message: None,
    checkpoint: Callable[[dict[str, Any]], None] = lambda report: None,
) -> dict[str, Any]:
    """Verify provenance, then evaluate the selected suites sequentially."""
    corpus: Corpus = load_corpus(repository_root)
    manifest = verify_manifest(repository_root)
    seed_commit = manifest.get("source_commit")
    if seed_commit is None:
        raise ValueError("A pinned seed commit is required")
    probe = await adapter.probe()
    if not probe.available:
        raise RuntimeError(f"Repair provider unavailable: {probe.reason}")
    exporter = ApplicationExporter(repository_root, seed_commit, work_root)
    incident = corpus["incident_request"]
    corpus_hash = hashlib.sha256(
        (repository_root / "fixtures/evaluation/cases.json").read_bytes()
    ).hexdigest()
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "tool": "faultline-evaluation",
        "started_at": datetime.now(UTC).isoformat(),
        "corpus": {"version": corpus["corpus_version"], "sha256": corpus_hash},
        "seed_commit": seed_commit,
        "runtime": launcher.kind,
        "provider": {
            "provider": probe.provider,
            "model": probe.model,
            "available": probe.available,
        },
        "classification": classify(probe.provider),
        "oracle": "app.http_regression (27 independent HTTP business checks)",
        "complete": False,
    }

    recorder = LimitRecorder(launcher)

    def selected(case_id: str) -> bool:
        return case_ids is None or case_id in case_ids

    if "holdout" in suites:
        results = []
        for trial in range(1, repeat + 1):
            for case in corpus["holdout"]:
                if not selected(case["id"]):
                    continue
                progress(f"holdout {case['id']} (trial {trial}/{repeat})")
                source = case_bytes(case, repository_root).decode("utf-8")
                outcome = await evaluate_holdout(
                    case, source, adapter, recorder, exporter, incident, attempts=attempts
                )
                results.append({"trial": trial, **outcome})
                report["holdout"] = {"cases": results, "summary": summarize_holdout(results)}
                report["runtime_limits"] = recorder.summary()
                checkpoint(report)
                progress(f"  -> {outcome['outcome']}")
        report["holdout"] = {"cases": results, "summary": summarize_holdout(results)}
    if "patches" in suites:
        seeded_case = next(
            case for case in corpus["holdout"] if case["id"] == "seeded_missing_coupon"
        )
        seeded = case_bytes(seeded_case, repository_root).decode("utf-8")
        patch_results = []
        for patch in corpus["patches"]:
            if not selected(patch["id"]):
                continue
            progress(f"patch {patch['id']}")
            diff = case_bytes(patch, repository_root).decode("utf-8")
            patch_results.append(
                await evaluate_patch(patch, diff, seeded, recorder, exporter, incident)
            )
            report["patches"] = {
                "cases": patch_results,
                "summary": summarize_patches(patch_results),
            }
            report["runtime_limits"] = recorder.summary()
            checkpoint(report)
        report["patches"] = {"cases": patch_results, "summary": summarize_patches(patch_results)}
    report["runtime_limits"] = recorder.summary()
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["complete"] = True
    return report


def _limits_line(observed: dict[str, Any] | None) -> str:
    if not observed or not observed["sessions"]:
        return "- Aggregate limits: no backend sessions recorded"
    limits = observed["limits"]
    if limits is None:
        return f"- Aggregate limits: not recorded for {observed['sessions']} backend sessions"
    if limits["mode"] == "disabled":
        return "- Aggregate limits: disabled by the operator"
    return (
        f"- Aggregate limits: {observed['verified_sessions']} of {observed['sessions']} backend "
        f"sessions ran in a verified cgroup v2 scope ({limits['memory_max_bytes'] // 1048576} MiB, "
        f"{limits['tasks_max']} tasks, {limits['cpu_quota_percent']}% CPU, no swap)"
    )


def render_markdown(report: dict[str, Any]) -> str:
    """Summarize measured results in plain tables; no claims beyond the record."""
    provider = report["provider"]
    lines = [
        "# FaultLine evaluation results",
        "",
        f"- Classification: `{report['classification']}`",
        f"- Provider: `{provider['provider']}` · model `{provider['model']}`",
        f"- Runtime: `{report['runtime']}` · seed `{report['seed_commit'][:12]}`",
        f"- Corpus: `{report['corpus']['version']}` · sha256 `{report['corpus']['sha256'][:12]}`",
        f"- Oracle: {report['oracle']}",
        _limits_line(report.get("runtime_limits")),
        f"- Window: {report['started_at']} to {report.get('finished_at', 'incomplete')}",
        "",
    ]
    if not report["complete"]:
        lines += [
            "**Incomplete run:** the tables cover only cases measured before the run stopped.",
            "",
        ]
    if report["classification"] == "deterministic_fallback_no_model_call":
        lines += [
            "The deterministic fallback makes no model call. It only knows the registered "
            "defect, so these results test the gates, not model generalization.",
            "",
        ]
    if "holdout" in report:
        summary = report["holdout"]["summary"]
        lines += [
            "## Unfamiliar defects",
            "",
            f"Verified {summary['verified']} of {summary['runs']} runs: "
            f"{summary['verified_first_attempt']} on the first attempt, "
            f"{summary['verified_after_gate_feedback']} after policy, start-up, or verification "
            f"findings were sent back, and {summary['verified_after_other_retry']} after a retry "
            "that followed a provider fault or a proposal-format rejection.",
            "",
            "| Trial | Case | Baseline failures | Attempts | Outcome |",
            "| ---: | --- | ---: | ---: | --- |",
        ]
        for case in report["holdout"]["cases"]:
            lines.append(
                f"| {case['trial']} | `{case['id']}` | {len(case['baseline_failures'])} | "
                f"{len(case['attempts'])} | {case['outcome'].replace('_', ' ')} |"
            )
        lines += [
            "",
            f"Outcomes: {summary['outcomes']}. Repair attempts: {summary['model_attempts']}. "
            f"Total tokens: {summary['total_tokens'] if summary['total_tokens'] is not None else 'not reported'}. "  # noqa: E501
            f"Median generation: {summary['median_generation_ms']} ms.",
            "",
        ]
    if "patches" in report:
        summary = report["patches"]["summary"]
        lines += [
            "## Candidate patches for the registered defect",
            "",
            f"The naive symptom check (replay the incident request and require HTTP 201) "
            f"accepted {summary['wrong_accepted_by_symptom_check']} of {summary['wrong']} "
            f"incorrect patches. FaultLine accepted {summary['wrong_accepted_by_faultline']}. "
            f"FaultLine accepted {summary['correct_accepted_by_faultline']} of "
            f"{summary['correct']} correct patches; policy rejected "
            f"{summary['out_of_policy_rejected_by_policy']} of {summary['out_of_policy']} "
            "out-of-policy patches before execution.",
            "",
            "| Patch | Kind | Policy | Symptom check | FaultLine | Failing checks |",
            "| --- | --- | --- | --- | --- | ---: |",
        ]
        for case in report["patches"]["cases"]:
            symptom = case["symptom_check_accepts"]
            lines.append(
                f"| `{case['id']}` | {case['kind'].replace('_', ' ')} | "
                f"{'pass' if case['policy']['is_valid'] else 'reject'} | "
                f"{'n/a' if symptom is None else 'accept' if symptom else 'reject'} | "
                f"{'accept' if case['faultline_accepts'] else 'reject'} | "
                f"{len(case['failing'])} |"
            )
        lines.append("")
    lines += [
        "These results cover an authored corpus for one checkout route. They are not a "
        "benchmark of arbitrary applications, and a verified candidate is not a deployment.",
        "",
    ]
    return "\n".join(lines)


class IsolatedBackendLauncher:
    """Launch backend-only sessions through the production isolated runtime profile."""

    kind = "isolated-backend"

    def __init__(self) -> None:
        from app.isolated_runtime import IsolatedRuntime

        self.runtime = IsolatedRuntime()

    def session(self, application: Path) -> AbstractAsyncContextManager[BackendSession]:
        """Start one candidate backend in its own namespace and aggregate limits."""
        return self.runtime.backend_session(application)

    async def preflight(self, *, allow_disabled_limits: bool = False) -> None:
        """Fail closed unless the sandbox and enforced aggregate limits are ready.

        An operator opt-out of aggregate limits must also be explicit here, and
        every report still records the limits each session actually had.
        """
        await self.runtime.backend_preflight()
        status = self.runtime.resource_limits_status
        if status["enforcement_preflight"] != "passed" and not (
            allow_disabled_limits and status["requested"] == "disabled"
        ):
            raise RuntimeError(f"Aggregate limits are not enforced: {status['reason']}")


def _write(out: Path, report: dict[str, Any]) -> None:
    """Replace results atomically so an interrupted run keeps its last checkpoint."""
    for name, text in (
        ("results.json", json.dumps(report, indent=2) + "\n"),
        ("summary.md", render_markdown(report)),
    ):
        partial = out / f".{name}.partial"
        partial.write_text(text, encoding="utf-8")
        partial.replace(out / name)


async def _main(arguments: argparse.Namespace) -> int:
    launcher = IsolatedBackendLauncher()
    await launcher.preflight(allow_disabled_limits=arguments.allow_disabled_limits)
    adapter = MetaRepairAdapter(ModelSettings.from_environment())
    out = Path(arguments.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    work_root = out / "work"
    try:
        report = await run_evaluation(
            launcher=launcher,
            adapter=adapter,
            work_root=work_root,
            suites={"holdout", "patches"} if arguments.suite == "all" else {arguments.suite},
            case_ids=set(arguments.cases.split(",")) if arguments.cases else None,
            repeat=arguments.repeat,
            attempts=arguments.attempts,
            progress=lambda message: print(message, flush=True),
            checkpoint=lambda partial: _write(out, partial),
        )
    finally:
        await adapter.close()
        shutil.rmtree(work_root, ignore_errors=True)
    _write(out, report)
    print(f"Wrote {out / 'results.json'} and {out / 'summary.md'}")
    return 0


def main() -> None:
    """Run the evaluation from the command line with the isolated runtime only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("holdout", "patches", "all"), default="all")
    parser.add_argument("--cases", help="Comma-separated case IDs; default: every case")
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--attempts", type=int, choices=(1, 2), default=2)
    parser.add_argument("--out", required=True, help="New directory for results.json/summary.md")
    parser.add_argument(
        "--allow-disabled-limits",
        action="store_true",
        help="Run when the operator disabled aggregate limits; reports still record it",
    )
    raise SystemExit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
