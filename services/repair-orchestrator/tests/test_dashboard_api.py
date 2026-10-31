"""Dashboard routes: scenario listing, live probes, and live-store delivery."""

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from conftest import Harness, submission
from fastapi.testclient import TestClient
from test_api import HEADERS, TOKEN, wait_completed

from app import cli
from app.main import Settings, create_app
from shared.config import REGISTRY
from shared.contracts.models import JobRequest

FINGERPRINT = REGISTRY["scripted_checkout_repair"].error_fingerprint
CONFIG = """
[project]
name = "acme"
url = "http://127.0.0.1:{port}"

[[invariants.rule]]
id = "health"
target = "http://127.0.0.1:{port}/healthz"
expected_status = 200

[[invariants.rule]]
id = "broken"
target = "http://127.0.0.1/"

[[scenarios]]
id = "journey"
title = "Storefront journey"
[[scenarios.steps]]
id = "home"
action = "navigate"
path = "/"
[[scenarios.steps]]
id = "heading"
action = "capture"
kind = "text"
selector = "h1"
[[scenarios.steps]]
id = "heading.ok"
action = "assert"
source = "heading"
check = { equals = "Shop" }
"""


class Store:
    """A switchable in-process stand-in for the live store API."""

    def __init__(self) -> None:
        self.fixed = False
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if self.fixed:
            return httpx.Response(201, json={"subtotal": 3998, "discount": 0, "total": 3998})
        return httpx.Response(500, json={"detail": FINGERPRINT})


@pytest.fixture
def store() -> Store:
    return Store()


@pytest.fixture
def live_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point delivery at a temporary copy, never the worktree's real store source."""
    root = tmp_path / "repo"
    target = root / "apps" / "buggyshop-backend" / "app" / "routes" / "checkout.py"
    target.parent.mkdir(parents=True)
    shutil.copyfile(cli.SEEDED_FILE, target)
    monkeypatch.setattr(cli, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(cli, "TARGET_FILE", target)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "cli-data")
    return target


@pytest.fixture
def client(harness: Harness, store: Store, tmp_path: Path) -> Iterator[TestClient]:
    config = tmp_path / "faultline.toml"
    config.write_text(CONFIG)
    app = create_app(
        Settings(
            data_dir=harness.root,
            control_token=TOKEN,
            config_path=config,
            live_store_url="http://127.0.0.1:8000",
        ),
        database=harness.database,
        adapter=harness.adapter,
        runtime=harness.runtime,
        snapshots=harness.snapshots,
        probe_transport=httpx.MockTransport(store),
    )
    with TestClient(app) as value:
        yield value


def register(client: TestClient, **changes: Any) -> dict[str, Any]:
    body = {
        "title": "Checkout without a coupon",
        "method": "POST",
        "url": "http://127.0.0.1:8000/api/checkout",
        "expected_status": 201,
        "body": {"items": [{"product_id": "trail-mug", "quantity": 2}]},
        **changes,
    }
    response = client.post("/api/faultline/invariants", json=body, headers=HEADERS)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/invariants"),
        ("POST", "/invariants/health/check"),
        ("GET", "/invariants/health/checks"),
        ("POST", "/invariants/health/remove"),
        ("GET", "/store"),
        ("POST", "/jobs/unknown/apply"),
        ("POST", "/revert"),
    ],
)
def test_dashboard_routes_require_bearer(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, "/api/faultline" + path)
    assert response.status_code == 401


def test_scenarios_list_packs_config_rules_and_errors(client: TestClient) -> None:
    listing = client.get("/api/faultline/scenarios", headers=HEADERS).json()
    assert [item["id"] for item in listing["scenarios"]] == ["scripted_checkout_repair"]
    assert listing["project"]["name"] == "acme"
    assert listing["project"]["errors"] == [
        f"{listing['project']['config_path']} invariants.rule[1] (broken) ignored: "
        "nothing can reproduce a failure (F1): declare an assertion"
    ]
    journey, health = listing["invariants"]
    assert health["source"] == "config" and health["needs_port"] is True
    assert health["latest_check"] is None
    assert journey["id"] == "scenario.journey" and journey["source"] == "scenario"
    assert [step["id"] for step in journey["repro"]["steps"]] == ["home", "heading", "heading.ok"]
    assert "sandbox runner" in journey["live_note"]


def test_browser_scenarios_are_refused_live_with_the_reason(client: TestClient) -> None:
    response = client.post(
        "/api/faultline/invariants/scenario.journey/check", json={"port": 8000}, headers=HEADERS
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"] == (
        "Browser steps (navigate, fill, click, capture) run only in the sandbox runner."
    )


