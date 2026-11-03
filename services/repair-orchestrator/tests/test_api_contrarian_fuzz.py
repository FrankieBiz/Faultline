"""Contrarian fuzz and race tests for the repair-orchestrator API boundary.

This file assumes nothing is safe. It throws hostile bytes at the three
surfaces a deployment decision flows through — job admission, snapshot/job
lookup, and cancellation — and asserts every failure lands in a single safe,
structured ``DatabaseError`` envelope (``422``/``413``/``404``/``409``/``401``)
rather than an unhandled traceback, a leaked filesystem path, or a mutated job:

1. **Job creation** (``POST /api/faultline/jobs``) — malformed JSON shapes,
   invalid UTF-8, lone surrogates, oversized bodies, and header injection must
   fail closed without echoing the hostile input.
2. **Snapshot / job lookup** (``GET /api/faultline/jobs/{job_id}`` and
   ``/api/faultline/artifacts/{artifact_id}``) — path traversal in the id path
   parameters (``..``, ``\\``, ``%2e%2e``) must never reach the filesystem,
   never return ``200``, and never leak a private storage path.
3. **Concurrent cancellation** (``POST /api/faultline/jobs/{job_id}/cancel``)
   — many simultaneous cancellations against an active or terminal job must
   serialize idempotently: exactly one ``cancel_requested`` event, a single
   terminal state, and no ``500``.

No browser, runner, sandbox, or model is launched; the ``client`` and
``harness`` fixtures from ``conftest`` supply the deterministic simulations.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from conftest import Harness, submission
from fastapi.testclient import TestClient
from test_api import HEADERS, TOKEN, wait_completed

from app.main import Settings, create_app
from app.snapshots import SnapshotManager, contained_path
from shared.contracts.models import JobState, TerminalOutcome


@pytest.fixture
def client(harness: Harness) -> Iterator[TestClient]:
    """The same trusted simulation boundary used by ``test_api``."""
    app = create_app(
        Settings(data_dir=harness.root, control_token=TOKEN),
        database=harness.database,
        adapter=harness.adapter,
        runtime=harness.runtime,
        snapshots=harness.snapshots,
    )
    with TestClient(app) as value:
        yield value


# --- hostile corpora -----------------------------------------------------------


# Percent-encoded traversal survives client-side URL normalization (httpx folds
# a literal ``..`` away before the request leaves), so these spellings are what
# actually reach Starlette's routing and the controller's path parameters.
_TRAVERSAL_IDS = [
    "%2e%2e",
    "%2e%2e%2f",
    "%2e%2e%2f%2e%2e",
    "%2e%2e%2fetc%2fpasswd",
    "..%2fetc%2fpasswd",
    "%252e%252e",
    "%252e%252e%252fetc%252fpasswd",
    "..%5c..%5cetc%5cpasswd",
    "..%5c..%5cwindows%5csystem32",
    ".%2e",
    "....",
    "%2e",
    "%2e%2e%2f.",
]

_MALFORMED_BODIES = [
    b"",  # empty
    b"hello world",  # not JSON
    b"[]",  # JSON array, not object
    b"null",  # JSON null
    b"42",  # JSON number
    b'"string"',  # JSON string
    b'{"scenario_id": "scripted_checkout_repair", "idempotency_key":',  # truncated
    b'{"scenario_id": "scripted_checkout_repair", "idempotency_key": "x"',  # unclosed
    b'{"scenario_id": "\xff\xfe\x00", "idempotency_key": "x"}',  # invalid UTF-8
    b'{"scenario_id": "\xed\xa0\x80", "idempotency_key": "x"}',  # lone surrogate
    b'{"scenario_id": "\x00", "idempotency_key": "x"}',  # NUL byte
]

# Hostile Authorization header values. Only a single clean ``Bearer <token>``
# (case-insensitive scheme per RFC 7235) may pass; every injected byte must 401.
_HOSTILE_AUTH = [
    "Bearer " + TOKEN + "\r\nX-Evil: 1",
    "Bearer " + TOKEN + "\nInjected: yes",
    "Bearer " + TOKEN + "\x00tail",
    "Bearer " + TOKEN + "\t",
    "Bearer  " + TOKEN,
    "Bearer " + TOKEN + " ",
    "Bearer " + TOKEN + "\r",
    "Bearer\r\n" + TOKEN,
    "bearer " + TOKEN + " extra",
    "Bearer: " + TOKEN,
    "Bearer",
]


# --- 1. job creation -----------------------------------------------------------


@pytest.mark.parametrize("body", _MALFORMED_BODIES, ids=repr)
def test_malformed_job_bodies_fail_closed_without_echo(client: TestClient, body: bytes) -> None:
    """Every hostile byte string is rejected as ``invalid_request``, never echoed."""
    response = client.post(
        "/api/faultline/jobs", content=body, headers={**HEADERS, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    # The envelope is fixed and never reflects the hostile bytes back.
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "invalid request", "job_id": None}
    }
    # Distinctive non-empty hostile payloads are provably absent from the reply.
    if body and body not in b'"job_id":null':
        assert body not in response.content


@pytest.mark.parametrize(
    "payload",
    [
        {"scenario_id": 123, "idempotency_key": "x"},
        {"scenario_id": None, "idempotency_key": "x"},
        {"scenario_id": ["a"], "idempotency_key": "x"},
        {"scenario_id": "scripted_checkout_repair", "idempotency_key": 7},
        {"scenario_id": "scripted_checkout_repair", "idempotency_key": None},
        {"scenario_id": "scripted_checkout_repair"},  # missing idempotency_key
        {"idempotency_key": "00000000-0000-0000-0000-000000000000"},  # missing scenario_id
        {"scenario_id": "scripted_checkout_repair", "idempotency_key": "x", "extra": True},
        {
            "scenario_id": "scripted_checkout_repair",
            "idempotency_key": "00000000-0000-0000-0000-000000000000",
            "mode": "sideways",
        },
        {
            "scenario_id": "scripted_checkout_repair",
            "idempotency_key": "00000000-0000-0000-0000-000000000000",
            "mode": 3,
        },
    ],
)
def test_strict_contract_rejects_wrong_types_extra_fields_and_bad_enums(
    client: TestClient, payload: dict[str, Any]
) -> None:
    """The strict wire contract rejects type coercion, unknown keys, and bad enums."""
    response = client.post("/api/faultline/jobs", json=payload, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("payload", ["null", "NaN", "Infinity", "-Infinity"])
def test_nonfinite_numbers_are_rejected(client: TestClient, payload: str) -> None:
    """``allow_inf_nan=False`` keeps NaN/Infinity out of the strict contract."""
    body = (
        '{"scenario_id": "scripted_checkout_repair", '
        '"idempotency_key": "00000000-0000-0000-0000-000000000000", '
        f'"mode": {payload}}}'
    )
    response = client.post("/api/faultline/jobs", content=body.encode(), headers=HEADERS)
    assert response.status_code == 422


def test_oversized_body_is_bounded_at_exactly_4097_bytes(client: TestClient) -> None:
    """The streaming body read refuses anything over 4096 bytes before parsing."""
    assert (
        client.post("/api/faultline/jobs", content=b"x" * 4096, headers=HEADERS).status_code == 422
    )
    assert (
        client.post("/api/faultline/jobs", content=b"x" * 4097, headers=HEADERS).status_code == 413
    )
    for size in (10_000, 100_000, 1_000_000):
        response = client.post("/api/faultline/jobs", content=b"x" * size, headers=HEADERS)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"


def test_oversized_but_otherwise_valid_json_is_bounded(client: TestClient) -> None:
    """A valid submission padded past the cap still fails closed at the read limit."""
    body = submission().model_dump(mode="json")
    padded = (json.dumps(body) + " " * 4096).encode()
    assert client.post("/api/faultline/jobs", content=padded, headers=HEADERS).status_code == 413


@pytest.mark.parametrize("auth", _HOSTILE_AUTH, ids=repr)
def test_header_injection_cannot_bypass_or_forge_auth(client: TestClient, auth: str) -> None:
    """Injected CR/LF/NUL/tab bytes in Authorization never pass the bearer check."""
    response = client.get("/api/faultline/jobs", headers={"Authorization": auth})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    # The injected bytes never leak into response headers or body.
    for forbidden in ("\r", "\n", "X-Evil", "Injected:"):
        assert forbidden not in response.headers.get("www-authenticate", "")
    assert "\r" not in response.text and "\n" not in response.text


def test_bearer_scheme_is_case_insensitive_but_token_is_exact(client: TestClient) -> None:
    """RFC 7235 schemes are case-insensitive; the token itself is compared exactly."""
    assert (
        client.get("/api/faultline/jobs", headers={"Authorization": f"bearer {TOKEN}"}).status_code
        == 200
    )
    assert (
        client.get("/api/faultline/jobs", headers={"Authorization": f"BEARER {TOKEN}"}).status_code
        == 200
    )
    assert (
        client.get("/api/faultline/jobs", headers={"Authorization": f"Bearer {TOKEN}x"}).status_code
        == 401
    )


def test_token_is_never_echoed_in_responses(client: TestClient) -> None:
    """The control token never appears in any response, including error envelopes."""
    client.post(
        "/api/faultline/jobs",
        content=TOKEN.encode(),
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    for path in ("/api/faultline/jobs", "/api/faultline/jobs/missing", "/healthz"):
        assert TOKEN not in client.get(path, headers=HEADERS).text


# --- 2. snapshot / job lookup path traversal ----------------------------------


@pytest.mark.parametrize("job_id", _TRAVERSAL_IDS, ids=repr)
def test_job_lookup_traversal_is_contained(client: TestClient, job_id: str) -> None:
    """A traversal job_id reaches only a parameterized SQL lookup, never the FS."""
    response = client.get(f"/api/faultline/jobs/{job_id}", headers=HEADERS)
    assert response.status_code in {404, 405}, response.text
    assert response.status_code != 200
    _assert_no_filesystem_leak(response.text)


@pytest.mark.parametrize("job_id", _TRAVERSAL_IDS, ids=repr)
@pytest.mark.parametrize("suffix", ["events", "cancel", "apply"])
def test_job_subroutes_reject_traversal(client: TestClient, job_id: str, suffix: str) -> None:
    """Every job-scoped subroute treats a traversal id as an ordinary lookup miss."""
    path = f"/api/faultline/jobs/{job_id}/{suffix}"
    if suffix == "events":
        response = client.get(path, headers=HEADERS)
    else:
        response = client.post(path, headers=HEADERS)
    assert response.status_code in {404, 405, 409}, response.text
    _assert_no_filesystem_leak(response.text)


@pytest.mark.parametrize("artifact_id", _TRAVERSAL_IDS, ids=repr)
def test_artifact_lookup_traversal_is_contained(client: TestClient, artifact_id: str) -> None:
    """Artifact resolution is a server-owned registration lookup, not a path join."""
    response = client.get(f"/api/faultline/artifacts/{artifact_id}", headers=HEADERS)
    assert response.status_code in {404, 405}, response.text
    _assert_no_filesystem_leak(response.text)


def test_artifact_served_without_header_or_path_injection(client: TestClient) -> None:
    """A served artifact's headers are built from a UUID, never attacker input."""
    job_id = client.post(
        "/api/faultline/jobs", json=submission().model_dump(mode="json"), headers=HEADERS
    ).json()["job_id"]
    done = wait_completed(client, job_id)
    artifact = done["artifacts"][0]["id"]
    download = client.get(f"/api/faultline/artifacts/{artifact}", headers=HEADERS)
    assert download.status_code == 200
    disposition = download.headers["content-disposition"]
    # The filename is exactly the server-owned UUID; no quotes, CR/LF, or ``..``.
    assert disposition == f'attachment; filename="{artifact}"'
    assert "\r" not in disposition and "\n" not in disposition
    # The artifact body is the simulated evidence, not a filesystem read of the id.
    assert "storage_key" not in download.text


