"""``faultline crawl URL`` (alias ``break``): a live HUD over the autonomous crawler.

``faultline scan URL`` (alias ``auto``) is the one-command flow: crawl, show
the reproduction journey of any defect, then offer to dispatch a sandboxed
repair to the running FaultLine engine and stream it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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


# --- faultline gate URL --------------------------------------------------------

GATE_PASSED = "PASSED"
GATE_FAILED = "FAILED"
SAFE_TO_DEPLOY = "SAFE_TO_DEPLOY"
DEPLOYMENT_BLOCKED = "DEPLOYMENT_BLOCKED"
_GATE_VERBS = {"click": "clicking", "fill": "filling", "select": "selecting", "check": "checking"}


def _plain() -> Palette:
    from app.cli import PLAIN

    return PLAIN


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _failing_crumb(report: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any] | None:
    step = failure.get("step")
    return next((c for c in report.get("breadcrumbs", []) if c.get("step") == step), None)


def _trigger(report: dict[str, Any], failure: dict[str, Any]) -> str | None:
    """``clicking "Place order" (button:has-text("Place order")) on /checkout``."""
    crumb = _failing_crumb(report, failure)
    if crumb is None or crumb.get("action") == "navigate":
        return None
    verb = _GATE_VERBS.get(str(crumb.get("action")), str(crumb.get("action")))
    label = crumb.get("label")
    target = json.dumps(label) if label else str(crumb.get("selector"))
    if label and crumb.get("selector"):
        target += f" ({crumb['selector']})"
    page = urllib.parse.urlsplit(str(crumb.get("url", ""))).path or "/"
    return f"{verb} {target} on {page}"


def _fix_instruction(failure: dict[str, Any]) -> str:
    kind = failure.get("kind")
    route = failure_route(failure) or "the failing request"
    if kind == "http_error":
        status = failure.get("status")
        if isinstance(status, int) and status >= 500:
            return (
                f"Fix the server-side exception handling for {route} so it no longer "
                f"returns HTTP {status}"
            )
        return (
            f"Fix the request the page sends to {route}, or the route handler, so the "
            f"action no longer gets HTTP {status}"
        )
    if kind == "request_failed":
        return f"Make {route} answer instead of dropping the connection"
    if kind == "page_error":
        return "Fix the client-side code that throws this exception"
    return "Fix the client-side code that logs this error"


def _defect_phrase(failure: dict[str, Any]) -> str:
    kind = failure.get("kind")
    if kind == "http_error":
        status = failure.get("status")
        handled = "an unhandled " if isinstance(status, int) and status >= 500 else "an "
        return f"{handled}HTTP {status} error on {failure_route(failure)}"
    if kind == "request_failed":
        return f"a failed network request: {describe_signal(failure)}"
    if kind == "page_error":
        return f"an uncaught JavaScript exception: {failure.get('message')}"
    return f"a console error: {failure.get('message')}"


def remediation_prompt(report: dict[str, Any], failure: dict[str, Any], url: str) -> str:
    """A self-contained fix instruction an agent can act on without the report."""
    sentences = [f"FaultLine caught {_defect_phrase(failure)}."]
    trigger = _trigger(report, failure)
    if trigger:
        sentences.append(f"Triggered by {trigger}.")
    lines = [" ".join(sentences)]
    if failure.get("response_body"):
        lines.append(f"Server response: {_clip(str(failure['response_body']), 300)}")
    if failure.get("stack"):
        lines.append(f"Stack: {' | '.join(str(failure['stack']).splitlines()[:4])}")
    trail = [str(step) for step in report.get("reproduction_trail") or []]
    if trail:
        lines.append("Reproduce:")
        lines.extend(f"  {step}" for step in trail)
    lines.append(
        f"{_fix_instruction(failure)} before deploying, then re-run "
        f"`faultline gate {url} --json` and continue only when it exits 0."
    )
    return "\n".join(lines)


def _error_prompt(code: str, message: str, url: str) -> str:
    if code in _INPUT_ERRORS:
        return (
            f"The FaultLine gate rejected its input: {message} Re-run it against the running "
            "preview, e.g. `faultline gate http://127.0.0.1:3000 --json`."
        )
    return (
        f"The FaultLine gate could not explore {url} ({code}): {message} "
        "Make sure the preview server is running and the browser runner is built, then re-run "
        f"`faultline gate {url} --json`. Do not deploy until the gate exits 0."
    )


def gate_result(report: dict[str, Any], url: str) -> dict[str, Any]:
    """The gate verdict for a completed crawl, in the documented JSON contract."""
    summary = crawler_service.telemetry(report)
    screens: list[Any] = summary["screens_visited"]
    explored = int(summary.get("elements_explored") or 0)
    target = str(summary.get("target_url") or url)
    trail = [str(step) for step in summary["reproduction_trail"]]
    failure = summary["failure"]
    status = report.get("status")
    error: dict[str, str] | None = None
    prompt: str | None = None
    if status == "clean":
        text = (
            f"No defects found: explored {_plural(explored, 'element')} across "
            f"{_plural(len(screens), 'screen')} with {_plural(summary['actions_taken'], 'action')}."
        )
    elif isinstance(failure, dict):
        if not trail:
            # Reports from older runners carry breadcrumbs only.
            trail = [line.strip() for line in _breadcrumb_lines(report, _plain())]
        text = (
            f"Defect intercepted: {describe_signal(failure)} after "
            f"{_plural(summary['actions_taken'], 'action')} across "
            f"{_plural(len(screens), 'screen')}."
        )
        prompt = remediation_prompt({**report, "reproduction_trail": trail}, failure, target)
    else:
        message = str(report.get("error") or "the crawl ended without a verdict")
        error = {"code": "crawl_error", "message": message}
        text = f"Gate could not complete the crawl: {message}"
        prompt = _error_prompt("crawl_error", message, target)
    passed = status == "clean"
    return {
        "gate_status": GATE_PASSED if passed else GATE_FAILED,
        "verdict": SAFE_TO_DEPLOY if passed else DEPLOYMENT_BLOCKED,
        "exit_code": 0 if passed else 1,
        "target_url": target,
        "summary": text,
        "elements_explored": explored,
        "screens_visited": screens,
        "failure": failure if isinstance(failure, dict) else None,
        "reproduction_trail": trail,
        "agent_remediation_prompt": prompt,
        "error": error,
    }


def gate_error_result(code: str, message: str, url: str) -> dict[str, Any]:
    """The verdict when the crawl could not run: exit 2 for bad input, else 1."""
    exit_code = 2 if code in _INPUT_ERRORS else 1
    return {
        "gate_status": GATE_FAILED,
        "verdict": DEPLOYMENT_BLOCKED,
        "exit_code": exit_code,
        "target_url": url,
        "summary": f"Gate could not run: {message}",
        "elements_explored": 0,
        "screens_visited": [],
        "failure": None,
        "reproduction_trail": [],
        "agent_remediation_prompt": _error_prompt(code, message, url),
        "error": {"code": code, "message": message},
    }


def _screen_paths(result: dict[str, Any]) -> list[str]:
    return [
        str(screen.get("path") or screen.get("url")) if isinstance(screen, dict) else str(screen)
        for screen in result["screens_visited"]
    ]


def _fence(text: str) -> str:
    """Wrap ``text`` in a code fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_gate_markdown(result: dict[str, Any]) -> str:
    """A GitHub PR comment / step summary: badge, facts, evidence, trail, fix prompt."""
    passed = result["gate_status"] == GATE_PASSED
    icon = "✅" if passed else "🛑"
    color = "brightgreen" if passed else "red"
    badge_text = result["verdict"].replace("_", "__")
    lines = [
        f"## {icon} FaultLine Pre-Flight Gate: {result['gate_status']}",
        "",
        f"![FaultLine gate: {result['verdict']}]"
        f"(https://img.shields.io/badge/FaultLine_gate-{badge_text}-{color})",
        "",
        f"> {result['summary']}",
        "",
        "| Target | Verdict | Elements explored | Screens visited |",
        "| --- | --- | --- | --- |",
        f"| {_md_cell(result['target_url'])} | **{result['verdict']}** | "
        f"{result['elements_explored']} | "
        f"{_md_cell(', '.join(f'`{p}`' for p in _screen_paths(result)) or '—')} |",
    ]
    failure = result.get("failure")
    if isinstance(failure, dict):
        evidence = [describe_signal(failure), *_evidence_lines(failure, _plain())]
        lines += ["", "### Defect", "", _fence("\n".join(evidence))]
    if result["reproduction_trail"]:
        lines += ["", "### Reproduction trail", "", _fence("\n".join(result["reproduction_trail"]))]
    if result.get("error"):
        lines += [
            "",
            "### Gate error",
            "",
            f"`{result['error']['code']}`: {result['error']['message']}",
        ]
    if result.get("agent_remediation_prompt"):
        lines += [
            "",
            "### Agent fix prompt",
            "",
            "Paste into your coding agent:",
            "",
            _fence(result["agent_remediation_prompt"]),
        ]
    lines += ["", f"<sub>Exit code {result['exit_code']} · `faultline gate`</sub>", ""]
    return "\n".join(lines)


