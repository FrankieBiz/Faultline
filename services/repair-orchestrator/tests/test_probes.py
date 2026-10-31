"""Live HTTP invariants: config loading, target policy, and the two-session gate."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.probes import (
    MAX_RESPONSE_BYTES,
    CheckRecord,
    Invariant,
    ProbeError,
    ProbeRequest,
    load_project_config,
    run_check,
    same_source,
    validate_target,
)
from app.snapshots import REPOSITORY_ROOT
from shared.config import REGISTRY, Scenario

FINGERPRINT = REGISTRY["scripted_checkout_repair"].error_fingerprint
STORE = "http://127.0.0.1:8000"
Handler = Callable[[httpx.Request], httpx.Response]


def checkout(**changes: object) -> Invariant:
    values: dict[str, object] = {
        "id": "checkout.no_coupon",
        "source": "config",
        "title": "Checkout without a coupon",
        "method": "POST",
        "url": f"{STORE}/api/checkout",
        "expected_status": 201,
        "has_body": True,
        "body": {"items": [{"product_id": "trail-mug", "quantity": 2}]},
    }
    values.update(changes)
    return Invariant.model_validate(values)


async def check(
    invariant: Invariant,
    handler: Handler,
    *,
    store: str = STORE,
    port: int | None = None,
    scenarios: dict[str, Scenario] | None = None,
) -> CheckRecord:
    return await run_check(
        invariant,
        port=port,
        live_store_url=store,
        redact=lambda value: value.replace("hunter2", "[redacted]"),
        scenarios=REGISTRY if scenarios is None else scenarios,
        transport=httpx.MockTransport(handler),
    )


def seeded(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"detail": FINGERPRINT})


def seeded_store(request: httpx.Request) -> httpx.Response:
    """The seeded checkout: no coupon crashes; valid coupons price; unknown ones are 400."""
    coupon = json.loads(request.content).get("coupon_code")
    if coupon is None:
        return seeded(request)
    discount = {"TENOFF": 199, "FIFTEEN": 299}.get(coupon)
    if discount is None:
        return httpx.Response(400, json={"detail": "Invalid coupon code"})
    return httpx.Response(
        201, json={"subtotal": 1999, "discount": discount, "total": 1999 - discount}
    )


def repository_scenario() -> Invariant:
    config = load_project_config(REPOSITORY_ROOT / "faultline.toml", REPOSITORY_ROOT)
    return next(item for item in config.invariants if item.id == "scenario.checkout_api")


def test_repository_config_lists_the_project_scenario_and_rules() -> None:
    config = load_project_config(REPOSITORY_ROOT / "faultline.toml", REPOSITORY_ROOT)
    assert config.errors == ()
    assert config.name == "FaultLine checkout API"
    assert config.path == "faultline.toml"
    assert [item.id for item in config.invariants] == ["scenario.checkout_api", "service_health"]
    scenario = config.invariants[0]
    assert scenario.source == "scenario" and scenario.live_note is None
    assert (scenario.method, scenario.url) == ("POST", "http://127.0.0.1:{port}/api/checkout")
    assert scenario.repro is not None and scenario.repro.id == "checkout_api"
    assert [label for _, label, _ in scenario.matchers()][:2] == [
        "no_coupon.status",
        "no_coupon.discount",
    ]


def test_spec_form_rules_label_each_matcher(tmp_path: Path) -> None:
    (tmp_path / "faultline.toml").write_text(
        """
[project]
url = "http://127.0.0.1:{port}"

[[invariants.rule]]
id = "checkout.no_coupon"
request = { method = "POST", path = "/api/checkout", json = { items = [] } }
[[invariants.rule.assert]]
status = 201
[[invariants.rule.assert]]
path = "$.discount"
equals = 0
[[invariants.rule.assert]]
path = "$.total"
equals_path = "$.subtotal"
"""
    )
    (rule,) = load_project_config(tmp_path / "faultline.toml", tmp_path).invariants
    assert (rule.url, rule.expected_status, rule.body) == (
        "http://127.0.0.1:{port}/api/checkout",
        201,
        {"items": []},
    )
    assert [label for _, label, _ in rule.matchers()] == [
        "HTTP status",
        "$.discount equals",
        "$.total equals path",
    ]


def test_every_scenario_form_is_listed_and_bad_ones_say_why(tmp_path: Path) -> None:
    (tmp_path / "outside.json").write_text("{}")
    project = tmp_path / "project"
    project.mkdir()
    (project / "faultline.toml").write_text(
        """
