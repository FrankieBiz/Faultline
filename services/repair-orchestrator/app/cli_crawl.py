"""``faultline crawl URL`` (alias ``break``): a live HUD over the autonomous crawler.

``faultline scan URL`` (alias ``auto``) is the one-command flow: crawl, show
the reproduction journey of any defect, then offer to dispatch a sandboxed
repair to the running FaultLine engine and stream it.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import uuid
from dataclasses import dataclass
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
        screens = event.get("screens")
        if isinstance(screens, int):
            noun = "screen" if screens == 1 else "screens"
            return (
                prefix + f"Discovered {event.get('total_elements')} interactive elements "
                f"across {screens} {noun}."
            )
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


def _evidence_lines(failure: dict[str, Any], c: Palette) -> list[str]:
    lines: list[str] = []
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
    return lines


def _breadcrumb_lines(report: dict[str, Any], c: Palette) -> list[str]:
    failing_step = (report.get("failure") or {}).get("step")
    lines: list[str] = []
    for crumb in report.get("breadcrumbs", []):
        action = crumb.get("action")
        if action == "navigate":
            detail = str(crumb.get("url"))
        else:
            detail = str(crumb.get("selector"))
            if crumb.get("value") is not None and action != "check":
                detail += f" = {json.dumps(crumb['value'])}"
        marker = f"  {c.red}<- fails here{c.reset}" if crumb.get("step") == failing_step else ""
        lines.append(f"  {crumb.get('step')}. {action} {detail}{marker}")
    return lines


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
    lines.extend(_evidence_lines(failure, c))
    lines.append("")
    lines.append(f"{c.bold}Reproduction{c.reset}")
    lines.extend(_breadcrumb_lines(report, c))
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


# --- faultline scan URL (alias auto) ------------------------------------------


class ScanHud:
    """Renders runner events as the scan HUD; one call per event."""

    def __init__(self, c: Palette) -> None:
        self.c = c
        self._exercising = False

    def _emit(self, line: str) -> None:
        print(line, flush=True)

    def __call__(self, event: dict[str, Any]) -> None:
        c = self.c
        prefix = f"{c.cyan}[Playwright]{c.reset} "
        kind = event.get("type")
        if kind == "action" and not event.get("ok") and isinstance(event.get("failure"), dict):
            verb = _VERBS.get(str(event.get("action")), str(event.get("action")).capitalize())
            self._emit(
                prefix
                + f"Step {event.get('step')}: {verb} {event.get('label')} -> {c.red}FAILED{c.reset}"
            )
            return
        line = render_event(event, c)
        if line is None:
            return
        self._emit(line)
        if kind == "discovered" and not self._exercising:
            self._exercising = True
            self._emit(prefix + "Exercising buttons and forms...")


def bug_caught_line(failure: dict[str, Any], c: Palette) -> str:
    return (
        f"{c.cyan}[Playwright]{c.reset} {c.red}{c.bold}💥 BUG CAUGHT: "
        f"{describe_signal(failure)}{c.reset}"
    )


def render_journey(report: dict[str, Any], c: Palette) -> list[str]:
    """The defect's evidence and the numbered steps that reproduce it."""
    failure: dict[str, Any] = report.get("failure", {})
    lines = ["", f"{c.bold}Evidence{c.reset}", *_evidence_lines(failure, c), ""]
    lines.append(f"{c.bold}Reproduction journey{c.reset}")
    trail = report.get("reproduction_trail")
    if isinstance(trail, list) and trail:
        for entry in trail:
            text = str(entry)
            if text.startswith(f"{failure.get('step')}. "):
                text = f"{c.red}{text}{c.reset}"
            lines.append(f"  {text}")
    else:
        # Reports from older runners carry breadcrumbs only.
        lines.extend(_breadcrumb_lines(report, c))
    return lines


@dataclass(frozen=True)
class RepairPlan:
    """A registered scenario covering the defect, and who would propose the patch."""

    scenario_id: str
    route: str
    #: "Meta" only when readiness reports the Meta provider; otherwise named plainly.
    engine: str
    #: Set when no model can propose a patch; the run will only reproduce.
    detect_only_reason: str | None = None


class RepairUnavailable(Exception):
    """The defect cannot be dispatched for repair; the message says why and what to do."""


def failure_route(failure: dict[str, Any]) -> str | None:
    """``METHOD /path`` of a failing request, e.g. ``POST /api/checkout``."""
    if failure.get("kind") not in ("http_error", "request_failed"):
        return None
    path = urllib.parse.urlsplit(str(failure.get("url", ""))).path or "/"
    return f"{str(failure.get('method') or 'GET').upper()} {path}"


def _engine_name(model: dict[str, Any]) -> str:
    provider = str(model.get("provider", ""))
    name = str(model.get("model", "")).strip()
    if provider == "meta":
        return "Meta"
    if provider == "deterministic":
        return "the deterministic fallback (not a Meta model)"
    return f"{provider or 'the configured'} model {name}".strip() + " (not a Meta model)"


