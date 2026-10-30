"""Public admission, repair-loop events, and durable sanitized evidence.

The launcher and oracle simulate authored fixture outcomes without executing
candidate code. The existing evaluation tests cover the real HTTP oracle.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from test_evaluation import HostSession, ScriptedAdapter, patch_text

from app.evaluation import (
    ApplicationExporter,
    BackendSession,
    Measurement,
    evaluate_holdout,
)
from app.live_demo import LiveSettings, PublicOutput, create_live_app
from app.model_adapter import ModelError, ModelResponse, ModelSettings, ProbeResult, RepairContext
from app.policy import TARGET_FILE
from app.runtime import CandidateRejected
from app.snapshots import REPOSITORY_ROOT
from fixtures.evaluation.corpus import case_bytes, load_corpus
from fixtures.provenance import verify_manifest
from shared.contracts.models import AssertionResult

SECRET = "live-test-key-never-public-4815"
DEFECT = "seeded_missing_coupon"
BASE = "/api/live"


class FakeLauncher:
    """Require preflight, optionally block, and count simultaneous backend sessions."""

    kind = "test-live"

    def __init__(self, *, available: bool = True, blocked: bool = False) -> None:
        self.available = available
        self.preflight_passed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not blocked:
            self.release.set()
        self.active = 0
        self.maximum_active = 0

    async def preflight(self) -> None:
        if not self.available:
            raise RuntimeError(f"preflight failed {SECRET} /private/runtime/path")
        self.preflight_passed = True

    def session(self, application: Path) -> Any:
        return self._session(application)

    @asynccontextmanager
    async def _session(self, application: Path) -> AsyncGenerator[BackendSession]:
        assert self.preflight_passed
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.entered.set()
        try:
            await self.release.wait()
            source = (application / TARGET_FILE).read_text()
            failing = load_corpus()["holdout"][0]["expected_failures"]
            if "discounts.get(coupon_code, 0)" in source:
                failing = []
            elif "if payload.coupon_code is None:" in source:
                failing = ["regression.empty_coupon", "regression.whitespace_coupon"]
            transport = httpx.MockTransport(lambda _: httpx.Response(200, json=failing))
            async with httpx.AsyncClient(transport=transport, base_url="http://fake") as client:
                yield HostSession(client, lambda: f"{SECRET} /private/backend/checkout.py")
        finally:
            self.active -= 1


@pytest.fixture(autouse=True)
def simulated_oracle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply controlled oracle outcomes while exercising real export and policy."""

    async def regression(client: httpx.AsyncClient) -> list[AssertionResult]:
        failing = (await client.get("/test/checks")).json()
        names = load_corpus()["holdout"][0]["expected_failures"]
        names = names + [f"regression.test_{number}" for number in range(27 - len(names))]
        return [
            AssertionResult(
                id=name,
                passed=name not in failing,
                expected="contract",
                observed="simulation",
                duration_ms=0,
            )
            for name in names
        ]

    monkeypatch.setattr("app.evaluation.regression", regression)


class FakeAdapter(ScriptedAdapter):
    """Use real policy and oracle with authored proposals and untrusted metadata."""

    def __init__(
        self,
        diffs: list[str] | None = None,
        *,
        available: bool = True,
        provider: str = "local",
        explanation: str = "Authored test repair.",
    ) -> None:
        super().__init__(diffs or [patch_text("reference_default_zero")] * 10)
        self.settings = ModelSettings(api_key=SECRET, base_url="http://127.0.0.1:9/v1")
        self.available = available
        self.provider = provider
        self.explanation = explanation
        self.probes = 0

    async def probe(self) -> ProbeResult:
        self.probes += 1
        return ProbeResult(
            self.available,
            self.provider,
            "scripted-test",
            None if self.available else f"provider_unavailable {SECRET} /private/provider/path",
        )

    async def propose_patch(
        self, context: RepairContext, *, fallback: bool = False
    ) -> ModelResponse:
        response = await super().propose_patch(context, fallback=fallback)
        return replace(
            response,
            provider=self.provider,
            proposal=response.proposal.model_copy(update={"explanation": self.explanation}),
            original_diff=f"private model diff {SECRET} /private/original/path",
        )