[project]
url = "http://127.0.0.1:{port}"

[[scenarios]]
id = "sum"
title = "Addition"
[[scenarios.steps]]
id = "response"
action = "request"
path = "/sum?a=1&b=2"
[[scenarios.steps]]
id = "sum.correct"
action = "assert"
source = "response"
check = { path = "$.sum", equals = 3 }

[[scenarios]]
id = "journey"
steps = [
  { id = "home", action = "navigate", path = "/" },
  { id = "title", action = "capture", kind = "text", selector = "h1" },
  { id = "title.ok", action = "assert", source = "title", check = { equals = "Shop" } },
]

[[scenarios]]
id = "escape"
repro = "../outside.json"

[[scenarios]]
id = "renamed"
[scenarios.repro]
id = "other"
[[scenarios.repro.steps]]
id = "r"
action = "request"
path = "/"
[[scenarios.repro.steps]]
id = "a"
action = "assert"
source = "r"
check = { status = 200 }
"""
    )
    config = load_project_config(project / "faultline.toml", tmp_path)
    by_id = {item.id: item for item in config.invariants}
    assert list(by_id) == ["scenario.sum", "scenario.journey"]
    assert by_id["scenario.sum"].url == "http://127.0.0.1:{port}/sum?a=1&b=2"
    assert by_id["scenario.sum"].live_note is None
    assert "run only in the sandbox runner" in (by_id["scenario.journey"].live_note or "")
    reasons = "\n".join(config.errors)
    assert "scenarios.escape ignored: ReproSpec file must be inside the project" in reasons
    assert "scenarios.renamed ignored: scenario name differs from its ReproSpec id" in reasons


async def test_browser_scenarios_are_never_sent_live(tmp_path: Path) -> None:
    journey = Invariant(
        id="scenario.journey",
        source="scenario",
        title="Journey",
        method="GET",
        url=STORE + "/",
        live_note="Browser steps (navigate, fill, click, capture) run only in the sandbox runner.",
    )
    with pytest.raises(ProbeError, match="sandbox runner"):
        await check(journey, seeded)


async def test_multi_request_scenario_reproduces_and_binds_the_registered_repair() -> None:
    record = await check(repository_scenario(), seeded_store, port=8000)
    assert record.outcome == "detected" and record.url == f"{STORE}/api/checkout"
    session = record.sessions[0]
    assert [(item.step_id, item.status) for item in session.requests] == [
        ("no_coupon", 500),
        ("tenoff", 201),
        ("fifteen", 201),
        ("unknown", 400),
    ]
    failed = [item.id for item in session.assertions if not item.passed]
    assert failed == [
        "no_coupon.status",
        "no_coupon.discount",
        "no_coupon.total",
        "no_coupon.subtotal",
    ]
    assert (session.status, session.fingerprint) == (500, FINGERPRINT)
    assert record.repair is not None and record.repair.scenario_id == "scripted_checkout_repair"


async def test_project_mode_binds_a_scenario_to_its_own_runner_only() -> None:
    project = Scenario(
        id="checkout_api",
        title="Checkout without a coupon",
        description="",
        target_file="app/routes/checkout.py",
        route="",
        error_fingerprint="",
        executor="repro",
        expected_assertions=["no_coupon.status"],
    )
    record = await check(
        repository_scenario(), seeded_store, port=8000, scenarios={"checkout_api": project}
    )
    assert record.repair is not None and record.repair.scenario_id == "checkout_api"
    assert "project runner owns checkout_api" in (record.repair_note or "")
    probe = await check(checkout(), seeded, scenarios={"checkout_api": project})
    assert probe.repair is None
    assert "no registered sandbox repair covers POST /api/checkout" in (probe.repair_note or "")


async def test_failures_across_routes_are_detection_only() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": FINGERPRINT})

    spec = repository_scenario().repro
    assert spec is not None
    steps = [step.model_dump() for step in spec.steps]
    steps[0]["path"] = "/api/other"
    split = repository_scenario().model_copy(
        update={"repro": spec.model_validate({**spec.model_dump(), "steps": steps})}
    )
    record = await check(split, broken, port=8000)
    assert record.outcome == "detected" and record.repair is None
    assert "span several routes" in (record.repair_note or "")


def test_invalid_rules_are_reported_without_hiding_valid_ones(tmp_path: Path) -> None:
    (tmp_path / "outside.json").write_text("{}")
    project = tmp_path / "project"
    project.mkdir()
    (project / "body.json").write_text('{"items": []}')
    (project / "faultline.toml").write_text(
        """