def render_gate_agent(result: dict[str, Any]) -> str:
    """Plain, labelled text built to be pasted straight into an LLM prompt."""
    screens = _screen_paths(result)
    lines = [
        f"FAULTLINE PRE-FLIGHT GATE: {result['gate_status']} "
        f"({result['verdict']}, exit {result['exit_code']})",
        f"Target: {result['target_url']}",
        f"Summary: {result['summary']}",
        f"Explored: {_plural(result['elements_explored'], 'element')} across "
        f"{_plural(len(screens), 'screen')}" + (f" ({', '.join(screens)})" if screens else ""),
    ]
    failure = result.get("failure")
    if isinstance(failure, dict):
        lines += ["", f"Defect: {describe_signal(failure)}"]
        lines += [line.rstrip() for line in _evidence_lines(failure, _plain())]
    if result.get("agent_remediation_prompt"):
        # The prompt already carries the reproduction trail.
        lines += ["", "Required action:", result["agent_remediation_prompt"]]
    else:
        lines += ["", "Required action: none. The explored flows are clean; proceed."]
    return "\n".join(lines)


def _annotation(text: str) -> str:
    # GitHub workflow commands end at a newline and treat % specially.
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_gate_ci(result: dict[str, Any], *, github: bool) -> str:
    """Terse log lines; with ``github``, an ``::error``/``::notice`` annotation too."""
    lines = [
        f"faultline gate: {result['gate_status']} ({result['verdict']})",
        f"target:   {result['target_url']}",
        f"explored: {_plural(result['elements_explored'], 'element')}, "
        f"{_plural(len(result['screens_visited']), 'screen')}",
    ]
    failure = result.get("failure")
    if isinstance(failure, dict):
        lines.append(f"defect:   {describe_signal(failure)}")
    if result.get("error"):
        lines.append(f"error:    {result['error']['code']}: {result['error']['message']}")
    if result["reproduction_trail"]:
        lines += ["reproduction:", *(f"  {step}" for step in result["reproduction_trail"])]
    if github:
        level = "notice" if result["exit_code"] == 0 else "error"
        lines.append(
            f"::{level} title=FaultLine gate {result['gate_status']}::"
            + _annotation(result["summary"])
        )
    return "\n".join(lines)