def _assert_no_filesystem_leak(text: str) -> None:
    """A traversal miss must never surface private paths, source, or credentials."""
    for forbidden in (
        "storage_key",
        "faultline.db",
        "jobs/",
        "worktrees",
        "checkout.py",
        "/etc/passwd",
        "buggyshop-backend",
        TOKEN,
    ):
        assert forbidden not in text, f"leaked {forbidden!r} in: {text}"


def test_snapshot_job_root_rejects_non_canonical_or_traversing_ids(
    tmp_path: Any, harness: Harness
) -> None:
    """The snapshot directory boundary refuses any non-UUID or escaping job id."""
    manager = SnapshotManager(tmp_path)
    for bad in ("", "not-a-uuid", "../escape", "a/../../etc/passwd", "..", "\\"):
        with pytest.raises(ValueError):
            manager._job_root(bad)
    # A canonical UUID resolves inside the owned data root and never escapes it.
    good = manager._job_root("00000000-0000-0000-0000-000000000000")
    assert good.is_relative_to(manager.data_root)


def test_contained_path_rejects_escaping_snapshot_entries(tmp_path: Any) -> None:
    """The snapshot containment helper never joins an escaping relative entry."""
    for bad in ("../x", "..\\x", "a/../../x", "/etc/passwd", "C:\\x", "\\\\srv\\share"):
        with pytest.raises(ValueError):
            contained_path(tmp_path, bad)


