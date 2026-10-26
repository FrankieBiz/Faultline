"""Authentication, idempotent controller routes, artifacts, and SSE replay."""

import asyncio
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import Harness, submission
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import Settings, create_app, event_stream
from app.model_adapter import MetaRepairAdapter, ModelSettings, ProbeResult
from shared.contracts.models import JobStage, TerminalOutcome

TOKEN = "test-controller-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(harness: Harness) -> Iterator[TestClient]:
    app = create_app(
        Settings(data_dir=harness.root, control_token=TOKEN),
        database=harness.database,
        adapter=harness.adapter,
        runtime=harness.runtime,
        snapshots=harness.snapshots,
    )
    with TestClient(app) as value:
        yield value


def wait_completed(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        detail: dict[str, Any] = client.get(f"/api/faultline/jobs/{job_id}", headers=HEADERS).json()
        if detail["job"]["stage"] == "completed":
            return detail
        time.sleep(0.01)
    pytest.fail("Job did not finish")


def test_public_health_is_exact_and_documentation_is_disabled(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok", "app": "faultline-orchestrator"}
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/jobs"),
        ("POST", "/jobs"),
        ("GET", "/jobs/unknown"),
        ("GET", "/jobs/unknown/events"),
        ("POST", "/jobs/unknown/cancel"),
        ("POST", "/reset"),
        ("GET", "/readiness"),
        ("GET", "/scenarios"),
        ("GET", "/artifacts/unknown"),
    ],
)
@pytest.mark.parametrize("auth", [None, "Bearer wrong", f"Basic {TOKEN}", "Bearer"])
def test_every_controller_route_requires_bearer(
    client: TestClient,
    method: str,
    path: str,
    auth: str | None,
) -> None:
    response = client.request(
        method, "/api/faultline" + path, headers={"Authorization": auth} if auth else {}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_job_endpoints_and_private_artifact_paths(client: TestClient) -> None:
    body = submission().model_dump(mode="json")
    created = client.post("/api/faultline/jobs", json=body, headers=HEADERS)
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert client.post("/api/faultline/jobs", json=body, headers=HEADERS).json()["job_id"] == job_id
    done = wait_completed(client, job_id)
    assert done["job"]["outcome"] == "verified"
    assert done["baseline"]["report"]["verdict"] == "failed"
    assert len(done["attempts"]) == 1
    assert len(client.get("/api/faultline/jobs", headers=HEADERS).json()["jobs"]) == 1
    assert "storage_key" not in json.dumps(done)
    artifact = done["artifacts"][0]
    download = client.get(f"/api/faultline/artifacts/{artifact['id']}", headers=HEADERS)
    assert download.status_code == 200
    assert download.headers["x-content-type-options"] == "nosniff"
    cancel = client.post(f"/api/faultline/jobs/{job_id}/cancel", headers=HEADERS)
    assert cancel.status_code == 200 and cancel.json() == done["job"]
    assert client.post("/api/faultline/reset", headers=HEADERS).status_code == 200
    assert client.get(f"/api/faultline/jobs/{job_id}", headers=HEADERS).json() == done


def test_sse_content_type_sequences_and_resume(client: TestClient) -> None:
    created = client.post(
        "/api/faultline/jobs", json=submission().model_dump(mode="json"), headers=HEADERS
    )
    job_id = created.json()["job_id"]
    done = wait_completed(client, job_id)
    response = client.get(f"/api/faultline/jobs/{job_id}/events", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    ids = [
        int(line.removeprefix("id: "))
        for line in response.text.splitlines()
        if line.startswith("id:")
    ]
    assert ids == [event["sequence"] for event in done["events"]]
    resumed = client.get(
        f"/api/faultline/jobs/{job_id}/events", headers={**HEADERS, "Last-Event-ID": "3"}
    )
    resumed_ids = [int(line[4:]) for line in resumed.text.splitlines() if line.startswith("id:")]
    assert resumed_ids == ids[3:]
    assert '"stage":"completed"' in resumed.text


@pytest.mark.parametrize("path", ["/jobs/missing", "/jobs/missing/events", "/artifacts/missing"])
def test_missing_resources_are_404(client: TestClient, path: str) -> None:
    assert client.get("/api/faultline" + path, headers=HEADERS).status_code == 404


def test_invalid_body_scenario_key_and_limit(client: TestClient) -> None:
    body = submission().model_dump(mode="json")
    for candidate in [
        {**body, "scenario_id": "unknown"},
        {**body, "idempotency_key": "invalid"},
        {**body, "target_file": "/etc/passwd"},
        {**body, "mode": "other"},
    ]:
        assert (
            client.post("/api/faultline/jobs", json=candidate, headers=HEADERS).status_code == 422
        )
    for limit in [0, 101, "bad"]:
        assert client.get(f"/api/faultline/jobs?limit={limit}", headers=HEADERS).status_code == 422


def test_readiness_explicitly_labels_deterministic_mode(client: TestClient) -> None:
    response = client.get("/api/faultline/readiness", headers=HEADERS).json()
    assert response["status"] == "ready"
    assert response["model"]["provider"] == "deterministic"
    assert TOKEN not in json.dumps(response)
    assert client.get("/api/faultline/scenarios", headers=HEADERS).status_code == 200


def test_unconfigured_runtime_blocks_jobs_without_host_fallback(tmp_path: Path) -> None:
    adapter = MetaRepairAdapter(ModelSettings())
    app = create_app(Settings(data_dir=tmp_path, control_token=TOKEN), adapter=adapter)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/faultline/readiness", headers=HEADERS).json()["status"] == "blocked"
        response = client.post(
            "/api/faultline/jobs", json=submission().model_dump(mode="json"), headers=HEADERS
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "isolated_runtime_unavailable"


def test_missing_control_token_refuses_startup(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="FAULTLINE_CONTROL_TOKEN is required"):
        with TestClient(create_app(Settings(data_dir=tmp_path))):
            pass


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    headers = {
        "Origin": "http://127.0.0.1:4000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    allowed = client.options("/api/faultline/jobs", headers=headers)
    assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
    rejected = client.options(
        "/api/faultline/jobs", headers={**headers, "Origin": "https://other.invalid"}
    )
    assert "access-control-allow-origin" not in rejected.headers


def test_busy_cancel_and_idempotency_conflict(client: TestClient, harness: Harness) -> None:
    harness.runtime.delay = 0.2
    body = submission().model_dump(mode="json")
    first = client.post("/api/faultline/jobs", json=body, headers=HEADERS)
    job_id = first.json()["job_id"]
    conflict = client.post("/api/faultline/jobs", json={**body, "mode": "detect"}, headers=HEADERS)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    busy = client.post(
        "/api/faultline/jobs", json=submission().model_dump(mode="json"), headers=HEADERS
    )
    assert busy.status_code == 409
    assert client.post("/api/faultline/reset", headers=HEADERS).status_code == 409
    cancelled = client.post(f"/api/faultline/jobs/{job_id}/cancel", headers=HEADERS)
    assert cancelled.status_code == 202
    assert wait_completed(client, job_id)["job"]["outcome"] == "cancelled"


def test_unavailable_model_is_explicit_detection_only(client: TestClient, harness: Harness) -> None:
    cast(FastAPI, client.app).state.controller.worker.probe = ProbeResult(
        False, "meta", "muse-spark-1.3", "model_unavailable"
    )
    response = client.post(
        "/api/faultline/jobs", json=submission().model_dump(mode="json"), headers=HEADERS
    )
    assert response.json()["effective_mode"] == "detect"
    assert response.json()["repair_block_reason"] == "model_unavailable"
    detail = wait_completed(client, response.json()["job_id"])
    assert detail["job"]["outcome"] == "repair_unavailable"
    assert not detail["attempts"]


async def test_live_event_generator_observes_transitions(harness: Harness) -> None:
    job = harness.database.create_job(submission())
    stream = event_stream(harness.database, job.id, poll_seconds=0.001)
    first = await anext(stream)
    assert first.id == "1"
    harness.database.transition(job.id, JobStage.BASELINE)
    second = await asyncio.wait_for(anext(stream), 1)
    assert second.id == "2"
    harness.database.finish_job(job.id, TerminalOutcome.DETECTED, clean=True)
    final = await anext(stream)
    assert final.id == "3"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


def test_oversized_json_is_rejected(client: TestClient) -> None:
    response = client.post("/api/faultline/jobs", content=b"x" * 4097, headers=HEADERS)
    assert response.status_code == 413