def render_gate_human(
    result: dict[str, Any], report: dict[str, Any] | None, c: Palette
) -> list[str]:
    passed = result["gate_status"] == GATE_PASSED
    tone = c.green if passed else c.red
    icon = "✅" if passed else "🛑"
    lines = [
        "",
        f"{c.bold}FaultLine Pre-Flight Gate{c.reset}  {tone}{c.bold}{icon} "
        f"{result['gate_status']} · {result['verdict']}{c.reset}",
        f"{c.dim}{result['summary']}{c.reset}",
    ]
    failure = result.get("failure")
    if isinstance(failure, dict) and report is not None:
        lines += render_journey({**report, "reproduction_trail": result["reproduction_trail"]}, c)
    if result.get("agent_remediation_prompt"):
        lines += ["", f"{c.bold}Agent fix prompt{c.reset}", result["agent_remediation_prompt"]]
    return lines


def gate_command(args: argparse.Namespace, c: Palette) -> int:
    """Pre-deployment gate: 0 SAFE_TO_DEPLOY, 1 DEPLOYMENT_BLOCKED or crawl error, 2 bad input."""
    url = args.url.strip()
    if url and "://" not in url:
        url = "http://" + url
    fmt = "json" if args.json else "markdown" if args.markdown else args.format or "human"

    def progress(event: dict[str, Any]) -> None:
        # Markdown goes to stdout (e.g. $GITHUB_STEP_SUMMARY), so progress goes to the log.
        line = render_event(event, c if fmt == "human" else _plain())
        if line is not None:
            print(line, file=sys.stderr if fmt == "markdown" else sys.stdout, flush=True)

    report: dict[str, Any] | None = None
    try:
        report = crawler_service.run_crawl(
            url,
            max_actions=args.max_actions,
            timeout_ms=round(args.timeout * 1000),
            on_event=progress if fmt in ("human", "ci", "markdown") else None,
        )
        result = gate_result(report, url)
    except crawler_service.CrawlError as exc:
        result = gate_error_result(exc.code, str(exc), url)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130

    if fmt == "json":
        print(json.dumps(result, ensure_ascii=True))
    elif fmt == "markdown":
        print(render_gate_markdown(result))
    elif fmt == "agent":
        print(render_gate_agent(result))
    elif fmt == "ci":
        print(render_gate_ci(result, github=os.environ.get("GITHUB_ACTIONS") == "true"))
    else:
        for line in render_gate_human(result, report, c):
            print(line)
    return int(result["exit_code"])
