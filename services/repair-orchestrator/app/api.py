"""Controller routes for the autonomous crawler.

``POST /api/faultline/crawl`` runs a crawl and returns the runner's CrawlReport
merged with its structured telemetry (``crawler_service.telemetry``).
``POST /api/crawl`` is the compatibility alias for the JSON report.
The primary route also streams the same crawl to the Inspector HUD as
NDJSON in its event vocabulary (``scan``, ``step``, ``defect``, ``done``,
``error``; see ``CrawlEvent`` in ``web/inspector-ui/src/lib/faultline-api.ts``).
Clients request streaming with ``Accept: application/x-ndjson`` or ``max_steps``.
The closing ``done`` event carries the telemetry as ``telemetry``.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import urllib.parse
from collections.abc import Iterator, Sequence
from typing import Any

from fastapi import APIRouter, Request, params
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app import crawler_service
from app.database import DatabaseError

logger = logging.getLogger("faultline.orchestrator")

# Failures that are the operator's input versus the local runner's health.
_ERROR_STATUS = {"invalid_url": 422, "invalid_request": 422, "runner_unavailable": 503}
_TRIGGER_KINDS = {"button": "Button", "link": "Link", "field": "Field"}
_SIGNAL_METHODS = {"page_error": "JS", "console_error": "CONSOLE"}
MAX_FINGERPRINT_CHARS = 300


class CrawlRequest(BaseModel):
    """JSON report request for the primary crawl route and its alias."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=crawler_service.MAX_URL_LENGTH)
    max_actions: int = Field(
        default=crawler_service.DEFAULT_MAX_ACTIONS, ge=1, le=crawler_service.MAX_ACTIONS
    )


class InspectorCrawlRequest(BaseModel):
    """Body of ``POST /api/faultline/crawl``, as the Inspector sends it."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=crawler_service.MAX_URL_LENGTH)
    max_steps: int = Field(
        default=crawler_service.DEFAULT_MAX_ACTIONS, ge=1, le=crawler_service.MAX_ACTIONS
    )


def _page(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")


def _fingerprint(failure: dict[str, Any]) -> str | None:
    """The response's ``detail`` (or body) for HTTP failures; the message otherwise."""
    text: Any = failure.get("message")
    body = failure.get("response_body")
    if failure.get("kind") == "http_error":
        text = body
        try:
            detail = json.loads(body or "")
        except json.JSONDecodeError:
            detail = None
        if isinstance(detail, dict) and isinstance(detail.get("detail"), str):
            text = detail["detail"]
    if not isinstance(text, str) or not text.strip():
        return None
    value: str = text.strip()
    return (
        value if len(value) <= MAX_FINGERPRINT_CHARS else value[: MAX_FINGERPRINT_CHARS - 1] + "…"
    )


def _note(failure: dict[str, Any]) -> str:
    kind = failure.get("kind")
    if kind == "http_error":
        return f"HTTP {failure.get('status')}"
    if kind == "request_failed":
        return "request failed"
    return "uncaught error" if kind == "page_error" else "console error"


