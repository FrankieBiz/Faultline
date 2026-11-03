"""Wire faults and fail-closed generation, without real providers.

The adapter dispatches once; the worker accounts for each retry as an attempt.
Retry-After and backoff are owned by the deadline-aware worker, with no hidden
adapter retries or changes to the two-request job budget.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from conftest import Harness

from app.model_adapter import (
    CORRECTABLE_PROPOSAL_ERRORS,
    MAX_WIRE_BYTES,
    MetaRepairAdapter,
    ModelError,
    ModelSettings,
    RepairContext,
    deterministic_diff,
)
from app.policy import TARGET_FILE
from app.worker import Budgets
from shared.contracts.models import TerminalOutcome

TRANSIENT_STATUSES = (429, 500, 502, 503, 504)
PRIVATE = "private provider body and credential marker"


def completion(source: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    """Return a valid source-bound patch so faults cannot hide behind bad input."""
    return {
        "model": "muse-spark-1.3",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {
                    "content": json.dumps(
                        {
                            "decision": "patch",
                            "target_file": TARGET_FILE,
                            "base_sha256": RepairContext(source, "failure").base_sha256,
                            "unified_diff": deterministic_diff(source),
                            "explanation": "Default zero discount.",
                        }
                    )
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 50},
    }


class FaultStream(httpx.AsyncByteStream):
    """Yield real response chunks, then raise at the body-consumption boundary."""

    def __init__(self, chunks: list[bytes], error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.closed = False
        self.delivered = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.delivered += 1
            yield chunk
        if self.error is not None:
            raise self.error

    async def aclose(self) -> None:
        self.closed = True


def assert_safe_error(error: ModelError, code: str, *, retryable: bool) -> None:
    assert error.code == code
    assert str(error) == code
    assert error.retryable is retryable
    assert error.disables_repair is False
    assert PRIVATE not in str(error)


@pytest.mark.parametrize(
    "retry_after,delay",
    [
        (None, None),
        ("0", 0.0),
        (" 2 ", 2.0),
        ("86400", 86400.0),
        ("Wed, 04 Nov 2026 12:00:00 GMT", 86400.0),
        ("Mon, 02 Nov 2026 12:00:00 GMT", 0.0),
        ("Tue Nov  3 12:00:02 2026", 2.0),
        ("-1", None),
        ("1.5", None),
        ("+2", None),
        ("NaN", None),
        ("inf", None),
        ("", None),
        ("invalid", None),
        ("Wed, 99 Nov 2026 12:00:00 GMT", None),
        pytest.param("9" * 5000, float("inf"), id="huge_integer"),
    ],
)
@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize(
    "base_url", ["https://api.meta.ai/v1", "https://api.openai.com/v1", "http://localhost:11434/v1"]
)
async def test_rate_limit_headers_do_not_trigger_hidden_adapter_retries(
    seeded_source: str,
    monkeypatch: pytest.MonkeyPatch,
    retry_after: str | None,
    delay: float | None,
    status: int,
    base_url: str,
) -> None:
    now = datetime(2026, 11, 3, 12, tzinfo=UTC).timestamp()
    monkeypatch.setattr("app.model_adapter.time.time", lambda: now)
    calls: list[httpx.Request] = []
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    body = FaultStream([], AssertionError("Error response body must not be consumed"))

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        return httpx.Response(status, headers=headers, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = MetaRepairAdapter(ModelSettings(api_key="test", base_url=base_url), client=client)
        with pytest.raises(ModelError) as caught:
            await adapter.propose_patch(RepairContext(seeded_source, "failure"))
        assert not client.is_closed
    assert_safe_error(caught.value, f"provider_http_{status}", retryable=True)
    assert caught.value.retry_after == delay
    assert len(calls) == 1
    assert body.closed
    # Backoff must be owned by the attempt/deadline-aware worker.
    sleep.assert_not_awaited()


@pytest.mark.parametrize("status", TRANSIENT_STATUSES)
async def test_gateway_failures_are_retryable_and_close_unread_bodies(
    seeded_source: str, status: int
) -> None:
    body = FaultStream([], AssertionError("Private error body must not be read"))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, headers={"Retry-After": "2"}, stream=body)
        )
    ) as client:
        with pytest.raises(ModelError) as caught:
            await MetaRepairAdapter(ModelSettings(api_key="test"), client=client).propose_patch(
                RepairContext(seeded_source, "failure")
            )
    assert_safe_error(caught.value, f"provider_http_{status}", retryable=True)
    assert caught.value.retry_after == (2.0 if status in {429, 503} else None)
    assert body.closed and body.delivered == 0


@pytest.mark.parametrize(
    "fault,code",
    [
        (httpx.ConnectError, "provider_transport"),
        (httpx.ReadError, "provider_transport"),
        (httpx.WriteError, "provider_transport"),
        (httpx.RemoteProtocolError, "provider_transport"),
        (httpx.ConnectTimeout, "provider_timeout"),
        (httpx.ReadTimeout, "provider_timeout"),
        (httpx.WriteTimeout, "provider_timeout"),
        (httpx.PoolTimeout, "provider_timeout"),
    ],
)
async def test_dispatch_faults_are_safe_and_retryable(
    seeded_source: str, fault: type[httpx.TransportError], code: str
) -> None:
    requests = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise fault(PRIVATE, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ModelError) as caught:
            await MetaRepairAdapter(ModelSettings(api_key="test"), client=client).propose_patch(
                RepairContext(seeded_source, "failure")
            )
    assert_safe_error(caught.value, code, retryable=True)
    assert requests == 1


@pytest.mark.parametrize("fault", [httpx.ReadError, httpx.RemoteProtocolError, httpx.ReadTimeout])
@pytest.mark.parametrize("complete_json", [False, True])
async def test_midstream_reset_never_returns_even_a_complete_json_prefix(
    seeded_source: str, fault: type[httpx.TransportError], complete_json: bool
) -> None:
    wire = json.dumps(completion(seeded_source)).encode()
    prefix = wire if complete_json else wire[: len(wire) // 2]
    body = FaultStream([prefix[:20], prefix[20:]], fault(PRIVATE))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        with pytest.raises(ModelError) as caught:
            await MetaRepairAdapter(ModelSettings(api_key="test"), client=client).propose_patch(
                RepairContext(seeded_source, "failure")
            )
    code = "provider_timeout" if fault is httpx.ReadTimeout else "provider_transport"
    assert_safe_error(caught.value, code, retryable=True)
    assert body.closed and body.delivered == 2


@pytest.mark.parametrize(
    "content_kind", ["complete_patch", "partial_json", "partial_diff", "empty"]
)
async def test_length_finish_reason_fails_closed_before_parsing_or_recounting(
    seeded_source: str, monkeypatch: pytest.MonkeyPatch, content_kind: str
) -> None:
    response = completion(seeded_source, finish_reason="length")
    message = response["choices"][0]["message"]
    if content_kind == "partial_json":
        message["content"] = message["content"][:100]
    elif content_kind == "partial_diff":
        proposal = json.loads(message["content"])
        proposal["unified_diff"] = proposal["unified_diff"][:100]
        message["content"] = json.dumps(proposal)
    elif content_kind == "empty":
        message["content"] = ""

    def unexpected_recount(*args: Any) -> str:
        pytest.fail("Truncated output must never reach diff normalization")

    monkeypatch.setattr("app.model_adapter.recount_unified_diff", unexpected_recount)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    ) as client:
        with pytest.raises(ModelError) as caught:
            await MetaRepairAdapter(ModelSettings(api_key="test"), client=client).propose_patch(
                RepairContext(seeded_source, "failure")
            )
    assert_safe_error(caught.value, "incomplete_response", retryable=True)
    assert caught.value.code in CORRECTABLE_PROPOSAL_ERRORS


@pytest.mark.parametrize("wire", [b'{"choices":', b"\xff", b"[]", b"null", b""])
async def test_clean_eof_with_corrupt_body_is_a_protocol_error(
    seeded_source: str, wire: bytes
) -> None:
    body = FaultStream([wire])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        with pytest.raises(ModelError) as caught:
            await MetaRepairAdapter(ModelSettings(api_key="test"), client=client).propose_patch(
                RepairContext(seeded_source, "failure")
            )
    assert_safe_error(caught.value, "invalid_response", retryable=False)
    assert body.closed


async def test_chunked_response_enforces_cumulative_wire_budget(seeded_source: str) -> None:
    body = FaultStream([b" " * (MAX_WIRE_BYTES // 2), b" " * (MAX_WIRE_BYTES // 2), b"x", b"x"])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        with pytest.raises(ModelError) as caught:
            await MetaRepairAdapter(ModelSettings(api_key="test"), client=client).propose_patch(
                RepairContext(seeded_source, "failure")
            )
    assert_safe_error(caught.value, "response_too_large", retryable=False)
    assert body.closed and body.delivered == 3


@pytest.mark.parametrize("at_limit", [False, True])
async def test_successful_chunked_response_waits_for_eof_and_accepts_wire_limit(
    seeded_source: str, at_limit: bool
) -> None:
    response = completion(seeded_source)
    proposal = json.loads(response["choices"][0]["message"]["content"])
    proposal["explanation"] = "Default zéro discount."
    response["choices"][0]["message"]["content"] = json.dumps(proposal, ensure_ascii=False)
    wire = json.dumps(response, ensure_ascii=False).encode()
    if at_limit:
        wire += b" " * (MAX_WIRE_BYTES - len(wire))
    # Split within a multibyte UTF-8 character as well as across JSON tokens.
    split = wire.index("é".encode()) + 1
    body = FaultStream([wire[:split], wire[split:]])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        result = await MetaRepairAdapter(
            ModelSettings(api_key="test"), client=client
        ).propose_patch(RepairContext(seeded_source, "failure"))
    assert result.proposal.unified_diff == deterministic_diff(seeded_source)
    assert result.proposal.explanation == proposal["explanation"]
    assert result.prompt_tokens == 120 and result.completion_tokens == 50
    assert body.closed and body.delivered == 2


class StalledStream(httpx.AsyncByteStream):
    """Send a prefix and stall indefinitely; timeout/cancellation must close it."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"choices":'
        self.entered.set()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