@asynccontextmanager
async def api(
    directory: Path,
    *,
    launcher: FakeLauncher | None = None,
    adapter: FakeAdapter | None = None,
    settings: LiveSettings | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    provider = adapter or FakeAdapter()
    application = create_live_app(
        launcher=launcher or FakeLauncher(), adapter=provider, data_dir=directory, settings=settings
    )
    try:
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application, client=("192.0.2.1", 12345)),
                base_url="http://live.test",
            ) as client:
                yield client, application
    finally:
        await provider.close()


async def submit(client: httpx.AsyncClient, **kwargs: Any) -> httpx.Response:
    return await client.post(f"{BASE}/runs", json={"defect_id": DEFECT}, **kwargs)


async def finished(client: httpx.AsyncClient, identifier: str) -> dict[str, Any]:
    async with asyncio.timeout(15):
        while True:
            response = await client.get(f"{BASE}/runs/{identifier}")
            assert response.status_code == 200
            result: dict[str, Any] = response.json()
            if result["state"] in {"finished", "failed"}:
                return result
            await asyncio.sleep(0.02)


def sequence(events: list[dict[str, Any]]) -> list[tuple[str, str, int | None]]:
    return [(item["stage"], item["status"], item["attempt"]) for item in events]


async def test_status_lists_only_public_defect_metadata(tmp_path: Path) -> None:
    async with api(tmp_path) as (client, _):
        status = (await client.get(f"{BASE}/status")).json()
        assert status["available"] is True and status["reason"] is None
        assert status["provider"] == "local"
        assert status["classification"] == "local_model_not_meta_hosted"
        assert status["queue"] == {"running": False, "waiting": 0, "max_waiting": 3}
        assert status["limits"] == {
            "per_client_per_hour": 4,
            "daily_cap": 150,
            "daily_remaining": 150,
        }
        assert len(status["defects"]) == 10
        assert {item["id"] for item in status["defects"]} == {
            case["id"] for case in load_corpus()["holdout"]
        }
        assert all(
            set(item) == {"id", "title", "defect_class", "expected_failures"}
            for item in status["defects"]
        )


@pytest.mark.parametrize("runtime_available,provider_available", [(False, True), (True, False)])
async def test_unavailable_fails_closed_without_leaking_preflight_errors(
    tmp_path: Path, runtime_available: bool, provider_available: bool
) -> None:
    launcher = FakeLauncher(available=runtime_available)
    adapter = FakeAdapter(available=provider_available)
    async with api(tmp_path, launcher=launcher, adapter=adapter) as (client, _):
        response = await client.get(f"{BASE}/status")
        assert response.json()["available"] is False
        assert response.json()["reason"]
        assert SECRET not in response.text and "/private/" not in response.text
        admission = await submit(client)
        assert admission.status_code == 503 and admission.json()["error"]["code"] == "unavailable"
        assert not launcher.active
        assert adapter.probes == int(runtime_available)


async def test_unknown_defect_and_invalid_body_are_safe_400s(tmp_path: Path) -> None:
    async with api(tmp_path) as (client, _):
        for body, code in (
            ({"defect_id": "unknown"}, "unknown_defect"),
            ({"defect_id": SECRET}, "unknown_defect"),
            ({"defect_id": [SECRET]}, "invalid_request"),
            ({"defect_id": DEFECT, "code": SECRET}, "invalid_request"),
        ):
            response = await client.post(f"{BASE}/runs", json=body)
            assert response.status_code == 400
            assert response.json()["error"]["code"] == code
            assert SECRET not in response.text
        missing = await client.get(f"{BASE}/runs/not-a-uuid")
        assert missing.status_code == 404
        assert (
            await client.get(f"{BASE}/runs/00000000-0000-0000-0000-000000000000")
        ).status_code == 404


