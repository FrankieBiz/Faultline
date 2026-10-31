"""``faultline crawl URL`` (alias ``break``): a live HUD over the autonomous crawler."""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING, Any

from app import crawler_service

if TYPE_CHECKING:
    from app.cli import Palette

_VERBS = {"click": "Clicking", "fill": "Filling", "select": "Selecting in", "check": "Checking"}
_INPUT_ERRORS = {"invalid_url", "invalid_request"}
MAX_BODY_CHARS = 600


def describe_signal(signal: dict[str, Any]) -> str:
    """Short description, e.g. ``HTTP 500 on POST /api/checkout``."""
    kind = signal.get("kind")
    if kind == "http_error":
        return f"HTTP {signal.get('status')} on {signal.get('method')} {signal.get('endpoint')}"
    if kind == "request_failed":
        return f"{signal.get('method')} {signal.get('endpoint')} failed: {signal.get('message')}"
    if kind == "page_error":
        return f"Uncaught {signal.get('message')}"
    return f"console.error: {signal.get('message')}"


def render_event(event: dict[str, Any], c: Palette) -> str | None:
    """One HUD line for a runner progress event; None for events not shown."""
    prefix = f"{c.cyan}[Playwright]{c.reset} "
    kind = event.get("type")
    if kind == "launch":
        return prefix + "Launching Chromium..."
    if kind == "navigate":
        return prefix + f"Navigating to {event.get('url')}..."
    if kind == "discovered":
        return prefix + f"Discovered {event.get('count')} interactive elements."
    if kind == "action":
        action = str(event.get("action"))
        value = f" with {json.dumps(event.get('value'))}" if action in ("fill", "select") else ""
        failure = event.get("failure")
        result = (
            f"{c.green}OK{c.reset}"
            if event.get("ok") or not isinstance(failure, dict)
            else f"{c.red}{c.bold}💥 {describe_signal(failure)}{c.reset}"
        )
        verb = _VERBS.get(action, action.capitalize())
        return prefix + f"Step {event.get('step')}: {verb} {event.get('label')}{value} -> {result}"
    return None


def _clip(text: str, limit: int = MAX_BODY_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_report(report: dict[str, Any], c: Palette) -> list[str]:
    """Closing summary: the defect and its reproduction, or the clean verdict."""
    status = report.get("status")
    if status == "clean":
        return [
            f"{c.green}{c.bold}No defect found.{c.reset} "
            f"Explored {report.get('elements_explored')} elements with "
            f"{report.get('actions_taken')} actions across "
            f"{len(report.get('pages_visited', []))} pages (stopped: {report.get('stop_reason')})."
        ]
    if status == "error":
        return [f"{c.red}Crawl could not complete:{c.reset} {report.get('error')}"]

    failure: dict[str, Any] = report.get("failure", {})
    lines = ["", f"{c.red}{c.bold}{describe_signal(failure)}{c.reset}"]
    if failure.get("kind") in ("http_error", "request_failed"):
        lines.append(f"  {c.dim}endpoint{c.reset}  {failure.get('method')} {failure.get('url')}")
    else:
        lines.append(f"  {c.dim}message{c.reset}   {failure.get('message')}")
    if failure.get("response_body"):
        lines.append(f"  {c.dim}response{c.reset}  {_clip(str(failure['response_body']))}")
    if failure.get("stack"):
        stack = str(failure["stack"]).splitlines()
        lines.append(f"  {c.dim}stack{c.reset}     {stack[0]}")
        lines.extend(f"            {frame.strip()}" for frame in stack[1:6])
    for message in failure.get("console_errors", [])[-3:]:
        lines.append(f"  {c.dim}console{c.reset}   {_clip(str(message), 200)}")
    lines.append("")
    lines.append(f"{c.bold}Reproduction{c.reset}")
    for crumb in report.get("breadcrumbs", []):
        action = crumb.get("action")
        if action == "navigate":
            detail = str(crumb.get("url"))
        else:
            detail = str(crumb.get("selector"))
            if crumb.get("value") is not None and action != "check":
                detail += f" = {json.dumps(crumb['value'])}"
        marker = (
            f"  {c.red}<- fails here{c.reset}" if crumb.get("step") == failure.get("step") else ""
        )
        lines.append(f"  {crumb.get('step')}. {action} {detail}{marker}")
    lines.append("")
    lines.append(
        f"{c.red}{c.bold}Defect intercepted!{c.reset} "
        f"Run {c.bold}./faultline run{c.reset} to repair it with Meta."
    )
    return lines


def crawl_command(args: argparse.Namespace, c: Palette) -> int:
    """Exit 0 clean, 1 defect found or crawl failure, 2 invalid input, 130 interrupted."""
    url = args.url.strip()
    if url and "://" not in url:
        url = "http://" + url

    def show(event: dict[str, Any]) -> None:
        line = render_event(event, c)
        if line is not None:
            print(line, flush=True)

    try:
        report = crawler_service.run_crawl(
            url,
            max_actions=args.max_actions,
            timeout_ms=round(args.timeout * 1000),
            on_event=None if args.json else show,
        )
    except crawler_service.CrawlError as exc:
        code = 2 if exc.code in _INPUT_ERRORS else 1
        if args.json:
            print(json.dumps({"status": "error", "code": exc.code, "error": str(exc)}))
        else:
            print(f"{c.red}faultline crawl: {exc}{c.reset}")
        return code
    except KeyboardInterrupt:
        print("Interrupted")
        return 130

    if args.json:
        print(json.dumps(report, ensure_ascii=True))
    else:
        for line in render_report(report, c):
            print(line)
    return 0 if report.get("status") == "clean" else 1
