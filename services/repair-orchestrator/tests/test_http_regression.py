"""Candidate faults become failed business checks, never oracle crashes."""

import httpx
import pytest

from app.http_regression import regression
from app.runtime import RuntimeUnavailable

EXPECTED_CHECKS = 27


async def run(transport: httpx.AsyncBaseTransport) -> dict[str, tuple[bool, str]]:
    """Measure one candidate and index results by assertion ID."""
    async with httpx.AsyncClient(transport=transport, base_url="http://candidate") as client:
        results = await regression(client)
    assert len({item.id for item in results}) == len(results) == EXPECTED_CHECKS
    return {item.id: (item.passed, item.observed) for item in results}


async def test_plain_text_server_errors_fail_checks_without_raising() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/orders":
            return httpx.Response(200, json={"orders": []})
        if request.url.path.startswith("/api/products/") or request.method == "GET":
            return httpx.Response(404, json={"detail": "Not found"})
        return httpx.Response(500, text="Internal Server Error")

    measured = await run(httpx.MockTransport(handle))
    passed, observed = measured["regression.fifteen"]
    assert not passed and observed == "HTTP 500: Internal Server Error"
    # Rejections still require the contract's exact status, so a 500 never passes them.
    assert not measured["regression.unknown_coupon"][0]
    assert measured["regression.unknown_order"][0]


class Failing(httpx.AsyncBaseTransport):
    """A candidate connection that never yields a usable response."""

    def __init__(self, fault: BaseException) -> None:
        self.fault = fault

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise self.fault


@pytest.mark.parametrize(
    "fault",
    [
        httpx.ReadTimeout("candidate did not answer"),
        RuntimeUnavailable("backend_response_limit"),
        TimeoutError(),
    ],
)
async def test_hung_or_oversized_candidates_fail_every_check(fault: BaseException) -> None:
    measured = await run(Failing(fault))
    assert not any(passed for passed, _ in measured.values())
    assert {observed for _, observed in measured.values()} == {
        f"request failed: {type(fault).__name__}"
    }