async def test_success_events_sanitized_attempts_and_persisted_run(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    adapter = FakeAdapter(explanation=f"{SECRET} /private/checkout.py " + "é" * 3000)
    async with api(tmp_path, launcher=launcher, adapter=adapter) as (client, application):
        response = await submit(client)
        assert response.status_code == 202 and response.json()["position"] == 0
        run = await finished(client, response.json()["run_id"])
        assert run["outcome"] == "verified" and run["state"] == "finished"
        assert run["provider"] == "local" and run["model"] == "scripted-test"
        assert run["classification"] == "local_model_not_meta_hosted"
        assert run["created_at"] <= run["started_at"] <= run["finished_at"]
        assert sequence(run["events"]) == [
            ("baseline", "running", None),
            ("baseline", "failed", None),
            ("propose", "running", 1),
            ("propose", "passed", 1),
            ("policy", "passed", 1),
            ("verify", "running", 1),
            ("verify", "passed", 1),
            ("done", "passed", None),
        ]
        assert run["events"][1]["data"] == {
            "failing": load_corpus()["holdout"][0]["expected_failures"],
            "total": 27,
        }
        assert run["events"][-2]["data"] == {"failing": [], "total": 27}
        assert [event["t_ms"] for event in run["events"]] == sorted(
            event["t_ms"] for event in run["events"]
        )
        attempt = run["attempts"][0]
        assert set(attempt) == {
            "attempt_number",
            "outcome",
            "provider",
            "model",
            "generation_ms",
            "prompt_tokens",
            "completion_tokens",
            "explanation",
            "diff",
            "diff_recounted",
            "policy",
            "failing_after",
            "prior_feedback",
        }
        assert len(attempt["explanation"].encode()) <= 2048
        assert len(attempt["diff"].encode()) <= 16384
        assert attempt["diff"] == patch_text("reference_default_zero")
        assert attempt["diff_recounted"] is True
        assert attempt["policy"] == {"is_valid": True, "error": None}
        serialized = json.dumps(run)
        assert all(value not in serialized for value in (SECRET, "/private/", "model_diff", "logs"))
        assert launcher.maximum_active == 1 and launcher.active == 0
        saved = json.loads((tmp_path / "runs" / f"{run['id']}.json").read_text())
        assert saved == run
        assert (await client.get(f"{BASE}/status")).json()["limits"]["daily_remaining"] == 149
        assert application.state.live.clients
        assert "192.0.2.1" not in json.dumps(list(application.state.live.clients))
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert all(value not in path.read_text() for value in (SECRET, "192.0.2.1"))


async def test_verification_failure_is_retried_with_feedback(tmp_path: Path) -> None:
    adapter = FakeAdapter([patch_text("null_coupon_only"), patch_text("reference_default_zero")])
    async with api(tmp_path, adapter=adapter) as (client, _):
        response = await submit(client)
        run = await finished(client, response.json()["run_id"])
        assert run["outcome"] == "verified"
        assert [attempt["outcome"] for attempt in run["attempts"]] == [
            "verification_failed",
            "verified",
        ]
        assert sequence(run["events"])[-6:] == [
            ("propose", "running", 2),
            ("propose", "passed", 2),
            ("policy", "passed", 2),
            ("verify", "running", 2),
            ("verify", "passed", 2),
            ("done", "passed", None),
        ]
        assert run["attempts"][1]["prior_feedback"]["gate"] == "verification_failed"
        assert adapter.contexts[1].feedback is not None
        assert SECRET not in json.dumps(run)


async def test_rate_limit_and_queue_full_reserve_capacity_synchronously(tmp_path: Path) -> None:
    launcher = FakeLauncher(blocked=True)
    config = LiveSettings(per_client_per_hour=2, max_waiting=1)
    async with api(tmp_path, launcher=launcher, settings=config) as (client, application):
        first = await submit(client)
        await launcher.entered.wait()
        second = await submit(client)
        assert second.status_code == 202 and second.json()["position"] == 1
        status = (await client.get(f"{BASE}/status")).json()
        assert status["queue"] == {"running": True, "waiting": 1, "max_waiting": 1}
        assert status["limits"]["daily_remaining"] == 148
        limited = await submit(client)
        assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
        assert 1 <= limited.json()["error"]["retry_after_seconds"] <= 3601
        assert limited.headers["retry-after"]
        # A distinct client still encounters the global queue bound.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, client=("192.0.2.2", 1)),
            base_url="http://live.test",
        ) as other:
            full = await submit(other)
            assert full.status_code == 429 and full.json()["error"]["code"] == "queue_full"
        launcher.release.set()
        run1 = await finished(client, first.json()["run_id"])
        run2 = await finished(client, second.json()["run_id"])
        assert run1["finished_at"] <= run2["started_at"]
        assert launcher.maximum_active == 1


