"""Live HTTP invariants: faultline.toml scenarios and rules, and operator probes.

A live check sends the invariant's requests through ReproEngine twice, each time
from a fresh HTTP client with its own correlation ID, so a failure counts only
when both sessions fail identically. Live checks observe a service the operator
already runs: they never start or execute repository code, and they do not reset
the target's state. A reproduced failure is repairable only by a sandbox scenario
the controller admits: the project runner's own scenario of the same name, or a
registered scenario covering the same route, server fingerprint, and source. That
pipeline reproduces the failure again in isolation before any model call (F1).
"""

import json
import time
import tomllib
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.repro import (
    AssertionCheck,
    AssertStep,
    Measurement,
    ReproductionResult,
    ReproEngine,
    ReproRun,
    ReproSession,
    ReproSpec,
    ReproStep,
    RequestStep,
)
from app.snapshots import contained_path
from shared.config import Scenario

Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
InvariantId = Annotated[
    str, Field(min_length=1, max_length=140, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
]

MAX_PROBES = 50
MAX_URL_LENGTH = 2048
MAX_RESPONSE_BYTES = 64 * 1024
MAX_PAYLOAD_FILE_BYTES = 16 * 1024
MAX_REPRO_FILE_BYTES = 256 * 1024
EXCERPT_CHARACTERS = 600
REQUEST_TIMEOUT_MS = 8_000
SESSION_TIMEOUT_MS = 10_000
SCENARIO_TIMEOUT_MS = 30_000
PORT_PLACEHOLDER = "{port}"
SCENARIO_PREFIX = "scenario."
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class ProbeError(ValueError):
    """An invariant or target that FaultLine refuses to send."""


def validate_target(url: str, *, placeholder: bool = False) -> str:
    """Accept only absolute http(s) URLs without credentials or fragments."""
    if len(url) > MAX_URL_LENGTH or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ProbeError("URL must be at most 2048 characters with no spaces")
    if not placeholder and PORT_PLACEHOLDER in url:
        raise ProbeError("Replace {port} with a port number")
    probe = url.replace(PORT_PLACEHOLDER, "1") if placeholder else url
    try:
        parsed = urlsplit(probe)
        _ = parsed.port  # raises ValueError for an out-of-range port
    except ValueError as exc:
        raise ProbeError("URL is not valid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProbeError("URL must start with http:// or https:// and name a host")
    if parsed.username is not None or parsed.password is not None:
        raise ProbeError("URL must not contain credentials")
    if parsed.fragment:
        raise ProbeError("URL must not contain a #fragment")
    if parsed.path.startswith("//"):
        raise ProbeError("URL path must not start with //")
    return url


def resolve_url(template: str, port: int | None) -> str:
    """Substitute the per-service {port} placeholder."""
    if PORT_PLACEHOLDER not in template:
        return template
    if port is None:
        raise ProbeError("port_required")
    return template.replace(PORT_PLACEHOLDER, str(port))


def split_target(url: str) -> tuple[str, str]:
    """Return the origin and the service-relative path with its query."""
    parsed = urlsplit(url)
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    return f"{parsed.scheme}://{parsed.netloc}", path


def same_source(url: str, origin: str) -> bool:
    """Compare origins, treating loopback aliases and default ports as equal."""

    def key(value: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        default = {"http": 80, "https": 443}.get(parsed.scheme)
        return parsed.scheme, "loopback" if host in _LOOPBACK else host, parsed.port or default

    try:
        return key(url) == key(origin)
    except ValueError:
        return False


class Invariant(BaseModel):
    """One live HTTP check: a faultline.toml scenario or rule, or a dashboard probe.

    Rules and probes describe one request. A scenario carries its full ReproSpec,
    and `url` names its first request so the dashboard can show where it goes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: InvariantId
    source: Literal["config", "probe", "scenario"]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=500)] | None = None
    method: Method
    url: str
    expected_status: Annotated[int, Field(ge=100, le=599)] | None = None
    has_body: bool = False
    body: JsonValue = None
    assertions: list[AssertionCheck] = Field(default_factory=list, max_length=32)
    fingerprint: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    created_at: str | None = None
    repro: ReproSpec | None = None
    #: Why this entry cannot be checked live, e.g. browser steps that need the sandbox.
    live_note: str | None = None

    def matchers(self) -> list[tuple[str, str, AssertionCheck]]:
        """Step ID, operator label, and check for every declared expectation."""
        if self.repro is not None:
            return [(s.id, s.id, s.check) for s in self.repro.steps if isinstance(s, AssertStep)]
        result: list[tuple[str, str, AssertionCheck]] = []
        if self.expected_status is not None:
            result.append(("status", "HTTP status", AssertionCheck(status=self.expected_status)))
        for index, check in enumerate(self.assertions, start=1):
            matcher = next(iter(check.model_fields_set - {"path"}), "equals")
            result.append((f"body-{index}", f"{check.path} {matcher.replace('_', ' ')}", check))
        return result


class ProbeRequest(BaseModel):
    """Wire body for registering an ad-hoc probe."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(max_length=120)] | None = None
    method: Method
    url: Annotated[str, Field(min_length=1, max_length=MAX_URL_LENGTH)]
    expected_status: Annotated[int, Field(ge=100, le=599)]
    body: JsonValue = None

    def invariant(self) -> Invariant:
        """Validate the target and build a stored probe."""
        url = validate_target(self.url.strip())
        has_body = self.body is not None
        if has_body and self.method in {"GET", "HEAD"}:
            raise ProbeError(f"{self.method} requests cannot carry a JSON body")
        _, path = split_target(url)
        title = (self.title or "").strip() or f"{self.method} {urlsplit(url).netloc}{path}"
        return Invariant(
            id=f"probe-{uuid4().hex[:12]}",
            source="probe",
            title=title[:120],
            method=self.method,
            url=url,
            expected_status=self.expected_status,
            has_body=has_body,
            body=self.body,
            created_at=datetime.now(UTC).isoformat(),
        )


class CheckRequest(BaseModel):
    """Optional port for a rule whose target uses the {port} placeholder."""

    model_config = ConfigDict(extra="forbid")

    port: Annotated[int, Field(ge=1, le=65535)] | None = None


class CheckedAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    passed: bool
    expected: str
    observed: str


class RequestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    method: Method
    path: str
    status: int
    duration_ms: float


class SessionResult(BaseModel):
    """What one fresh HTTP session sent back, bounded and redacted.

    The top-level status and excerpt describe the request behind the first failed
    expectation (or the first request when all passed); `requests` lists them all.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    status: int | None
    duration_ms: float | None
    content_type: str | None
    excerpt: str | None
    truncated: bool
    fingerprint: str | None
    error: str | None
    assertions: list[CheckedAssertion]
    requests: list[RequestResult]


class RepairBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    title: str
    target_file: str


class CheckRecord(BaseModel):
    """One immutable live check of an invariant."""

    model_config = ConfigDict(extra="forbid")

    id: str
    invariant_id: str
    created_at: str
    method: Method
    url: str
    outcome: Literal["detected", "no_failure", "infrastructure_error"]
    reason: str
    sessions: list[SessionResult]
    repair: RepairBinding | None
    repair_note: str | None


@dataclass
class _Exchange:
    method: Method
    path: str
    status: int
    duration_ms: float
    content_type: str
    text: str
    truncated: bool
    value: JsonValue


class HttpProbeSession:
    """A ReproSession over one fresh HTTP client, without redirects or host proxies."""

    def __init__(self, client: httpx.AsyncClient, origin: str, session_id: str) -> None:
        self._client = client
        self._origin = origin
        self.session_id = session_id
        self.exchanges: dict[str, _Exchange] = {}

    async def perform(self, step: ReproStep) -> Measurement | bytes | None:
        if not isinstance(step, RequestStep):
            raise TypeError("live probes support request steps only")
        # The trusted runner's correlation header; servers that ignore it are unaffected.
        headers = {"X-Faultline-Case-Id": self.session_id, "Accept": "application/json, */*"}
        content: bytes | None = None
        if "body" in step.model_fields_set:
            content = json.dumps(step.body, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        async with self._client.stream(
            step.method,
            self._origin + step.path,
            headers=headers,
            content=content,
            timeout=step.timeout_ms / 1000,
        ) as response:
            data = bytearray()
            truncated = False
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    del data[MAX_RESPONSE_BYTES:]
                    truncated = True
                    break
        try:
            text = data.decode(response.charset_encoding or "utf-8", errors="replace")
        except LookupError:
            text = data.decode("utf-8", errors="replace")
        content_type = response.headers.get("content-type", "")
        value: JsonValue = text
        if not truncated and "json" in content_type.lower():
            try:
                value = json.loads(text)
            except ValueError:
                pass
        self.exchanges[step.id] = _Exchange(
            step.method,
            step.path,
            response.status_code,
            round((time.perf_counter() - started) * 1000, 1),
            content_type,
            text,
            truncated,
            value,
        )
        return Measurement(value=value, status=response.status_code)

    async def fingerprint(self) -> str | None:
        """The first 5xx response's own error text, never a model diagnosis."""
        exchange = next((x for x in self.exchanges.values() if x.status >= 500), None)
        if exchange is None:
            return None
        value = exchange.value
        if isinstance(value, dict):
            for key in ("detail", "error", "message"):
                item = value.get(key)
                if isinstance(item, dict):
                    item = item.get("message")
                if isinstance(item, str) and item:
                    return item[:512]
        return f"HTTP {exchange.status}"


@dataclass
class _Sessions:
    origin: str
    transport: httpx.AsyncBaseTransport | None
    opened: list[HttpProbeSession] = field(default_factory=list)

    @asynccontextmanager
    async def open(self) -> AsyncGenerator[ReproSession]:
        async with httpx.AsyncClient(
            transport=self.transport, follow_redirects=False, trust_env=False
        ) as client:
            session = HttpProbeSession(client, self.origin, str(uuid4()))
            self.opened.append(session)
            yield session


def build_spec(invariant: Invariant, path: str) -> ReproSpec:
    """Translate an invariant into the ReproSpec that gates reproduction."""
    if invariant.repro is not None:
        # The project runner matches a scenario fingerprint against service logs,
        # which a live check cannot read, so live admission compares responses only.
        timeout = min(invariant.repro.timeout_ms, SCENARIO_TIMEOUT_MS)
        return invariant.repro.model_copy(update={"fingerprint": None, "timeout_ms": timeout})
    # An absent body differs from a JSON null body, so set it only when declared.
    request = (
        RequestStep(
            id="request",
            method=invariant.method,
            path=path,
            timeout_ms=REQUEST_TIMEOUT_MS,
            body=invariant.body,
        )
        if invariant.has_body
        else RequestStep(
            id="request", method=invariant.method, path=path, timeout_ms=REQUEST_TIMEOUT_MS
        )
    )
    steps: list[ReproStep] = [request]
    steps.extend(
        AssertStep(id=step_id, source="request", check=check)
        for step_id, _, check in invariant.matchers()
    )
    return ReproSpec(
        id=invariant.id,
        timeout_ms=SESSION_TIMEOUT_MS,
        fingerprint=invariant.fingerprint,
        steps=steps,
    )


def _failing_routes(spec: ReproSpec, run: ReproRun) -> set[str]:
    """Routes of the requests whose expectations failed in this session."""
    requests = {step.id: step for step in spec.steps if isinstance(step, RequestStep)}
    sources = {step.id: step.source for step in spec.steps if isinstance(step, AssertStep)}
    routes = set()
    for item in run.assertions:
        request = requests.get(sources.get(item.id, ""))
        if not item.passed and request is not None:
            routes.add(f"{request.method} {urlsplit(request.path).path}")
    return routes


def repair_binding(
    invariant: Invariant,
    url: str,
    spec: ReproSpec,
    result: ReproductionResult,
    live_store_url: str,
    scenarios: Mapping[str, Scenario],
) -> tuple[Scenario | None, str | None]:
    """Find the sandbox scenario the controller admits that can repair this failure."""
    if result.outcome != "detected":
        return None, None
    if invariant.source == "scenario":
        own = scenarios.get(invariant.id.removeprefix(SCENARIO_PREFIX))
        if own is not None and own.executor == "repro":
            return own, (
                f"The controller's project runner owns {own.id}. Its sandbox run reproduces "
                "this ReproSpec again from tracked source before any model call."
            )
    failing = _failing_routes(spec, result.runs[0])
    if len(failing) != 1:
        return None, (
            "Detection only: the failing checks span several routes, and each registered "
            "sandbox repair covers one."
        )
    route = failing.pop()
    candidates = [item for item in scenarios.values() if item.route and item.route == route]
    if not candidates:
        return None, (
            f"Detection only: no registered sandbox repair covers {route}. "
            "FaultLine repairs only source it can rebuild and verify in isolation."
        )
    for scenario in candidates:
        if not all(
            run.fingerprint and scenario.error_fingerprint in run.fingerprint for run in result.runs
        ):
            continue
        if not same_source(url, live_store_url):
            return None, (
                f"The failure matches {scenario.title}, but {scenario.target_file} is served "
                f"at {live_store_url}, not this origin. Detection only."
            )
        return scenario, (
            f"Same route and server fingerprint as {scenario.title}. Its sandbox pipeline "
            "reproduces the failure again in isolation before any model call."
        )
    return None, (
        f"Detection only: {route} failed with a different server error than the "
        "registered repair scenario expects."
    )


def _session_result(
    invariant: Invariant,
    spec: ReproSpec,
    run: ReproRun,
    session: HttpProbeSession | None,
    redact: Callable[[str], str],
) -> SessionResult:
    labels = {step_id: label for step_id, label, _ in invariant.matchers()}
    sources = {step.id: step.source for step in spec.steps if isinstance(step, AssertStep)}
    exchanges = session.exchanges if session else {}
    failed = next((sources.get(item.id) for item in run.assertions if not item.passed), None)
    exchange = exchanges.get(failed or "") or next(iter(exchanges.values()), None)
    # Redact before cutting, so a secret straddling the cut is never half-shown.
    redacted = redact(exchange.text) if exchange is not None else None
    return SessionResult(
        session_id=run.session_id,
        status=exchange.status if exchange else None,
        duration_ms=exchange.duration_ms if exchange else None,
        content_type=exchange.content_type[:120] if exchange else None,
        excerpt=redacted[:EXCERPT_CHARACTERS] if redacted is not None else None,
        truncated=bool(
            exchange
            and redacted is not None
            and (exchange.truncated or len(redacted) > EXCERPT_CHARACTERS)
        ),
        fingerprint=redact(run.fingerprint) if run.fingerprint else None,
        error=run.error,
        assertions=[
            CheckedAssertion(
                id=item.id,
                label=labels.get(item.id, item.id),
                passed=item.passed,
                expected=redact(item.expected[:240]),
                observed=redact(item.observed[:240]),
            )
            for item in run.assertions
        ],
        requests=[
            RequestResult(
                step_id=step_id,
                method=item.method,
                path=redact(item.path),
                status=item.status,
                duration_ms=item.duration_ms,
            )
            for step_id, item in exchanges.items()
        ],
    )


async def run_check(
    invariant: Invariant,
    *,
    port: int | None,
    live_store_url: str,
    redact: Callable[[str], str],
    scenarios: Mapping[str, Scenario],
    transport: httpx.AsyncBaseTransport | None = None,
) -> CheckRecord:
    """Reproduce an invariant live: two fresh sessions must fail identically."""
    if invariant.live_note:
        raise ProbeError(invariant.live_note)
    url = validate_target(resolve_url(invariant.url, port))
    origin, path = split_target(url)
    spec = build_spec(invariant, path)
    sessions = _Sessions(origin, transport)
    result = await ReproEngine(sessions.open).reproduce(spec)
    by_id = {session.session_id: session for session in sessions.opened}
    scenario, note = repair_binding(invariant, url, spec, result, live_store_url, scenarios)
    return CheckRecord(
        id=str(uuid4()),
        invariant_id=invariant.id,
        created_at=datetime.now(UTC).isoformat(),
        method=invariant.method,
        url=url,
        outcome=result.outcome,
        reason=result.reason,
        sessions=[
            _session_result(invariant, spec, run, by_id.get(run.session_id), redact)
            for run in result.runs
        ],
        repair=RepairBinding(
            scenario_id=scenario.id, title=scenario.title, target_file=scenario.target_file
        )
        if scenario
        else None,
        repair_note=note,
    )


@dataclass(frozen=True)
class ProjectConfig:
    """The project name, scenarios, and HTTP rules declared in faultline.toml."""

    path: str | None
    name: str | None
    invariants: tuple[Invariant, ...]
    errors: tuple[str, ...]


def _project_file(base: Path, relative: str, limit: int, kind: str) -> str:
    """Read a bounded file inside the config's directory, refusing symlinks."""
    try:
        path = contained_path(base, relative)
    except ValueError as exc:
        raise ProbeError(f"{kind} file must be inside the project") from exc
    if path.stat().st_size > limit:
        raise ProbeError(f"{kind} file is larger than {limit // 1024} KiB")
    return path.read_text(encoding="utf-8")


def _payload(value: object, base: Path) -> tuple[bool, JsonValue]:
    """Inline JSON or an "@relative/file.json" reference inside the project."""
    if not isinstance(value, str) or not value.startswith("@"):
        return True, json.loads(json.dumps(value, allow_nan=False))
    loaded: JsonValue = json.loads(
        _project_file(base, value[1:], MAX_PAYLOAD_FILE_BYTES, "payload")
    )
    return True, loaded


def _scenario(
    name: str, selected: dict[str, Any], project_url: str | None, base: Path
) -> Invariant:
    """A [scenarios.NAME] entry, read the same way the project runner reads it."""
    raw = selected.get(
        "repro",
        {
            k: v
            for k, v in selected.items()
            if k in {"version", "id", "timeout_ms", "fingerprint", "steps"}
        },
    )
    if isinstance(raw, str):
        spec = ReproSpec.model_validate_json(
            _project_file(base, raw, MAX_REPRO_FILE_BYTES, "ReproSpec")
        )
    else:
        spec = ReproSpec.model_validate({"id": name, **raw})
    if spec.id != name:
        raise ProbeError("scenario name differs from its ReproSpec id")
    requests = [step for step in spec.steps if isinstance(step, RequestStep)]
    note = None
    if any(not isinstance(step, RequestStep | AssertStep) for step in spec.steps):
        note = "Browser steps (navigate, fill, click, capture) run only in the sandbox runner."
    elif not requests:
        note = "This ReproSpec sends no HTTP requests to check live."
    elif not project_url:
        note = "A live check needs [project].url."
    first = requests[0] if requests else None
    url = (project_url or "http://127.0.0.1:{port}").rstrip("/") + (first.path if first else "/")
    validate_target(url, placeholder=True)
    description = selected.get("description")
    return Invariant(
        id=SCENARIO_PREFIX + name,
        source="scenario",
        title=str(selected.get("title") or name)[:120],
        description=description if isinstance(description, str) and description else None,
        method=first.method if first else "GET",
        url=url,
        repro=spec,
        live_note=note,
    )


def _rule(rule: dict[str, Any], project_url: str | None, base: Path) -> Invariant:
    rule_id = rule.get("id")
    if not isinstance(rule_id, str) or rule_id.startswith(("probe-", SCENARIO_PREFIX)):
        raise ProbeError("id must be a name that does not start with probe- or scenario.")
    statuses: list[int] = []
    assertions: list[AssertionCheck] = []
    has_body, body = False, None
    if "request" in rule:
        # PLATFORM_DX_SPEC §4.3: request table plus [[invariants.rule.assert]] matchers.
        request = rule["request"]
        if not isinstance(request, dict) or not isinstance(request.get("path"), str):
            raise ProbeError("request needs a path")
        if not project_url:
            raise ProbeError("request.path needs [project].url")
        method = request.get("method", "GET")
        url = project_url.rstrip("/") + request["path"]
        if "json" in request:
            has_body, body = _payload(request["json"], base)
        for item in rule.get("assert", []):
            if isinstance(item, dict) and set(item) == {"status"}:
                statuses.append(item["status"])
            else:
                assertions.append(AssertionCheck.model_validate(item))
    else:
        # The form `faultline init` writes: target, method, expected_status.
        method = rule.get("method", "GET")
        url = rule.get("target")
        if "expected_status" in rule:
            statuses.append(rule["expected_status"])
        if "json" in rule:
            has_body, body = _payload(rule["json"], base)
    if not isinstance(url, str):
        raise ProbeError("target URL is missing")
    validate_target(url, placeholder=True)
    if len(statuses) > 1:
        raise ProbeError("declare at most one status assertion")
    if not statuses and not assertions:
        raise ProbeError("nothing can reproduce a failure (F1): declare an assertion")
    title = rule.get("name") or rule.get("description") or rule_id
    return Invariant(
        id=rule_id,
        source="config",
        title=str(title)[:120],
        description=rule.get("description"),
        method=method,
        url=url,
        expected_status=statuses[0] if statuses else None,
        has_body=has_body,
        body=body,
        assertions=assertions,
        fingerprint=rule.get("fingerprint"),
    )


def load_project_config(path: Path, root: Path) -> ProjectConfig:
    """Read faultline.toml on every call so edits appear without a restart."""
    display = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    if not path.is_file():
        return ProjectConfig(None, None, (), ())
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return ProjectConfig(display, None, (), (f"{display}: {exc}",))
    raw_project, raw_section = data.get("project"), data.get("invariants")
    project: dict[str, Any] = raw_project if isinstance(raw_project, dict) else {}
    section: dict[str, Any] = raw_section if isinstance(raw_section, dict) else {}
    name = project.get("name") if isinstance(project.get("name"), str) else None
    project_url = project.get("url") if isinstance(project.get("url"), str) else None
    rules = section.get("rule", [])
    invariants: list[Invariant] = []
    errors: list[str] = []
    seen: set[str] = set()
    # Scenarios use the project runner's forms: [scenarios.NAME], [[scenarios]] with
    # an id, or one top-level [repro].
    raw_scenarios = data.get("scenarios", {})
    definitions: dict[str, Any] = {}
    if isinstance(raw_scenarios, list):
        for item in raw_scenarios:
            key = item.get("id") if isinstance(item, dict) else None
            if not isinstance(key, str) or key in definitions:
                errors.append(f"{display} [[scenarios]] entry ignored: missing or duplicate id")
            else:
                definitions[key] = item
    elif isinstance(raw_scenarios, dict):
        definitions = raw_scenarios
    if not definitions and isinstance(data.get("repro"), dict):
        definitions = {str(data["repro"].get("id")): {"repro": data["repro"]}}
    for scenario_name, selected in definitions.items():
        try:
            if not isinstance(selected, dict):
                raise ProbeError("must be a table")
            invariants.append(_scenario(scenario_name, selected, project_url, path.parent))
        except (ProbeError, ValidationError, ValueError, TypeError, OSError) as exc:
            reason = (
                "; ".join(error["msg"] for error in exc.errors()[:3])
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            errors.append(f"{display} scenarios.{scenario_name} ignored: {reason}")
    for index, rule in enumerate(rules if isinstance(rules, list) else []):
        label = f"invariants.rule[{index}]"
        if isinstance(rule, dict) and isinstance(rule.get("id"), str):
            label += f" ({rule['id']})"
        try:
            if not isinstance(rule, dict):
                raise ProbeError("must be a table")
            invariant = _rule(rule, project_url, path.parent)
            if invariant.id in seen:
                raise ProbeError("duplicate id")
            seen.add(invariant.id)
            invariants.append(invariant)
        except (ProbeError, ValidationError, ValueError, TypeError, OSError) as exc:
            reason = (
                "; ".join(error["msg"] for error in exc.errors()[:3])
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            errors.append(f"{display} {label} ignored: {reason}")
    return ProjectConfig(display, name, tuple(invariants), tuple(errors))