[project]
name = "acme"
url = "http://127.0.0.1:{port}"

[[invariants.rule]]
id = "ok"
request = { method = "POST", path = "/orders", json = "@body.json" }
[[invariants.rule.assert]]
status = 201

[[invariants.rule]]
id = "no_assertion"
target = "http://127.0.0.1:{port}/"

[[invariants.rule]]
id = "credentials"
target = "http://user:pass@127.0.0.1/"
expected_status = 200

[[invariants.rule]]
id = "escape"
request = { method = "POST", path = "/", json = "@../outside.json" }
[[invariants.rule.assert]]
status = 200

[[invariants.rule]]
id = "probe-reserved"
target = "http://127.0.0.1/"
expected_status = 200

[[invariants.rule]]
id = "ok"
target = "http://127.0.0.1/"
expected_status = 200
"""
    )
    config = load_project_config(project / "faultline.toml", tmp_path)
    assert [item.id for item in config.invariants] == ["ok"]
    assert config.invariants[0].body == {"items": []}
    assert config.path == "project/faultline.toml"
    reasons = "\n".join(config.errors)
    assert len(config.errors) == 5
    for expected in [
        "(no_assertion) ignored: nothing can reproduce a failure (F1)",
        "(credentials) ignored: URL must not contain credentials",
        "(escape) ignored: payload file must be inside the project",
        "(probe-reserved) ignored: id must be a name",
        "(ok) ignored: duplicate id",
    ]:
        assert expected in reasons


def test_missing_and_malformed_config_are_explicit(tmp_path: Path) -> None:
    assert load_project_config(tmp_path / "faultline.toml", tmp_path).path is None
    (tmp_path / "faultline.toml").write_text("[project\n")
    broken = load_project_config(tmp_path / "faultline.toml", tmp_path)
    assert broken.invariants == () and broken.errors[0].startswith("faultline.toml:")


@pytest.mark.parametrize(
    "url,reason",
    [
        ("ftp://example.com/", "http:// or https://"),
        ("http:///path", "http:// or https://"),
        ("https://user:secret@example.com/", "credentials"),
        ("https://example.com/#top", "fragment"),
        ("https://example.com/a b", "no spaces"),
        ("http://127.0.0.1:{port}/", "Replace {port}"),
        ("http://127.0.0.1:99999/", "not valid"),
        ("https://example.com//evil.example/x", "must not start with //"),
    ],
)
def test_targets_are_absolute_http_without_credentials(url: str, reason: str) -> None:
    with pytest.raises(ProbeError, match=reason.replace("{", r"\{").replace("}", r"\}")):
        validate_target(url)


def test_probe_registration_names_and_validates_the_request() -> None:
    probe = ProbeRequest(
        method="GET", url=" https://example.com/status?x=1 ", expected_status=200
    ).invariant()
    assert probe.id.startswith("probe-") and probe.source == "probe"
    assert probe.title == "GET example.com/status?x=1"
    assert not probe.has_body
    with pytest.raises(ProbeError, match="GET requests cannot carry a JSON body"):
        ProbeRequest(
            method="GET", url="https://example.com/", expected_status=200, body={}
        ).invariant()


def test_loopback_aliases_and_default_ports_are_the_same_source() -> None:
    assert same_source("http://localhost:8000/api/checkout", "http://127.0.0.1:8000")
    assert same_source("https://example.com/x", "https://example.com:443")
    assert not same_source("http://127.0.0.1:8001/", "http://127.0.0.1:8000")


async def test_seeded_failure_reproduces_twice_and_binds_the_sandbox_repair() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return seeded(request)

    record = await check(checkout(), handler)
    assert record.outcome == "detected" and record.reason == "same_failure_reproduced_twice"
    assert [str(request.url) for request in seen] == [f"{STORE}/api/checkout"] * 2
    assert json.loads(seen[0].content) == {"items": [{"product_id": "trail-mug", "quantity": 2}]}
    assert seen[0].headers["content-type"] == "application/json"
    case_ids = [request.headers["x-faultline-case-id"] for request in seen]
    assert len(set(case_ids)) == 2 and case_ids == [s.session_id for s in record.sessions]
    first = record.sessions[0]
    assert (first.status, first.fingerprint, first.error) == (500, FINGERPRINT, None)
    assert first.assertions[0].model_dump() == {
        "id": "status",
        "label": "HTTP status",
        "passed": False,
        "expected": "201",
        "observed": "500",
    }
    assert record.repair is not None and record.repair.scenario_id == "scripted_checkout_repair"
    assert record.repair_note and "before any model call" in record.repair_note


async def test_passing_service_is_no_failure_with_no_repair() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"subtotal": 3998, "discount": 0, "total": 3998})

    record = await check(checkout(), handler)
    assert (record.outcome, record.reason) == ("no_failure", "failure_not_reproduced_twice")
    assert record.repair is None and record.repair_note is None
    assert all(item.passed for item in record.sessions[1].assertions)


async def test_same_failure_elsewhere_or_with_another_error_is_detection_only() -> None:
    elsewhere = await check(checkout(url="http://127.0.0.1:9999/api/checkout"), seeded)
    assert elsewhere.outcome == "detected" and elsewhere.repair is None
    assert "not this origin" in (elsewhere.repair_note or "")

    def other(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "KeyError: 'GHOST50'"})

    different = await check(checkout(), other)
    assert different.outcome == "detected" and different.repair is None
    assert "different server error" in (different.repair_note or "")

    uncovered = await check(checkout(url=f"{STORE}/api/orders"), seeded)
    assert uncovered.repair is None
    assert "no registered sandbox repair covers POST /api/orders" in (uncovered.repair_note or "")


async def test_flaky_failures_and_transport_faults_are_not_reproductions() -> None:
    calls: list[int] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return seeded(request) if len(calls) == 1 else httpx.Response(201, json={})

    flaked = await check(checkout(), flaky)
    assert (flaked.outcome, flaked.reason) == ("no_failure", "failure_not_reproduced_twice")

    statuses = iter([500, 503])

    def drifting(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), json={"detail": FINGERPRINT})

    drifted = await check(checkout(), drifting)
    assert (drifted.outcome, drifted.reason) == ("no_failure", "nondeterministic_failure")
    assert drifted.repair is None

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    down = await check(checkout(), refused)
    assert down.outcome == "infrastructure_error"
    assert [session.error for session in down.sessions] == ["ConnectError"]
    assert down.sessions[0].status is None and down.repair is None


async def test_redirects_are_observed_not_followed_and_bodies_are_bounded() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/login"
        return httpx.Response(302, headers={"location": "https://elsewhere.example/"})

    moved = await check(
        checkout(
            method="GET",
            url="https://shop.example/login",
            has_body=False,
            body=None,
            expected_status=200,
        ),
        redirect,
    )
    assert moved.sessions[0].status == 302 and moved.outcome == "detected"

    def huge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            content=b'{"detail": "hunter2' + b"x" * (2 * MAX_RESPONSE_BYTES) + b'"}',
            headers={"content-type": "application/json"},
        )

    record = await check(checkout(), huge)
    session = record.sessions[0]
    assert session.truncated and session.excerpt is not None and len(session.excerpt) <= 600
    assert "hunter2" not in session.excerpt and "[redacted]" in session.excerpt
    # A truncated JSON body is never parsed, so the fingerprint falls back to the status.
    assert session.fingerprint == "HTTP 500"


async def test_port_placeholder_requires_a_port() -> None:
    rule = checkout(url="http://127.0.0.1:{port}/api/checkout")
    with pytest.raises(ProbeError, match="port_required"):
        await check(rule, seeded)
    record = await check(rule, seeded, port=8000)
    assert record.url == f"{STORE}/api/checkout" and record.repair is not None