class InspectorTranslator:
    """Turns runner events into Inspector HUD events, in order."""

    def __init__(self) -> None:
        self._actions: dict[int, dict[str, Any]] = {}

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        kind = event.get("type")
        if kind == "discovered":
            return [
                {
                    "type": "scan",
                    "url": event.get("url"),
                    "buttons": event.get("buttons", 0),
                    "forms": event.get("forms", 0),
                    "links": event.get("links", 0),
                }
            ]
        if kind == "navigate":
            url = str(event.get("url"))
            return [
                {
                    "type": "step",
                    "n": event.get("step"),
                    "action": "visit",
                    "target": url,
                    "page": _page(url),
                    "ok": True,
                }
            ]
        if kind == "action":
            self._actions[int(event.get("step", 0))] = event
            action = event.get("action")
            hud_action = (
                "fill"
                if action in ("fill", "select", "check")
                else ("submit" if event.get("submit") else "click")
            )
            failure = event.get("failure")
            step: dict[str, Any] = {
                "type": "step",
                "n": event.get("step"),
                "action": hud_action,
                "target": event.get("label"),
                "page": _page(str(event.get("url", ""))),
                "ok": bool(event.get("ok")),
            }
            if not step["ok"] and isinstance(failure, dict):
                step["note"] = _note(failure)
            return [step]
        if kind == "report":
            return self._report(event.get("report") or {})
        return []

    def _report(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        steps = len(report.get("breadcrumbs", []))
        status = report.get("status")
        summary = crawler_service.telemetry(report)
        if status == "clean":
            return [{"type": "done", "steps": steps, "defect": False, "telemetry": summary}]
        if status != "failure":
            return [{"type": "error", "message": str(report.get("error") or "The crawl failed.")}]
        failure: dict[str, Any] = report.get("failure", {})
        step = int(failure.get("step", 0))
        crumb: dict[str, Any] = next(
            (c for c in report.get("breadcrumbs", []) if c.get("step") == step), {}
        )
        action = self._actions.get(step, {})
        signal_kind = failure.get("kind")
        if signal_kind in ("http_error", "request_failed"):
            method = str(failure.get("method", "GET"))
            path = urllib.parse.urlsplit(str(failure.get("url", ""))).path or "/"
        else:
            method = _SIGNAL_METHODS.get(str(signal_kind), "JS")
            path = _page(str(crumb.get("url", "")))
        return [
            {
                "type": "defect",
                "method": method,
                "path": path,
                "status": failure.get("status") if signal_kind == "http_error" else None,
                "trigger": {
                    "kind": _TRIGGER_KINDS.get(str(action.get("element")), "Page"),
                    "label": crumb.get("label") or crumb.get("url") or "page load",
                    "page": _page(str(crumb.get("url", ""))),
                },
                "fingerprint": _fingerprint(failure),
            },
            {"type": "done", "steps": steps, "defect": True, "telemetry": summary},
        ]


def build_crawl_router(dependencies: Sequence[params.Depends]) -> APIRouter:
    """Routes guarded by ``dependencies`` (the controller's bearer check)."""
    router = APIRouter(dependencies=list(dependencies))
    # One Chromium crawl at a time per controller, across both routes.
    busy = threading.Lock()

    @router.post("/api/crawl", include_in_schema=False)
    def crawl(body: CrawlRequest) -> dict[str, Any]:
        """Crawl a URL in headless Chromium until something breaks; return report and telemetry."""
        if not busy.acquire(blocking=False):
            raise DatabaseError("crawl_in_progress", 409)
        try:
            report = crawler_service.run_crawl(body.url, max_actions=body.max_actions)
            return {**report, **crawler_service.telemetry(report)}
        except crawler_service.CrawlError as exc:
            raise DatabaseError(exc.code, _ERROR_STATUS.get(exc.code, 502)) from exc
        finally:
            busy.release()

    def inspector_crawl(body: InspectorCrawlRequest) -> StreamingResponse:
        """Stream a crawl to the Inspector HUD as NDJSON events."""
        try:
            url = crawler_service.validate_url(body.url)
            crawler_service.ensure_runner()
        except crawler_service.CrawlError as exc:
            raise DatabaseError(exc.code, _ERROR_STATUS.get(exc.code, 502)) from exc
        if not busy.acquire(blocking=False):
            raise DatabaseError("crawl_in_progress", 409)

        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        cancel = threading.Event()

        def work() -> None:
            try:
                report = crawler_service.run_crawl(
                    url, max_actions=body.max_steps, on_event=events.put, cancel=cancel
                )
                events.put({"type": "report", "report": report})
            except crawler_service.CrawlError as exc:
                events.put({"type": "report", "report": {"status": "error", "error": str(exc)}})
            except Exception:
                logger.exception("crawl failed")
                events.put({"type": "report", "report": {"status": "error"}})
            finally:
                busy.release()
                events.put(None)

        # Started before the response, so the lock is released even if the
        # client disconnects before the stream is read.
        threading.Thread(target=work, daemon=True).start()

        def stream() -> Iterator[str]:
            translator = InspectorTranslator()
            try:
                while (event := events.get()) is not None:
                    for item in translator.feed(event):
                        yield json.dumps(item) + "\n"
            finally:
                cancel.set()

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/faultline/crawl", response_model=None)
    def primary_crawl(
        body: CrawlRequest | InspectorCrawlRequest, request: Request
    ) -> dict[str, Any] | StreamingResponse:
        """Return the crawl report, or stream HUD events when requested by the Inspector."""
        if isinstance(body, InspectorCrawlRequest):
            return inspector_crawl(body)
        if "application/x-ndjson" in request.headers.get("accept", ""):
            return inspector_crawl(InspectorCrawlRequest(url=body.url, max_steps=body.max_actions))
        return crawl(body)

    return router