def plan_repair(failure: dict[str, Any], port: int) -> RepairPlan:
    """Find the scenario that covers the defect and check the engine can run it."""
    from app.cli import _api_request

    route = failure_route(failure)
    if route is None:
        raise RepairUnavailable(
            f"FaultLine repairs failing HTTP routes; this defect is "
            f"{describe_signal(failure)}. Fix it by hand using the journey above."
        )
    scenarios = _api_request("/api/faultline/scenarios", port=port)
    if "error" in scenarios:
        raise RepairUnavailable(
            f"The FaultLine engine is not reachable on port {port} ({scenarios['error']}). "
            "Start it with ./faultline demo, then scan again."
        )
    match = next(
        (
            item
            for item in scenarios.get("scenarios", [])
            if isinstance(item, dict) and str(item.get("route", "")).upper() == route.upper()
        ),
        None,
    )
    if match is None:
        raise RepairUnavailable(
            f"No repair scenario covers {route} yet. Describe it in faultline.toml, "
            "then run ./faultline run."
        )
    readiness = _api_request("/api/faultline/readiness", port=port)
    if "error" in readiness:
        raise RepairUnavailable(f"Could not read engine readiness: {readiness['error']}")
    if readiness.get("status") == "blocked":
        raise RepairUnavailable(
            f"The sandbox is not ready ({readiness.get('reason')}). Run ./faultline doctor."
        )
    model = readiness.get("model") or {}
    reason = None
    if readiness.get("status") != "ready":
        reason = str(model.get("reason") or "no repair model is available")
    return RepairPlan(
        scenario_id=str(match["id"]),
        route=route,
        engine=_engine_name(model),
        detect_only_reason=reason,
    )


def repair_prompt(plan: RepairPlan, c: Palette) -> str:
    head = f"{c.red}{c.bold}Defect intercepted!{c.reset} "
    if plan.detect_only_reason:
        return head + (
            f"No model can propose a patch ({plan.detect_only_reason}). "
            "Reproduce it in the sandbox anyway? [Y/n] "
        )
    return head + f"Propose and verify patch with {plan.engine} in sandbox? [Y/n] "


def confirm(prompt: str) -> bool:
    """Ask on the terminal; Enter means yes, end of input means no."""
    try:
        answer = input(prompt)
    except EOFError:
        print()
        return False
    return answer.strip().lower() in ("", "y", "yes")


def dispatch_repair(plan: RepairPlan, args: argparse.Namespace, port: int, c: Palette) -> int:
    """Start the sandboxed run and stream it with the ``listen`` HUD; return its exit code."""
    from app.cli import _api_request, cmd_listen

    job = _api_request(
        "/api/faultline/jobs",
        method="POST",
        data={"scenario_id": plan.scenario_id, "idempotency_key": uuid.uuid4().hex},
        port=port,
    )
    if "error" in job:
        print(f"{c.red}The engine refused the repair run: {job['error']}{c.reset}")
        return 1
    job_id = str(job["job_id"])
    if job.get("effective_mode") == "detect" and not plan.detect_only_reason:
        print(f"{c.yellow}Running detection only: {job.get('repair_block_reason')}.{c.reset}")
    print(f"{c.cyan}[FaultLine]{c.reset} Sandbox run {c.bold}{job_id}{c.reset} started.")
    listen_args = argparse.Namespace(
        job_id=job_id,
        port=port,
        plain=getattr(args, "plain", False),
        no_color=getattr(args, "no_color", False),
        ascii=False,
    )
    return cmd_listen(listen_args)


def scan_command(args: argparse.Namespace, c: Palette, *, port: int) -> int:
    """Crawl, explain any defect, and offer a sandboxed repair.

    Exit 0 clean; 1 defect left unrepaired or crawl failure; 2 invalid input;
    130 interrupted. A dispatched repair returns the ``listen`` exit code.
    """
    url = args.url.strip()
    if url and "://" not in url:
        url = "http://" + url
    hud = None if args.json else ScanHud(c)
    try:
        report = crawler_service.run_crawl(
            url,
            max_actions=args.max_actions,
            timeout_ms=round(args.timeout * 1000),
            on_event=hud,
        )
    except crawler_service.CrawlError as exc:
        code = 2 if exc.code in _INPUT_ERRORS else 1
        if args.json:
            print(json.dumps({"status": "error", "code": exc.code, "error": str(exc)}))
        else:
            print(f"{c.red}faultline scan: {exc}{c.reset}")
        return code
    except KeyboardInterrupt:
        print("Interrupted")
        return 130

    if args.json:
        print(json.dumps({**report, **crawler_service.telemetry(report)}, ensure_ascii=True))
        return 0 if report.get("status") == "clean" else 1
    if report.get("status") != "failure":
        for line in render_report(report, c):
            print(line)
        return 0 if report.get("status") == "clean" else 1

    failure: dict[str, Any] = report.get("failure", {})
    print(bug_caught_line(failure, c))
    screens = report.get("screens_visited") or report.get("pages_visited") or []
    print(
        f"{c.dim}Explored {report.get('elements_explored')} elements on {len(screens)} "
        f"{'screen' if len(screens) == 1 else 'screens'} with "
        f"{report.get('actions_taken')} actions.{c.reset}"
    )
    for line in render_journey(report, c):
        print(line)
    print()
    if args.no_repair:
        print(f"Repair skipped. Run {c.bold}./faultline run{c.reset} to repair it later.")
        return 1
    try:
        plan = plan_repair(failure, port)
    except RepairUnavailable as exc:
        print(f"{c.red}{c.bold}Defect intercepted!{c.reset} {exc}")
        return 1
    prompt = repair_prompt(plan, c)
    if args.yes:
        print(prompt + "y (--yes)")
    elif not sys.stdin.isatty():
        print(prompt.removesuffix(" [Y/n] "))
        print("Not a terminal, so nothing was dispatched. Re-run with --yes to repair.")
        return 1
    else:
        try:
            accepted = confirm(prompt)
        except KeyboardInterrupt:
            print("\nInterrupted")
            return 130
        if not accepted:
            print(f"Repair skipped. Run {c.bold}./faultline run{c.reset} to repair it later.")
            return 1
    return dispatch_repair(plan, args, port, c)
