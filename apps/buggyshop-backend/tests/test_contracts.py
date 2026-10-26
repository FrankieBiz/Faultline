"""Wire round trips and strict rejection for the public backend contracts."""

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from shared.config import REGISTRY, Scenario
from shared.contracts import (
    AssertionResult,
    CleanupStatus,
    ExecutionReport,
    ExecutionVerdict,
    Job,
    JobStage,
    JobState,
    Observation,
    ObservationKind,
    PatchValidationResult,
    RepairAttempt,
    TerminalOutcome,
)

OBSERVATION: dict[str, Any] = {
    "id": "observation-1",
    "kind": "http_error",
    "source": "POST /api/checkout",
    "message": "Checkout returned 500",
    "data": {"status": 500},
    "timestamp": "2026-10-26T12:00:00Z",
}
ASSERTION: dict[str, Any] = {
    "id": "checkout.status_201",
    "passed": False,
    "expected": "201",
    "observed": "500",
    "duration_ms": 2.5,
}
JOB: dict[str, Any] = {
    "id": "job-1",
    "scenario_id": "scripted_checkout_repair",
    "state": "queued",
    "stage": "preparing",
    "outcome": None,
    "cleanup_status": "not_started",
    "created_at": "2026-10-26T12:00:00Z",
    "updated_at": "2026-10-26T12:00:00Z",
    "error_details": None,
}
WIRE_CASES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (Observation, OBSERVATION),
    (AssertionResult, ASSERTION),
    (
        ExecutionReport,
        {
            "execution_id": "execution-1",
            "case_id": "case-1",
            "scenario_id": "scripted_checkout_repair",
            "verdict": "failed",
            "duration_ms": 25.0,
            "observations": [OBSERVATION],
            "assertions": [ASSERTION],
            "raw_logs": "TypeError",
        },
    ),
    (Job, JOB),
    (
        RepairAttempt,
        {
            "id": "attempt-1",
            "job_id": "job-1",
            "attempt_number": 1,
            "prompt_tokens": None,
            "completion_tokens": None,
            "raw_patch": None,
            "parsed_diff": None,
            "validation_result": None,
            "outcome": None,
        },
    ),
    (
        PatchValidationResult,
        {
            "is_valid": False,
            "target_file": "app/routes/checkout.py",
            "syntax_valid": True,
            "error_message": "Unexpected path",
            "ast_safe": False,
        },
    ),
]


@pytest.mark.parametrize(("model", "payload"), WIRE_CASES)
def test_contract_json_round_trip(model: type[BaseModel], payload: dict[str, Any]) -> None:
    parsed = model.model_validate_json(json.dumps(payload))
    assert model.model_validate_json(parsed.model_dump_json()) == parsed
    assert parsed.model_dump(mode="json") == payload


@pytest.mark.parametrize(("model", "payload"), WIRE_CASES)
def test_unknown_contract_fields_are_rejected(
    model: type[BaseModel], payload: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps({**payload, "unknown": "field"}))
    assert model.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_assertion_passed_is_a_strict_boolean(value: object) -> None:
    with pytest.raises(ValidationError):
        AssertionResult.model_validate_json(json.dumps({**ASSERTION, "passed": value}))


@pytest.mark.parametrize("value", [-1.0, "2.5", float("inf"), float("nan"), True])
def test_duration_is_finite_and_nonnegative(value: object) -> None:
    with pytest.raises(ValidationError):
        AssertionResult.model_validate({**ASSERTION, "duration_ms": value})


def test_timestamps_require_timezone_and_normalize_utc() -> None:
    timestamp = datetime(2026, 10, 26, 8, tzinfo=timezone(timedelta(hours=-4)))
    observation = Observation(
        id="event",
        kind=ObservationKind.SERVER_EXCEPTION,
        source="backend",
        message="TypeError",
        data={},
        timestamp=timestamp,
    )
    assert observation.timestamp == datetime(2026, 10, 26, 12, tzinfo=UTC)
    assert observation.timestamp.tzinfo is UTC
    assert observation.model_dump(mode="json")["timestamp"] == "2026-10-26T12:00:00Z"
    with pytest.raises(ValidationError, match="timezone-aware"):
        Observation.model_validate(
            {**observation.model_dump(), "timestamp": timestamp.replace(tzinfo=None)}
        )


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_job_json_rejects_naive_timestamps(field: str) -> None:
    with pytest.raises(ValidationError):
        Job.model_validate_json(json.dumps({**JOB, field: "2026-10-26T12:00:00"}))


@pytest.mark.parametrize("attempt_number", [0, -1, True, "1", 1.5])
def test_attempt_number_is_a_positive_integer(attempt_number: object) -> None:
    with pytest.raises(ValidationError):
        RepairAttempt.model_validate(
            {"id": "attempt", "job_id": "job", "attempt_number": attempt_number}
        )


@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens"])
@pytest.mark.parametrize("value", [-1, True, "10", 2.5])
def test_usage_is_unknown_or_a_nonnegative_integer(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RepairAttempt.model_validate(
            {"id": "attempt", "job_id": "job", "attempt_number": 1, field: value}
        )
    attempt = RepairAttempt(id="attempt", job_id="job", attempt_number=1)
    assert attempt.prompt_tokens is None
    assert attempt.completion_tokens is None


@pytest.mark.parametrize("state", list(JobState))
def test_all_job_states_have_wire_representations(state: JobState) -> None:
    assert Job.model_validate_json(json.dumps({**JOB, "state": state.value})).state is state


@pytest.mark.parametrize("outcome", list(TerminalOutcome))
def test_all_terminal_outcomes_have_wire_representations(outcome: TerminalOutcome) -> None:
    assert Job.model_validate_json(json.dumps({**JOB, "outcome": outcome.value})).outcome is outcome


def test_contract_enum_values_reject_unknown_wire_values() -> None:
    for enum in [
        ObservationKind,
        ExecutionVerdict,
        JobState,
        JobStage,
        TerminalOutcome,
        CleanupStatus,
    ]:
        with pytest.raises(ValueError):
            enum("unknown")


def test_scenario_registry_is_explicit_and_validated() -> None:
    assert set(REGISTRY) == {"scripted_checkout_repair"}
    scenario = REGISTRY["scripted_checkout_repair"]
    assert scenario.id == "scripted_checkout_repair"
    assert scenario.route == "POST /api/checkout"
    assert scenario.target_file == "apps/buggyshop-backend/app/routes/checkout.py"
    assert scenario.expected_assertions
    assert len(set(scenario.expected_assertions)) == len(scenario.expected_assertions)
    assert Scenario.model_validate_json(scenario.model_dump_json()) == scenario
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            {**scenario.model_dump(), "untrusted_url": "https://outside.example"}
        )
