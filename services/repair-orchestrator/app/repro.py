"""Declarative browser/HTTP reproduction and the F1 admission gate.

The platform spec defines invariant matchers but no ReproSpec wire format. This
module supplies a strict, versioned format with eight discriminated primitives.
The project runtime supplies fresh isolated service and browser sessions.

Execution requires a trusted async session factory. Each invocation must reset
application data and create a fresh browser context against the SAME immutable
sandbox snapshot, enforcing network isolation and confirming cleanup on exit.
There is deliberately no host launcher or default session factory. PlaywrightSession
adapts an already provisioned page; it does not establish sandbox containment.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from shared.contracts.models import AssertionResult, ContractModel

Name = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=4096)]
Timeout = Annotated[int, Field(ge=1, le=180_000)]


def _relative_path(value: str) -> str:
    parsed = urlsplit(value)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or "\\" in value
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("expected a service-relative path starting with a single /")
    return value


ServicePath = Annotated[Text, AfterValidator(_relative_path)]


def _json_path(value: str) -> str:
    # Deliberately bounded JSONPath subset: root, object fields, array indices.
    if not re.fullmatch(r"\$(?:\.[A-Za-z_][A-Za-z0-9_-]*|\[\d{1,9}\])*", value):
        raise ValueError("JSONPath supports only $, .field, and [index]")
    return value


JsonPath = Annotated[Text, AfterValidator(_json_path)]


class Step(ContractModel):
    id: Name
    timeout_ms: Timeout = 10_000


class NavigateStep(Step):
    action: Literal["navigate"] = "navigate"
    path: ServicePath


class FillStep(Step):
    action: Literal["fill"] = "fill"
    selector: Text
    value: str


class ClickStep(Step):
    action: Literal["click"] = "click"
    selector: Text


class SelectStep(Step):
    action: Literal["select"] = "select"
    selector: Text
    value: str


class WaitForStep(Step):
    action: Literal["wait_for"] = "wait_for"
    selector: Text
    state: Literal["attached", "detached", "visible", "hidden"] = "visible"


class RequestStep(Step):
    action: Literal["request"] = "request"
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    path: ServicePath
    body: JsonValue = None
    headers: dict[str, str] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        result: dict[str, Any] = handler(self)
        if "body" not in self.model_fields_set:
            result.pop("body", None)
        return result


class CaptureStep(Step):
    action: Literal["capture"] = "capture"
    kind: Literal["text", "value", "visible", "url", "screenshot"] = "text"
    selector: Text | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> Self:
        if (self.kind in {"text", "value", "visible"}) != (self.selector is not None):
            raise ValueError("text/value/visible require a selector; url/screenshot forbid one")
        return self


class AssertionCheck(ContractModel):
    """Exactly one matcher, following PLATFORM_DX_SPEC §4.3.

    A status assertion reads the response status; other matchers read the response
    JSON body (or captured value). Explicit equals=null differs from an absent key.
    """

    status: Annotated[int, Field(ge=100, le=599)] | None = None
    path: JsonPath = "$"
    equals: JsonValue = None
    equals_path: JsonPath | None = None
    matches: Text | None = None
    type: Literal["null", "boolean", "integer", "number", "string", "array", "object"] | None = None
    exists: bool | None = None

    @model_serializer
    def serialize(self) -> dict[str, Any]:
        # Preserve the difference between an absent matcher and equals=null.
        return {key: getattr(self, key) for key in self.model_fields_set}

    @model_validator(mode="after")
    def validate_matcher(self) -> Self:
        matchers = self.model_fields_set - {"path"}
        if len(matchers) != 1:
            raise ValueError("exactly one assertion matcher is required")
        matcher = next(iter(matchers))
        if matcher != "equals" and getattr(self, matcher) is None:
            raise ValueError("only equals accepts null")
        if matcher == "status" and "path" in self.model_fields_set:
            raise ValueError("status does not accept a JSONPath")
        if self.matches is not None:
            try:
                re.compile(self.matches)
            except re.error as exc:
                raise ValueError("invalid assertion regex") from exc
        return self


class AssertStep(Step):
    action: Literal["assert"] = "assert"
    source: Name
    check: AssertionCheck


ReproStep = Annotated[
    NavigateStep
    | FillStep
    | ClickStep
    | SelectStep
    | WaitForStep
    | RequestStep
    | CaptureStep
    | AssertStep,
    Field(discriminator="action"),
]


class ReproSpec(ContractModel):
    version: Literal[1] = 1
    id: Name
    timeout_ms: Timeout = 20_000
    fingerprint: Text | None = None
    steps: Annotated[list[ReproStep], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def validate_steps(self) -> Self:
        seen: set[str] = set()
        sources: dict[str, RequestStep | CaptureStep] = {}
        has_assertion = False
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"duplicate step id: {step.id}")
            seen.add(step.id)
            if isinstance(step, AssertStep):
                has_assertion = True
                if step.source not in sources:
                    raise ValueError(
                        f"assertion source must be an earlier request/capture: {step.source}"
                    )
                if step.check.status is not None and not isinstance(
                    sources[step.source], RequestStep
                ):
                    raise ValueError("status assertions require a request source")
            if isinstance(step, RequestStep) or (
                isinstance(step, CaptureStep) and step.kind != "screenshot"
            ):
                sources[step.id] = step
        if not has_assertion:
            raise ValueError("nothing can reproduce a failure (F1): declare an assertion")
        return self


@dataclass(frozen=True)
class Measurement:
    value: JsonValue
    status: int | None = None


class ReproSession(Protocol):
    """Trusted, fresh sandbox session; exceptions are infrastructure failures.

    session_id must uniquely identify the reset application/browser execution.
    fingerprint() returns the correlated server error, never a model diagnosis.
    """

    session_id: str

    async def perform(self, step: ReproStep) -> Measurement | bytes | None: ...

    async def fingerprint(self) -> str | None: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[ReproSession]]
_MISSING = object()


def _lookup(value: object, path: str) -> object:
    for key, index in re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)|\[(\d+)\]", path):
        if key and isinstance(value, dict):
            value = value.get(key, _MISSING)
        elif index and isinstance(value, list) and int(index) < len(value):
            value = value[int(index)]
        else:
            return _MISSING
    return value


def _encoded(value: object) -> str:
    if value is _MISSING:
        return "<missing>"
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _equal(left: object, right: object) -> bool:
    # Avoid Python's True == 1, including nested values.
    return left is not _MISSING and right is not _MISSING and _encoded(left) == _encoded(right)


def evaluate_assertion(step: AssertStep, measurement: Measurement) -> AssertionResult:
    check = step.check
    observed = _lookup(measurement.value, check.path)
    expected: object
    if check.status is not None:
        observed, expected = measurement.status, check.status
        passed = observed == expected
    elif "equals" in check.model_fields_set:
        expected = check.equals
        passed = _equal(observed, expected)
    elif check.equals_path is not None:
        expected = _lookup(measurement.value, check.equals_path)
        passed = _equal(observed, expected)
    elif check.exists is not None:
        observed, expected = observed is not _MISSING, check.exists
        passed = observed == expected
    elif check.matches is not None:
        expected = check.matches
        passed = isinstance(observed, str) and re.search(check.matches, observed) is not None
    else:
        expected = check.type
        types: dict[str, tuple[type, ...]] = {
            "null": (type(None),),
            "boolean": (bool,),
            "integer": (int,),
            "number": (int, float),
            "string": (str,),
            "array": (list,),
            "object": (dict,),
        }
        passed = type(observed) in types[str(expected)]
    return AssertionResult(
        id=step.id,
        passed=passed,
        expected=_encoded(expected),
        observed=_encoded(observed),
        duration_ms=0.0,
    )


@dataclass
class ReproRun:
    session_id: str = ""
    assertions: list[AssertionResult] = field(default_factory=list)
    captures: dict[str, Measurement | bytes] = field(default_factory=dict)
    fingerprint: str | None = None
    error: str | None = None

    @property
    def failure_signature(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            (item.id, item.expected, item.observed) for item in self.assertions if not item.passed
        )


@dataclass(frozen=True)
class ReproductionResult:
    outcome: Literal["detected", "no_failure", "infrastructure_error"]
    reason: str
    runs: tuple[ReproRun, ...]

    @property
    def repair_allowed(self) -> bool:
        return self.outcome == "detected"


class ReproductionNotConfirmed(RuntimeError):
    def __init__(self, result: ReproductionResult) -> None:
        super().__init__(f"No reproduction, no repair (F1): {result.reason}")
        self.result = result


class ReproEngine:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def _run(self, spec: ReproSpec) -> ReproRun:
        run = ReproRun()
        completed = False
        try:
            # Cleanup is outside the execution timeout; the runtime owns its cleanup budget.
            async with self._session_factory() as session:
                run.session_id = session.session_id
                async with asyncio.timeout(spec.timeout_ms / 1000):
                    for step in spec.steps:
                        async with asyncio.timeout(step.timeout_ms / 1000):
                            if isinstance(step, AssertStep):
                                source = run.captures[step.source]
                                if not isinstance(source, Measurement):
                                    raise TypeError("assertions require a measured value")
                                run.assertions.append(evaluate_assertion(step, source))
                            else:
                                value = await session.perform(step)
                                if isinstance(step, (RequestStep, CaptureStep)):
                                    if isinstance(step, CaptureStep) and step.kind == "screenshot":
                                        if not isinstance(value, bytes):
                                            raise TypeError("screenshot capture requires bytes")
                                    elif not isinstance(value, Measurement):
                                        raise TypeError("request/capture requires a measurement")
                                    assert value is not None
                                    run.captures[step.id] = value
                    run.fingerprint = await session.fingerprint()
                    completed = True
            if not completed:
                run.error = "IncompleteRun"
        except Exception as exc:
            # Transport, selector, timeout, and cleanup faults never count as an invariant failure.
            # Do not retain exception text: drivers can include secrets/response bodies in it.
            run.error = type(exc).__name__
        return run

    async def run(self, spec: ReproSpec) -> ReproRun:
        """Measure one immutable oracle; return only after session cleanup."""
        return await self._run(ReproSpec.model_validate_json(spec.model_dump_json()))

    async def reproduce(self, spec: ReproSpec) -> ReproductionResult:
        # Revalidate a detached copy so callers cannot mutate the oracle between runs.
        oracle = ReproSpec.model_validate_json(spec.model_dump_json())
        first = await self._run(oracle)
        if first.error:
            return ReproductionResult(
                "infrastructure_error", "execution_or_cleanup_failed", (first,)
            )
        second = await self._run(oracle)
        runs = (first, second)
        if any(run.error for run in runs):
            return ReproductionResult("infrastructure_error", "execution_or_cleanup_failed", runs)
        if not first.session_id or not second.session_id or first.session_id == second.session_id:
            return ReproductionResult("infrastructure_error", "fresh_sessions_required", runs)
        if not first.failure_signature or not second.failure_signature:
            return ReproductionResult("no_failure", "failure_not_reproduced_twice", runs)
        if (
            first.failure_signature != second.failure_signature
            or first.fingerprint != second.fingerprint
        ):
            return ReproductionResult("no_failure", "nondeterministic_failure", runs)
        if oracle.fingerprint is not None and first.fingerprint != oracle.fingerprint:
            return ReproductionResult("no_failure", "fingerprint_mismatch", runs)
        return ReproductionResult("detected", "same_failure_reproduced_twice", runs)

    async def repair[T](
        self, spec: ReproSpec, propose: Callable[[ReproductionResult], Awaitable[T]]
    ) -> T:
        """The only proposal entry point: two completed reproductions precede inference."""
        result = await self.reproduce(spec)
        if not result.repair_allowed:
            raise ReproductionNotConfirmed(result)
        return await propose(result)


class PlaywrightSession:
    """Adapter for an async Playwright page supplied by a trusted sandbox runtime.

    The runtime owns browser/context creation, egress restrictions (including
    redirects and subresources), correlated logs, artifact retention, and cleanup.
    No Python Playwright dependency is needed to validate or unit test ReproSpec.
    """

    def __init__(
        self,
        page: Any,
        *,
        base_url: str,
        session_id: str,
        read_fingerprint: Callable[[], Awaitable[str | None]],
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be a loopback service origin")
        self._page = page
        self._base_url = base_url.rstrip("/")
        self.session_id = session_id
        self._read_fingerprint = read_fingerprint

    async def fingerprint(self) -> str | None:
        return await self._read_fingerprint()

    async def perform(self, step: ReproStep) -> Measurement | bytes | None:
        page = self._page
        if isinstance(step, NavigateStep):
            await page.goto(
                self._base_url + step.path, timeout=step.timeout_ms, wait_until="domcontentloaded"
            )
        elif isinstance(step, FillStep):
            await page.locator(step.selector).fill(step.value, timeout=step.timeout_ms)
        elif isinstance(step, ClickStep):
            await page.locator(step.selector).click(timeout=step.timeout_ms)
        elif isinstance(step, SelectStep):
            await page.locator(step.selector).select_option(step.value, timeout=step.timeout_ms)
        elif isinstance(step, WaitForStep):
            await page.locator(step.selector).wait_for(state=step.state, timeout=step.timeout_ms)
        elif isinstance(step, RequestStep):
            options: dict[str, Any] = {}
            if "body" in step.model_fields_set:
                # Serialize explicitly: strings, numbers and null must also be valid JSON bodies.
                options["data"] = json.dumps(step.body, allow_nan=False)
                options["headers"] = {"content-type": "application/json", **step.headers}
            else:
                options["headers"] = step.headers
            response = await page.request.fetch(
                self._base_url + step.path,
                method=step.method,
                timeout=step.timeout_ms,
                fail_on_status_code=False,
                max_redirects=0,
                **options,
            )
            try:
                try:
                    value = await response.json()
                except ValueError:
                    value = await response.text()
                return Measurement(value=value, status=response.status)
            finally:
                await response.dispose()
        elif isinstance(step, CaptureStep):
            if step.kind == "screenshot":
                content: bytes = await page.screenshot(type="png", timeout=step.timeout_ms)
                return content
            if step.kind == "url":
                return Measurement(value=page.url)
            locator = page.locator(step.selector)
            if step.kind == "visible":
                return Measurement(value=await locator.is_visible())
            if step.kind == "value":
                return Measurement(value=await locator.input_value(timeout=step.timeout_ms))
            return Measurement(value=await locator.inner_text(timeout=step.timeout_ms))
        else:
            raise TypeError("assert steps are evaluated by the trusted engine")
        return None