def test_registered_probe_reproduces_live_and_binds_repair(
    client: TestClient, store: Store
) -> None:
    probe = register(client)
    assert probe["source"] == "probe" and probe["has_body"] is True
    check = client.post(f"/api/faultline/invariants/{probe['id']}/check", headers=HEADERS)
    assert check.status_code == 200
    record = check.json()
    assert record["outcome"] == "detected"
    assert record["repair"]["scenario_id"] == "scripted_checkout_repair"
    assert [session["status"] for session in record["sessions"]] == [500, 500]
    assert len(store.requests) == 2

    store.fixed = True
    again = client.post(f"/api/faultline/invariants/{probe['id']}/check", headers=HEADERS)
    assert again.json()["outcome"] == "no_failure"
    history = client.get(f"/api/faultline/invariants/{probe['id']}/checks", headers=HEADERS)
    assert [item["outcome"] for item in history.json()["checks"]] == ["no_failure", "detected"]
    listing = client.get("/api/faultline/scenarios", headers=HEADERS).json()
    listed = next(item for item in listing["invariants"] if item["id"] == probe["id"])
    assert listed["latest_check"]["outcome"] == "no_failure"

    removed = client.post(f"/api/faultline/invariants/{probe['id']}/remove", headers=HEADERS)
    assert removed.json() == {"status": "removed"}
    missing = client.get(f"/api/faultline/invariants/{probe['id']}/checks", headers=HEADERS)
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"url": "https://user:pw@example.com/"}, "URL must not contain credentials"),
        (
            {"url": "file:///etc/passwd"},
            "URL must start with http:// or https:// and name a host",
        ),
        ({"method": "GET"}, "GET requests cannot carry a JSON body"),
    ],
)
def test_invalid_probes_say_why(client: TestClient, changes: dict[str, Any], message: str) -> None:
    body = {"method": "POST", "url": "https://example.com/", "expected_status": 200, "body": {}}
    response = client.post("/api/faultline/invariants", json={**body, **changes}, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["error"] == {"code": "invalid_probe", "message": message, "job_id": None}


def test_malformed_probe_bodies_are_rejected_without_echo(client: TestClient) -> None:
    response = client.post(
        "/api/faultline/invariants",
        json={"method": "TRACE", "url": "https://example.com/", "expected_status": 200},
        headers=HEADERS,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_probe"
    assert "example.com" not in response.text


def test_config_rules_need_a_port_and_cannot_be_removed(client: TestClient) -> None:
    unresolved = client.post("/api/faultline/invariants/health/check", headers=HEADERS)
    assert unresolved.status_code == 422
    assert unresolved.json()["error"]["code"] == "port_required"
    checked = client.post(
        "/api/faultline/invariants/health/check", json={"port": 8000}, headers=HEADERS
    )
    assert checked.json()["outcome"] == "no_failure"
    assert checked.json()["url"] == "http://127.0.0.1:8000/healthz"
    removal = client.post("/api/faultline/invariants/health/remove", headers=HEADERS)
    assert removal.status_code == 409 and removal.json()["error"]["code"] == "config_invariant"
    unknown = client.post("/api/faultline/invariants/missing/check", headers=HEADERS)
    assert unknown.status_code == 404


def test_probe_count_is_bounded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main

    monkeypatch.setattr(app.main, "MAX_PROBES", 1)
    register(client)
    response = client.post(
        "/api/faultline/invariants",
        json={"method": "GET", "url": "https://example.com/", "expected_status": 200},
        headers=HEADERS,
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "too_many_probes"


def test_project_runner_jobs_are_never_delivered_to_the_store(
    client: TestClient, live_source: Path, harness: Harness
) -> None:
    harness.database.scenario_ids.add("project_x")
    job = harness.database.create_job(
        JobRequest(scenario_id="project_x", idempotency_key=str(uuid4()))
    )
    refused = client.post(f"/api/faultline/jobs/{job.id}/apply", headers=HEADERS)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "delivery_unsupported"
    assert live_source.read_text() == cli.SEEDED_FILE.read_text()


def test_store_delivery_applies_only_verified_jobs_to_the_seed(
    client: TestClient, live_source: Path, harness: Harness
) -> None:
    seeded = live_source.read_text()
    status = client.get("/api/faultline/store", headers=HEADERS).json()
    assert status["state"] == "seeded" and status["applied_job_id"] is None
    assert status["target_file"] == "apps/buggyshop-backend/app/routes/checkout.py"

    harness.runtime.verification_failed = True
    failed = client.post(
        "/api/faultline/jobs", json=submission().model_dump(mode="json"), headers=HEADERS
    ).json()["job_id"]
    assert wait_completed(client, failed)["job"]["outcome"] != "verified"
    refused = client.post(f"/api/faultline/jobs/{failed}/apply", headers=HEADERS)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "unverified_job"
    assert live_source.read_text() == seeded

    harness.runtime.verification_failed = False
    job_id = client.post(
        "/api/faultline/jobs", json=submission().model_dump(mode="json"), headers=HEADERS
    ).json()["job_id"]
    assert wait_completed(client, job_id)["job"]["outcome"] == "verified"
    applied = client.post(f"/api/faultline/jobs/{job_id}/apply", headers=HEADERS)
    assert applied.status_code == 200, applied.text
    store = applied.json()["store"]
    assert store["state"] == "patched" and store["applied_job_id"] == job_id
    assert live_source.read_text() != seeded
    assert str(live_source) not in applied.text

    twice = client.post(f"/api/faultline/jobs/{job_id}/apply", headers=HEADERS)
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "store_not_seeded"

    live_source.write_text(live_source.read_text() + "\n# hand edit\n")
    edited = client.get("/api/faultline/store", headers=HEADERS).json()
    assert edited["state"] == "modified" and edited["applied_job_id"] is None

    reverted = client.post("/api/faultline/revert", headers=HEADERS)
    assert reverted.json()["store"]["state"] == "seeded"
    assert live_source.read_text() == seeded
