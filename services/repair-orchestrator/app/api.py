"""Controller routes for the autonomous crawler (``POST /api/crawl``)."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, params
from pydantic import BaseModel, ConfigDict, Field

from app import crawler_service
from app.database import DatabaseError

# Failures that are the operator's input versus the local runner's health.
_ERROR_STATUS = {"invalid_url": 422, "invalid_request": 422, "runner_unavailable": 503}


class CrawlRequest(BaseModel):
    """Body of ``POST /api/crawl``."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=crawler_service.MAX_URL_LENGTH)
    max_actions: int = Field(
        default=crawler_service.DEFAULT_MAX_ACTIONS, ge=1, le=crawler_service.MAX_ACTIONS
    )


def build_crawl_router(dependencies: Sequence[params.Depends]) -> APIRouter:
    """Routes guarded by ``dependencies`` (the controller's bearer check)."""
    router = APIRouter(prefix="/api", dependencies=list(dependencies))
    # One Chromium crawl at a time per controller.
    busy = threading.Lock()

    @router.post("/crawl")
    def crawl(body: CrawlRequest) -> dict[str, Any]:
        """Crawl a URL in headless Chromium until something breaks; return the CrawlReport."""
        if not busy.acquire(blocking=False):
            raise DatabaseError("crawl_in_progress", 409)
        try:
            return crawler_service.run_crawl(body.url, max_actions=body.max_actions)
        except crawler_service.CrawlError as exc:
            raise DatabaseError(exc.code, _ERROR_STATUS.get(exc.code, 502)) from exc
        finally:
            busy.release()

    return router
