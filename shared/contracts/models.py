"""Canonical Pydantic v2 contracts for execution evidence and repair jobs.

Wire data must use ``model_validate_json`` so JSON enum strings and RFC 3339
timestamps are decoded while scalar types and unknown fields remain strict.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _utc_timestamp(value: datetime) -> datetime:
    """Require a timezone and normalize persisted timestamps to UTC."""
    if value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(UTC)


Timestamp = Annotated[datetime, AfterValidator(_utc_timestamp)]
Duration = Annotated[float, Field(ge=0)]
TokenCount = Annotated[int, Field(ge=0)]


class ContractModel(BaseModel):
    """Reject extra keys, implicit scalar coercion, and nonfinite numbers."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ObservationKind(StrEnum):
    """Distinct sources of failure evidence collected by the trusted runner."""

    ASSERTION = "assertion"
    HTTP_ERROR = "http_error"
    BROWSER_EXCEPTION = "browser_exception"
    TRANSPORT_ERROR = "transport_error"
    SERVER_EXCEPTION = "server_exception"
    RUNNER_ERROR = "runner_error"


class Observation(ContractModel):
    """One timestamped observation, preserving structured diagnostic data."""

    id: str
    kind: ObservationKind
    source: str
    message: str
    data: dict[str, Any]
    timestamp: Timestamp


class AssertionResult(ContractModel):
    """The measured result of a single named business assertion."""

    id: str
    passed: bool
    expected: str
    observed: str
    duration_ms: Duration


class ExecutionVerdict(StrEnum):
    """Separate assertion failures from execution infrastructure errors."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class ExecutionReport(ContractModel):
    """Runner evidence for one scenario execution within a case namespace."""

    execution_id: str
    case_id: str
    scenario_id: str
    verdict: ExecutionVerdict
    duration_ms: Duration
    observations: list[Observation]
    assertions: list[AssertionResult]
    raw_logs: str


class JobState(StrEnum):
    """Persisted lifecycle state of a controlled repair job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobStage(StrEnum):
    """Current workflow stage, including cleanup and terminal completion."""

    PREPARING = "preparing"
    BASELINE = "baseline"
    DIAGNOSING = "diagnosing"
    PATCH_VALIDATION = "patch_validation"
    ACTIVATING = "activating"
    VERIFICATION = "verification"
    CLEANUP = "cleanup"
    COMPLETED = "completed"


class TerminalOutcome(StrEnum):
    """Specific terminal result; cleanup remains independently observable."""

    VERIFIED = "verified"
    DETECTED = "detected"
    NO_FAILURE = "no_failure"
    REPAIR_UNAVAILABLE = "repair_unavailable"
    UNEXPECTED_FAILURE = "unexpected_failure"
    INVALID_PATCH = "invalid_patch"
    MODEL_ERROR = "model_error"
    UNRESOLVED = "unresolved"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    ARTIFACT_ERROR = "artifact_error"
    TIMEOUT = "timeout"
    CLEANUP_FAILED = "cleanup_failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class CleanupStatus(StrEnum):
    """Whether disposal of job-owned resources has been confirmed."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job(ContractModel):
    """Persisted job status with explicit work outcome and cleanup status."""

    id: str
    scenario_id: str
    state: JobState
    stage: JobStage
    outcome: TerminalOutcome | None = None
    cleanup_status: CleanupStatus
    created_at: Timestamp
    updated_at: Timestamp
    error_details: dict[str, Any] | None = None


class RepairAttempt(ContractModel):
    """One bounded proposal and its validation result; unknown usage is null."""

    id: str
    job_id: str
    attempt_number: Annotated[int, Field(ge=1)]
    prompt_tokens: TokenCount | None = None
    completion_tokens: TokenCount | None = None
    raw_patch: str | None = None
    parsed_diff: str | None = None
    validation_result: dict[str, Any] | None = None
    outcome: str | None = None


class PatchValidationResult(ContractModel):
    """Policy and syntax checks for a proposed single-file source patch."""

    is_valid: bool
    target_file: str
    syntax_valid: bool
    error_message: str | None = None
    ast_safe: bool