async def test_total_request_timeout_covers_a_stalled_body() -> None:
    body = StalledStream()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        adapter = MetaRepairAdapter(ModelSettings(api_key="test"), client=client)
        with pytest.raises(ModelError) as caught:
            await adapter._request("POST", "/chat/completions", timeout=0.02)
    assert_safe_error(caught.value, "provider_timeout", retryable=True)
    assert body.entered.is_set() and body.closed


async def test_caller_cancellation_propagates_and_closes_body(seeded_source: str) -> None:
    body = StalledStream()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        adapter = MetaRepairAdapter(ModelSettings(api_key="test"), client=client)
        task = asyncio.create_task(adapter.propose_patch(RepairContext(seeded_source, "failure")))
        try:
            await asyncio.wait_for(body.entered.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert body.closed and not client.is_closed


@pytest.mark.parametrize("status", TRANSIENT_STATUSES)
@pytest.mark.parametrize("recover", [False, True])
async def test_worker_accounts_for_every_retry_without_exceeding_two_requests(
    harness: Harness, seeded_source: str, status: int, recover: bool
) -> None:
    requests = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if recover and requests == 2:
            return httpx.Response(200, json=completion(seeded_source))
        return httpx.Response(status, text=PRIVATE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkey_adapter = MetaRepairAdapter(ModelSettings(api_key="test"), client=client)
        harness.worker.adapter = monkey_adapter
        job = await harness.run()
    attempts = harness.database.list_attempts(job.id)
    assert requests == len(attempts) == 2
    assert attempts[0].outcome == f"provider_http_{status}"
    assert job.outcome == (TerminalOutcome.VERIFIED if recover else TerminalOutcome.MODEL_ERROR)
    assert attempts[1].outcome == ("verified" if recover else f"provider_http_{status}")
    assert not (attempts[1].validation_result or {}).get("prior_feedback")
    if not recover:
        assert "activate" not in harness.runtime.calls
        assert all(
            attempt.raw_patch is None and attempt.parsed_diff is None for attempt in attempts
        )


async def test_worker_never_applies_or_retains_a_length_truncated_patch(
    harness: Harness, seeded_source: str
) -> None:
    requests = 0
    payloads: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=completion(seeded_source, finish_reason="length"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        harness.worker.adapter = MetaRepairAdapter(ModelSettings(api_key="test"), client=client)
        job = await harness.run()
    attempts = harness.database.list_attempts(job.id)
    assert requests == len(attempts) == 2
    assert job.outcome == TerminalOutcome.MODEL_ERROR
    assert [attempt.outcome for attempt in attempts] == ["incomplete_response"] * 2
    assert all(attempt.raw_patch is None and attempt.parsed_diff is None for attempt in attempts)
    assert "activate" not in harness.runtime.calls
    evidence = json.loads(payloads[1]["messages"][1]["content"])
    assert evidence["previous_attempt"]["rejected_by_gate"] == "incomplete_response"
    assert evidence["previous_attempt"]["rejected_unified_diff"] is None


@pytest.mark.parametrize("header_kind", ["delta_seconds", "http_date"])
@pytest.mark.parametrize("status", [429, 503])
async def test_retry_after_beyond_job_budget_prevents_second_dispatch(
    harness: Harness, header_kind: str, status: int
) -> None:
    retry_after = (
        "86400"
        if header_kind == "delta_seconds"
        else format_datetime(datetime.now(UTC) + timedelta(days=1), usegmt=True)
    )
    requests = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(status, headers={"Retry-After": retry_after}, text=PRIVATE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        harness.worker.adapter = MetaRepairAdapter(ModelSettings(api_key="test"), client=client)
        job = await harness.run()
    assert job.outcome == TerminalOutcome.MODEL_ERROR
    assert requests == 1, (
        "Provider delay exceeds the entire job budget; another dispatch is forbidden"
    )
    assert len(harness.database.list_attempts(job.id)) == 1


@pytest.mark.parametrize("retry_after", [None, "1"])
async def test_backoff_must_leave_budget_for_a_complete_second_attempt(
    harness: Harness, retry_after: str | None
) -> None:
    harness.worker.budgets = replace(Budgets(), work=1.0, attempt=0.75)
    requests = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        return httpx.Response(503, headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        harness.worker.adapter = MetaRepairAdapter(ModelSettings(api_key="test"), client=client)
        job = await harness.run()
    assert job.outcome == TerminalOutcome.MODEL_ERROR
    assert requests == len(harness.database.list_attempts(job.id)) == 1
    assert "cleanup" in harness.runtime.calls


@pytest.mark.parametrize("retry_after,minimum_wait", [(None, 1.0), ("invalid", 1.0), ("2", 2.0)])
async def test_worker_waits_before_second_dispatch(
    harness: Harness, seeded_source: str, retry_after: str | None, minimum_wait: float
) -> None:
    dispatch_times: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        dispatch_times.append(time.monotonic())
        if len(dispatch_times) == 2:
            return httpx.Response(200, json=completion(seeded_source))
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        return httpx.Response(503, headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        harness.worker.adapter = MetaRepairAdapter(ModelSettings(api_key="test"), client=client)
        job = await harness.run()
    assert job.outcome == TerminalOutcome.VERIFIED
    assert len(dispatch_times) == len(harness.database.list_attempts(job.id)) == 2
    assert dispatch_times[1] - dispatch_times[0] >= minimum_wait


async def test_cancellation_during_backoff_prevents_second_dispatch(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeping = asyncio.Event()
    original_sleep = asyncio.sleep
    requests = 0

    async def sleep(delay: float) -> None:
        if delay == 2.0:
            sleeping.set()
            await asyncio.Event().wait()
        else:
            await original_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(429, headers={"Retry-After": "2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        harness.worker.adapter = MetaRepairAdapter(ModelSettings(api_key="test"), client=client)
        task = asyncio.create_task(harness.run())
        try:
            await asyncio.wait_for(sleeping.wait(), timeout=5)
            job = harness.database.unfinished_jobs()[0]
            harness.database.request_cancel(job.id)
            result = await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert result.outcome == TerminalOutcome.CANCELLED
    assert requests == len(harness.database.list_attempts(result.id)) == 1
    assert "cleanup" in harness.runtime.calls