async def test_zero_waiting_allows_one_active_run(tmp_path: Path) -> None:
    async with api(
        tmp_path, launcher=FakeLauncher(blocked=True), settings=LiveSettings(max_waiting=0)
    ) as (client, _):
        assert (await submit(client)).status_code == 202
        response = await submit(client)
        assert response.status_code == 429 and response.json()["error"]["code"] == "queue_full"


async def test_ledger_aggregation_and_daily_cap_survive_restart(tmp_path: Path) -> None:
    config = LiveSettings(daily_cap=2)
    async with api(tmp_path, settings=config) as (client, _):
        first = await submit(client)
        run = await finished(client, first.json()["run_id"])
        ledger = (await client.get(f"{BASE}/ledger")).json()
        assert ledger["runs_total"] == ledger["verified"] == 1
        assert ledger["by_defect"] == {DEFECT: {"runs": 1, "verified": 1}}
        assert ledger["by_classification"] == {
            "local_model_not_meta_hosted": {"runs": 1, "verified": 1}
        }
        assert ledger["recent"][0]["attempts"] == 1
        assert "created_at" not in ledger["recent"][0]
    async with api(tmp_path, settings=config) as (client, _):
        assert (await client.get(f"{BASE}/runs/{run['id']}")).json() == run
        assert (await client.get(f"{BASE}/ledger")).json() == ledger
        assert (await client.get(f"{BASE}/status")).json()["limits"]["daily_remaining"] == 1
        second = await submit(client)
        assert second.status_code == 202
        capped = await submit(client)
        assert capped.status_code == 429
        assert capped.json()["error"]["code"] == "daily_cap_reached"
        await finished(client, second.json()["run_id"])
    async with api(tmp_path, settings=config) as (client, _):
        capped = await submit(client)
        assert capped.status_code == 429
        assert capped.json()["error"]["code"] == "daily_cap_reached"
        assert (await client.get(f"{BASE}/ledger")).json()["runs_total"] == 2


async def test_daily_cap_uses_utc_day_and_recent_ledger_is_bounded(tmp_path: Path) -> None:
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    rows = [
        {
            "id": str(number),
            "defect_id": DEFECT,
            "outcome": "verified",
            "provider": "local",
            "model": "scripted-test",
            "classification": "local_model_not_meta_hosted",
            "attempts": 1,
            "created_at": yesterday,
            "finished_at": yesterday,
        }
        for number in range(25)
    ]
    (tmp_path / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    async with api(tmp_path, settings=LiveSettings(daily_cap=1)) as (client, _):
        assert (await client.get(f"{BASE}/status")).json()["limits"]["daily_remaining"] == 1
        ledger = (await client.get(f"{BASE}/ledger")).json()
        assert ledger["runs_total"] == 25 and len(ledger["recent"]) == 20
        assert ledger["recent"][0]["id"] == "24" and ledger["recent"][-1]["id"] == "5"


@pytest.mark.parametrize("trust_proxy", [False, True])
async def test_forwarded_address_requires_explicit_environment_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust_proxy: bool
) -> None:
    monkeypatch.setenv("LIVE_DEMO_TRUST_PROXY", "1" if trust_proxy else "0")
    monkeypatch.setenv("LIVE_DEMO_PER_CLIENT_PER_HOUR", "1")
    async with api(tmp_path, launcher=FakeLauncher(blocked=True)) as (client, _):
        first = await submit(client, headers={"X-Forwarded-For": "198.51.100.1, 203.0.113.1"})
        second = await submit(client, headers={"X-Forwarded-For": "198.51.100.1, 203.0.113.2"})
        assert first.status_code == 202
        assert second.status_code == (202 if trust_proxy else 429)
        # The last hop, rather than the attacker-controlled first hop, is the key.
        third = await submit(client, headers={"X-Forwarded-For": "198.51.100.2, 203.0.113.1"})
        assert third.status_code == 429 and third.json()["error"]["code"] == "rate_limited"


