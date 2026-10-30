"""ReproSpec contract, browser adapter, and F1 gate tests; no host app execution."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.repro import (
    AssertionCheck,
    AssertStep,
    CaptureStep,
    ClickStep,
    FillStep,
    Measurement,
    NavigateStep,
    PlaywrightSession,
    ReproductionNotConfirmed,
    ReproductionResult,
    ReproEngine,
    ReproSession,
    ReproSpec,
    ReproStep,
    RequestStep,
    SelectStep,
    WaitForStep,
    evaluate_assertion,
)


def spec(**changes: Any) -> ReproSpec:
    return ReproSpec.model_validate(
        {
            "id": "checkout",
            "steps": [
                {"action": "request", "id": "checkout", "method": "POST", "path": "/api/checkout"},
                {
                    "action": "assert",
                    "id": "created",
                    "source": "checkout",
                    "check": {"status": 201},
                },
            ],
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": True},
        {"version": 2},
        {"timeout_ms": "20"},
        {"timeout_ms": 0},
        {"timeout_ms": 180001},
        {"steps": []},
        {"steps": [{"action": "navigate", "id": "home", "path": "/"}]},
        {"steps": [{"action": "execute", "id": "code", "code": "anything"}]},
        {"steps": [{"action": "assert", "id": "a", "source": "later", "check": {"status": 200}}]},
    ],
)
def test_invalid_specs_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        spec(**changes)


@pytest.mark.parametrize(
    "path", ["https://example.com", "//example.com", "/\\evil", "relative", "/a\nb"]
)
def test_paths_cannot_override_service_origin(path: str) -> None:
    with pytest.raises(ValidationError):
        RequestStep(id="r", path=path)
    with pytest.raises(ValidationError):
        NavigateStep(id="n", path=path)


def test_duplicate_ids_and_screenshot_assertions_are_rejected() -> None:
    original = spec().model_dump()
    original["steps"][1]["id"] = "checkout"
    with pytest.raises(ValidationError, match="duplicate"):
        ReproSpec.model_validate(original)
    with pytest.raises(ValidationError, match="earlier request/capture"):
        ReproSpec(
            id="s",
            steps=[
                CaptureStep(id="shot", kind="screenshot"),
                AssertStep(id="a", source="shot", check=AssertionCheck(exists=True)),
            ],
        )


@pytest.mark.parametrize(
    "check",
    [
        {},
        {"status": 200, "equals": 1},
        {"status": "200"},
        {"status": 99},
        {"status": None},
        {"status": 200, "path": "$"},
        {"equals": 1, "unknown": 2},
        {"matches": "["},
        {"path": "$..x", "exists": True},
        {"path": "$.a[*]", "exists": True},
        {"type": "anything"},
        {"exists": 1},
    ],
)
def test_invalid_assertion_contract(check: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AssertionCheck.model_validate(check)


@pytest.mark.parametrize(
    ("check", "value", "passed"),
    [
        ({"equals": None}, None, True),
        ({"path": "$.missing", "equals": None}, {}, False),
        ({"path": "$.items[1].price", "equals": 10}, {"items": [{}, {"price": 10}]}, True),
        ({"equals": 1}, True, False),
        ({"equals": {"x": 1}}, {"x": True}, False),
        ({"path": "$.total", "equals_path": "$.subtotal"}, {"total": 100, "subtotal": 100}, True),
        ({"path": "$.a", "equals_path": "$.b"}, {}, False),
        ({"path": "$.a", "exists": False}, {}, True),
        ({"path": "$.a", "exists": True}, {"a": None}, True),
        ({"path": "$.a[3]", "exists": False}, {"a": [1]}, True),
        ({"path": "$.a.x", "exists": False}, {"a": None}, True),
        ({"matches": "^order-[0-9]+$"}, "order-12", True),
        ({"matches": "order"}, 123, False),
        ({"type": "integer"}, True, False),
        ({"type": "integer"}, 1, True),
        ({"type": "number"}, 1.5, True),
        ({"type": "number"}, True, False),
        ({"type": "null"}, None, True),
        ({"type": "boolean"}, False, True),
        ({"type": "object"}, {}, True),
        ({"type": "array"}, [], True),
        ({"type": "string"}, "ok", True),
    ],
)
def test_assertion_matchers(check: dict[str, Any], value: Any, passed: bool) -> None:
    step = AssertStep(id="a", source="r", check=AssertionCheck.model_validate(check))
    result = evaluate_assertion(step, Measurement(value))
    assert result.passed is passed


def test_json_round_trip_preserves_explicit_null_and_default_actions() -> None:
    original = ReproSpec(
        id="test",
        steps=[
            RequestStep(id="r", path="/"),
            AssertStep(id="a", source="r", check=AssertionCheck(equals=None)),
        ],
    )
    restored = ReproSpec.model_validate_json(original.model_dump_json())
    assert restored == original
    assertion = restored.steps[1]
    assert isinstance(assertion, AssertStep)
    assert assertion.check.model_fields_set == {"equals"}
    assert (
        ReproSpec.model_json_schema()["properties"]["steps"]["items"]["discriminator"][
            "propertyName"
        ]
        == "action"
    )


class FakeSession:
    def __init__(
        self, session_id: str, status: int = 500, fingerprint: str | None = "TypeError"
    ) -> None:
        self.session_id = session_id
        self.status = status
        self.error_fingerprint = fingerprint
        self.steps: list[str] = []
        self.error: BaseException | None = None
        self.delay = False

    async def perform(self, step: ReproStep) -> Measurement | bytes | None:
        self.steps.append(step.action)
        if self.delay:
            await asyncio.Event().wait()
        if self.error:
            raise self.error
        if isinstance(step, RequestStep):
            return Measurement({"error": "checkout failed"}, self.status)
        if isinstance(step, CaptureStep):
            return b"png" if step.kind == "screenshot" else Measurement("observed")
        return None

    async def fingerprint(self) -> str | None:
        return self.error_fingerprint


class Sessions:
    def __init__(self, *sessions: FakeSession) -> None:
        self.sessions = list(sessions)
        self.entered = 0
        self.closed = 0
        self.cleanup_error = False

    @asynccontextmanager
    async def open(self) -> AsyncIterator[ReproSession]:
        session = self.sessions[self.entered]
        self.entered += 1
        try:
            yield session
        finally:
            self.closed += 1
            if self.cleanup_error:
                raise RuntimeError("cleanup unconfirmed")


async def test_gate_only_calls_proposal_after_two_failures_and_cleanup() -> None:
    sessions = Sessions(FakeSession("one"), FakeSession("two"))
    calls = 0

    async def propose(result: ReproductionResult) -> str:
        nonlocal calls
        calls += 1
        assert sessions.closed == 2
        assert result.repair_allowed
        assert len(result.runs) == 2
        return "candidate"

    result = await ReproEngine(sessions.open).repair(spec(fingerprint="TypeError"), propose)
    assert result == "candidate"
    assert calls == 1


@pytest.mark.parametrize(
    ("statuses", "fingerprints", "expected", "reason"),
    [
        ((201, 201), (None, None), None, "failure_not_reproduced_twice"),
        ((500, 201), (None, None), None, "failure_not_reproduced_twice"),
        ((201, 500), (None, None), None, "failure_not_reproduced_twice"),
        ((500, 503), (None, None), None, "nondeterministic_failure"),
        ((500, 500), ("TypeError", "ValueError"), None, "nondeterministic_failure"),
        ((500, 500), ("OtherError", "OtherError"), "TypeError", "fingerprint_mismatch"),
        ((500, 500), (None, None), "TypeError", "fingerprint_mismatch"),
    ],
)
async def test_unreproduced_failures_never_call_model(
    statuses: tuple[int, int],
    fingerprints: tuple[str | None, str | None],
    expected: str | None,
    reason: str,
) -> None:
    sessions = Sessions(*(FakeSession(str(i), statuses[i], fingerprints[i]) for i in range(2)))
    propose = AsyncMock()
    with pytest.raises(ReproductionNotConfirmed) as exc:
        await ReproEngine(sessions.open).repair(spec(fingerprint=expected), propose)
    assert exc.value.result.outcome == "no_failure"
    assert exc.value.result.reason == reason
    assert sessions.closed == 2
    propose.assert_not_called()


@pytest.mark.parametrize("kind", ["transport", "selector", "timeout", "cleanup", "reused", "setup"])
async def test_infrastructure_failures_block_repair(kind: str) -> None:
    one, two = FakeSession("one"), FakeSession("two")
    sessions = Sessions(one, two)
    if kind in {"transport", "selector"}:
        one.error = RuntimeError("sensitive driver error")
    elif kind == "timeout":
        one.delay = True
    elif kind == "cleanup":
        sessions.cleanup_error = True
    elif kind == "reused":
        two.session_id = one.session_id
    else:
        sessions.sessions = []
    propose = AsyncMock()
    with pytest.raises(ReproductionNotConfirmed) as exc:
        await ReproEngine(sessions.open).repair(spec(timeout_ms=10), propose)
    assert exc.value.result.outcome == "infrastructure_error"
    propose.assert_not_called()
    assert "sensitive" not in str(exc.value.result)
    if kind != "reused":
        assert len(exc.value.result.runs) == 1  # Never re-enter after unconfirmed cleanup.


async def test_cancellation_propagates_and_cleans_up() -> None:
    one = FakeSession("one")
    one.error = asyncio.CancelledError()
    sessions = Sessions(one)
    with pytest.raises(asyncio.CancelledError):
        await ReproEngine(sessions.open).reproduce(spec())
    assert sessions.closed == 1


async def test_failed_assertions_do_not_skip_evidence_or_later_checks() -> None:
    original = spec()
    original.steps.extend(
        [
            CaptureStep(id="shot", kind="screenshot"),
            CaptureStep(id="text", selector="#result"),
            AssertStep(id="text_ok", source="text", check=AssertionCheck(equals="expected")),
        ]
    )
    sessions = Sessions(FakeSession("one"), FakeSession("two"))
    result = await ReproEngine(sessions.open).reproduce(original)
    assert result.repair_allowed
    assert [item.id for item in result.runs[0].assertions] == ["created", "text_ok"]
    assert result.runs[0].captures["shot"] == b"png"


def browser() -> tuple[PlaywrightSession, Any, Any]:
    locator = Mock()
    for name in (
        "fill",
        "click",
        "select_option",
        "wait_for",
        "inner_text",
        "input_value",
        "is_visible",
    ):
        setattr(locator, name, AsyncMock())
    locator.inner_text.return_value = "Order failed"
    locator.input_value.return_value = "TENOFF"
    locator.is_visible.return_value = True
    page = Mock(url="http://127.0.0.1:8000/result")
    page.goto = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"png")
    page.locator.return_value = locator
    response = Mock(status=500)
    response.json = AsyncMock(return_value={"error": "failure"})
    response.text = AsyncMock(return_value="not json")
    response.dispose = AsyncMock()
    page.request.fetch = AsyncMock(return_value=response)
    return (
        PlaywrightSession(
            page,
            base_url="http://127.0.0.1:8000",
            session_id="fresh",
            read_fingerprint=AsyncMock(return_value="TypeError"),
        ),
        page,
        locator,
    )


async def test_browser_step_primitives() -> None:
    session, page, locator = browser()
    await session.perform(NavigateStep(id="n", path="/checkout", timeout_ms=123))
    page.goto.assert_awaited_once_with(
        "http://127.0.0.1:8000/checkout",
        timeout=123,
        wait_until="domcontentloaded",
    )
    await session.perform(FillStep(id="f", selector="#coupon", value="TENOFF"))
    locator.fill.assert_awaited_once_with("TENOFF", timeout=10000)
    await session.perform(ClickStep(id="c", selector="button"))
    locator.click.assert_awaited_once_with(timeout=10000)
    await session.perform(SelectStep(id="s", selector="select", value="2"))
    locator.select_option.assert_awaited_once_with("2", timeout=10000)
    await session.perform(WaitForStep(id="w", selector="#order", state="hidden"))
    locator.wait_for.assert_awaited_once_with(state="hidden", timeout=10000)
    assert await session.fingerprint() == "TypeError"


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("text", Measurement("Order failed")),
        ("value", Measurement("TENOFF")),
        ("visible", Measurement(True)),
        ("url", Measurement("http://127.0.0.1:8000/result")),
        ("screenshot", b"png"),
    ],
)
async def test_capture_primitives(kind: Any, value: Any) -> None:
    session, _, _ = browser()
    step = CaptureStep(
        id="capture", kind=kind, selector=None if kind in {"url", "screenshot"} else "#target"
    )
    assert await session.perform(step) == value


@pytest.mark.parametrize("body", [None, "text", 1, {"items": []}])
async def test_request_serializes_json_and_releases_response(body: Any) -> None:
    import json

    session, page, _ = browser()
    result = await session.perform(
        RequestStep(id="r", path="/api/checkout", method="POST", body=body)
    )
    assert result == Measurement({"error": "failure"}, 500)
    options = page.request.fetch.call_args.kwargs
    assert json.loads(options["data"]) == body
    assert options["max_redirects"] == 0
    assert options["fail_on_status_code"] is False
    page.request.fetch.return_value.dispose.assert_awaited_once()


async def test_request_without_body_and_non_json_response() -> None:
    session, page, _ = browser()
    page.request.fetch.return_value.json.side_effect = ValueError("invalid json")
    result = await session.perform(RequestStep(id="r", path="/"))
    assert result == Measurement("not json", 500)
    assert "data" not in page.request.fetch.call_args.kwargs
    page.request.fetch.return_value.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    "url",
    ["https://example.com", "file:///etc/passwd", "http://user@localhost", "http://localhost/app"],
)
def test_browser_adapter_rejects_non_service_origins(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        PlaywrightSession(Mock(), base_url=url, session_id="x", read_fingerprint=AsyncMock())


@pytest.mark.parametrize("explicit_null", [False, True])
def test_request_round_trip_preserves_absent_body(explicit_null: bool) -> None:
    original = spec()
    request = original.steps[0]
    assert isinstance(request, RequestStep)
    if explicit_null:
        request.body = None
    restored = ReproSpec.model_validate_json(original.model_dump_json())
    assert ("body" in restored.steps[0].model_fields_set) is explicit_null


async def test_entire_journey_through_browser_adapter() -> None:
    original = ReproSpec(
        id="journey",
        steps=[
            NavigateStep(id="home", path="/"),
            FillStep(id="coupon", selector="#coupon", value=""),
            SelectStep(id="quantity", selector="#quantity", value="2"),
            ClickStep(id="buy", selector="#buy"),
            WaitForStep(id="result", selector="#result"),
            RequestStep(id="request", path="/api/checkout", method="POST"),
            CaptureStep(id="shot", kind="screenshot"),
            AssertStep(id="created", source="request", check=AssertionCheck(status=201)),
        ],
    )
    pages: list[Any] = []

    @asynccontextmanager
    async def open_session() -> AsyncIterator[ReproSession]:
        session, page, _ = browser()
        session.session_id = str(len(pages))
        pages.append(page)
        yield session

    result = await ReproEngine(open_session).reproduce(original)
    assert result.repair_allowed
    assert len(pages) == 2
    for page in pages:
        assert "data" not in page.request.fetch.call_args.kwargs
        page.goto.assert_awaited_once()
        page.screenshot.assert_awaited_once()


async def test_second_run_error_withholds_proposal() -> None:
    second = FakeSession("two")
    second.error = RuntimeError("request failed")
    sessions = Sessions(FakeSession("one"), second)
    propose = AsyncMock()
    with pytest.raises(ReproductionNotConfirmed) as exc:
        await ReproEngine(sessions.open).repair(spec(), propose)
    assert exc.value.result.outcome == "infrastructure_error"
    assert len(exc.value.result.runs) == 2
    propose.assert_not_called()


async def test_gate_compares_failed_assertions_even_when_fingerprint_matches() -> None:
    class ValuesSession(FakeSession):
        async def perform(self, step: ReproStep) -> Measurement | bytes | None:
            if isinstance(step, RequestStep):
                return Measurement({"a": self.session_id == "one", "b": self.session_id == "two"})
            return await super().perform(step)

    original = ReproSpec(
        id="different-failures",
        steps=[
            RequestStep(id="r", path="/"),
            AssertStep(id="a", source="r", check=AssertionCheck(path="$.a", equals=True)),
            AssertStep(id="b", source="r", check=AssertionCheck(path="$.b", equals=True)),
        ],
    )
    sessions = Sessions(ValuesSession("one"), ValuesSession("two"))
    result = await ReproEngine(sessions.open).reproduce(original)
    assert not result.repair_allowed
    assert result.reason == "nondeterministic_failure"


def test_status_assertion_requires_http_measurement() -> None:
    with pytest.raises(ValidationError, match="status assertions require a request"):
        ReproSpec(
            id="invalid",
            steps=[
                CaptureStep(id="text", selector="#text"),
                AssertStep(id="status", source="text", check=AssertionCheck(status=200)),
            ],
        )


async def test_suppressed_driver_error_cannot_admit_partial_run() -> None:
    class PartialSession(FakeSession):
        async def perform(self, step: ReproStep) -> Measurement | bytes | None:
            if step.id == "shot":
                raise RuntimeError("driver error after failed assertion")
            return await super().perform(step)

    @asynccontextmanager
    async def suppressing_factory() -> AsyncIterator[ReproSession]:
        try:
            yield PartialSession("one")
        except RuntimeError:
            pass

    original = spec()
    original.steps.append(CaptureStep(id="shot", kind="screenshot"))
    result = await ReproEngine(suppressing_factory).reproduce(original)
    assert not result.repair_allowed
    assert result.runs[0].error == "IncompleteRun"