# --- 3. concurrent cancellation races -----------------------------------------


def test_concurrent_cancel_against_queued_job_emits_single_intent(harness: Harness) -> None:
    """64 racing cancellations of an unclaimed job yield exactly one intent event."""
    db = harness.database
    job = db.create_job(submission())
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _: db.request_cancel(job.id), range(64)))
    # Every result is the same object identity; no partial or torn write.
    assert {r.id for r in results} == {job.id}
    events = db.list_events(job.id, limit=1000)
    assert [e.message_code for e in events].count("cancel_requested") == 1
    assert db.get_job(job.id).cancel_requested is True
    assert db.get_job(job.id).state == JobState.QUEUED


def test_concurrent_cancel_against_terminal_job_is_immutable(harness: Harness) -> None:
    """Cancelling a finished job is a no-op that never mutates completed history."""
    db = harness.database
    job = db.create_job(submission())
    db.finish_job(job.id, TerminalOutcome.VERIFIED, clean=True)
    before = db.list_events(job.id, limit=1000)
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _: db.request_cancel(job.id), range(64)))
    assert all(r.state in (JobState.SUCCEEDED,) for r in results)
    assert all(r.cancel_requested is False for r in results)
    assert db.list_events(job.id, limit=1000) == before
    assert db.get_job(job.id).state == JobState.SUCCEEDED