@pytest.mark.parametrize(
    "origin,allowed",
    [
        ("https://frankiebiz.github.io", True),
        ("https://evil.example", False),
        ("https://frankiebiz.github.io.evil.example", False),
    ],
)
async def test_cors_only_allows_configured_origins(
    tmp_path: Path, origin: str, allowed: bool
) -> None:
    async with api(tmp_path) as (client, _):
        response = await client.get(f"{BASE}/status", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == (origin if allowed else None)
        preflight = await client.options(
            f"{BASE}/runs",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert preflight.status_code == (200 if allowed else 400)
        assert preflight.headers.get("access-control-allow-origin") == (origin if allowed else None)
        forbidden = await client.options(
            f"{BASE}/runs",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "DELETE",
            },
        )
        assert forbidden.status_code == 400


async def test_per_run_timeout_is_persisted_and_releases_the_worker(tmp_path: Path) -> None:
    launcher = FakeLauncher(blocked=True)
    async with api(tmp_path, launcher=launcher, settings=LiveSettings(run_timeout_seconds=0.1)) as (
        client,
        _,
    ):
        response = await submit(client)
        run = await finished(client, response.json()["run_id"])
        assert run["state"] == "failed" and run["outcome"] == "timeout"
        assert run["events"][-1]["data"] == {"outcome": "timeout"}
        assert launcher.active == 0
        status = (await client.get(f"{BASE}/status")).json()
        assert status["queue"]["running"] is False
        assert status["available"] is True
        assert (await client.get(f"{BASE}/ledger")).json()["recent"][0]["outcome"] == "timeout"
        second = await submit(client)
        assert second.status_code == 202
        assert (await finished(client, second.json()["run_id"]))["outcome"] == "timeout"


@pytest.mark.parametrize(
    "provider,classification",
    [
        ("meta", "meta_model"),
        ("openai-compatible", "openai_compatible_model_not_meta_hosted"),
        ("deterministic", "deterministic_fallback_no_model_call"),
    ],
)
async def test_classification_comes_from_adapter_responses(
    tmp_path: Path, provider: str, classification: str
) -> None:
    adapter = FakeAdapter(provider=provider)
    async with api(tmp_path, adapter=adapter) as (client, _):
        assert (await client.get(f"{BASE}/status")).json()["classification"] == classification
        response = await submit(client)
        run = await finished(client, response.json()["run_id"])
        assert run["provider"] == provider and run["classification"] == classification
        assert run["attempts"][0]["provider"] == provider


async def test_corrupt_ledger_withholds_admission(tmp_path: Path) -> None:
    (tmp_path / "ledger.jsonl").write_text("not a JSON record\n")
    async with api(tmp_path) as (client, _):
        assert (await client.get(f"{BASE}/status")).json()["available"] is False
        assert (await submit(client)).status_code == 503
        assert (await client.get(f"{BASE}/ledger")).status_code == 503


async def test_output_bounds_and_redaction_preserve_patch_arithmetic() -> None:
    adapter = FakeAdapter()
    try:
        output = PublicOutput(adapter)
        diff = "+discount = subtotal // 10\n+price = cents / 100\n"
        attempt = output.attempt(
            {
                "explanation": f"{SECRET} /private/checkout.py C:\\private\\checkout.py "
                + "é" * 3000,
                "diff": diff + f"+# {SECRET} /private/checkout.py\n" + "é" * 10000,
                "model_diff": "private original",
                "logs": "private logs",
                "policy": {"is_valid": False, "error": f"{SECRET} /private/source.py"},
                "prior_feedback": {"policy_error": f"{SECRET} /private/source.py", "logs": SECRET},
            }
        )
        assert attempt["diff"].startswith(diff)
        assert len(attempt["diff"].encode()) <= 16384
        assert len(attempt["explanation"].encode()) <= 2048
        assert all(
            text not in json.dumps(attempt) for text in (SECRET, "/private/", "C:\\", "logs")
        )
        assert "model_diff" not in attempt
    finally:
        await adapter.close()


@pytest.mark.parametrize("mode", ["verified", "policy", "candidate", "verification", "provider"])
async def test_evaluate_holdout_event_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    case = load_corpus()["holdout"][0]
    baseline = Measurement(
        (
            AssertionResult(
                id="regression.missing_coupon",
                passed=False,
                expected="201",
                observed="500",
                duration_ms=0,
            ),
        ),
        500,
        f"backend log {SECRET} /private/backend.py",
    )
    passed = Measurement((), 201, "")
    measurements = 0

    async def measure(*args: Any, **kwargs: Any) -> Measurement:
        nonlocal measurements
        measurements += 1
        if measurements == 1:
            return baseline
        if mode == "candidate":
            raise CandidateRejected("candidate_rejected")
        return baseline if mode == "verification" else passed

    monkeypatch.setattr("app.evaluation.measure", measure)
    diff = patch_text("reference_default_zero")
    if mode == "policy":
        diff = diff.replace("@@ -40,7", "@@ -40,9")
    adapter = FakeAdapter([diff])

    async def provider_error(*args: Any, **kwargs: Any) -> ModelResponse:
        raise ModelError("provider_timeout", retryable=True)

    if mode == "provider":
        monkeypatch.setattr(adapter, "propose_patch", provider_error)
    commit = verify_manifest().get("source_commit")
    assert commit is not None
    exporter = ApplicationExporter(REPOSITORY_ROOT, commit, tmp_path)
    events: list[dict[str, Any]] = []
    try:
        result = await evaluate_holdout(
            case,
            case_bytes(case).decode(),
            adapter,
            FakeLauncher(),
            exporter,
            load_corpus()["incident_request"],
            attempts=1,
            on_event=events.append,
        )
    finally:
        await adapter.close()
    expected: list[tuple[str, str, int | None]] = [
        ("baseline", "running", None),
        ("baseline", "failed", None),
        ("propose", "running", 1),
    ]
    if mode == "provider":
        expected.append(("propose", "error", 1))
        assert events[-1]["data"] == {"code": "provider_timeout"}
    else:
        expected.extend(
            [
                ("propose", "passed", 1),
                ("policy", "rejected" if mode == "policy" else "passed", 1),
            ]
        )
        if mode != "policy":
            expected.extend(
                [
                    ("verify", "running", 1),
                    (
                        "verify",
                        {"candidate": "rejected", "verification": "failed"}.get(mode, "passed"),
                        1,
                    ),
                ]
            )
    assert sequence(events) == expected
    assert (
        result["outcome"]
        == {
            "verified": "verified",
            "policy": "patch_policy_rejected",
            "candidate": "candidate_rejected",
            "verification": "verification_failed",
            "provider": "model_error",
        }[mode]
    )


async def test_required_provider_withholds_admission_from_other_providers(tmp_path: Path) -> None:
    for provider, available in (("deterministic", False), ("meta", True)):
        settings = LiveSettings(require_provider="meta")
        async with api(tmp_path, adapter=FakeAdapter(provider=provider), settings=settings) as (
            client,
            _,
        ):
            status = (await client.get(f"{BASE}/status")).json()
            assert status["available"] is available
            if not available:
                assert status["reason"] == "The configured provider is deterministic, not meta."
                assert (await submit(client)).status_code == 503


async def test_infrastructure_failure_requests_a_supervised_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr("app.live_demo.os.kill", lambda pid, sig: signals.append((pid, sig)))

    async def broken(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("scope cleanup unconfirmed")

    monkeypatch.setattr("app.live_demo.evaluate_holdout", broken)
    for exit_on_failure, expected in ((False, 0), (True, 1)):
        signals.clear()
        settings = LiveSettings(exit_on_failure=exit_on_failure)
        async with api(tmp_path / str(exit_on_failure), settings=settings) as (client, _):
            run = await finished(client, (await submit(client)).json()["run_id"])
            assert run["outcome"] == "runtime_error"
            assert (await client.get(f"{BASE}/status")).json()["available"] is False
        assert len(signals) == expected


async def test_unavailable_start_retries_through_a_supervised_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signals: list[int] = []
    monkeypatch.setattr("app.live_demo.os.kill", lambda pid, sig: signals.append(sig))
    settings = LiveSettings(exit_on_failure=True, unavailable_retry_seconds=0.05)
    async with api(tmp_path, adapter=FakeAdapter(available=False), settings=settings) as (
        client,
        _,
    ):
        assert (await client.get(f"{BASE}/status")).json()["available"] is False
        await asyncio.sleep(0.2)
    assert len(signals) == 1