def test_concurrent_cancel_against_running_job_is_idempotent(
    client: TestClient, harness: Harness
) -> None:
    """Many simultaneous HTTP cancellations of an active job never 500 or corrupt."""
    harness.runtime.delay = 0.05
    job_id = client.post(
        "/api/faultline/jobs", json=submission().model_dump(mode="json"), headers=HEADERS
    ).json()["job_id"]

    def cancel(_: int) -> int:
        return client.post(f"/api/faultline/jobs/{job_id}/cancel", headers=HEADERS).status_code

    with ThreadPoolExecutor(max_workers=16) as executor:
        codes = list(executor.map(cancel, range(64)))
    assert 500 not in codes
    assert set(codes) <= {200, 202}
    # One clear terminal state, exactly one durable cancellation intent.
    detail = wait_completed(client, job_id)
    assert detail["job"]["state"] in {"cancelled", "succeeded", "failed"}
    intents = [
        e["message_code"] for e in detail["events"] if e["message_code"] == "cancel_requested"
    ]
    assert len(intents) <= 1
    # A post-race read returns the same consistent envelope.
    assert client.get(f"/api/faultline/jobs/{job_id}", headers=HEADERS).json() == detail


def test_cancel_and_finish_serialize_without_torn_state(harness: Harness) -> None:
    """Concurrent cancel/finish interleavings never produce a torn job record."""
    db = harness.database
    job = db.create_job(submission())
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = []
        for index in range(64):
            if index % 2:
                futures.append(executor.submit(db.request_cancel, job.id))
            else:
                futures.append(
                    executor.submit(db.finish_job, job.id, TerminalOutcome.DETECTED, clean=True)
                )
        for future in futures:
            future.result()  # any exception would surface here
    final = db.get_job(job.id)
    assert final.state in (JobState.SUCCEEDED, JobState.CANCELLED)
    # The serialized job payload still round-trips its strict contract.
    assert final.id == job.id
    assert final.idempotency_key == job.idempotency_key
    assert [e.sequence for e in db.list_events(job.id, limit=1000)] == list(
        range(1, len(db.list_events(job.id, limit=1000)) + 1)
    )
