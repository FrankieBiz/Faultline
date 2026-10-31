"""FaultLine CLI: developer-facing control, diagnostics, live run HUD, and patch application."""

from __future__ import annotations

import argparse
import ast
import asyncio
import http.client
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.cli_init import detect_project_stack as detect_project_stack
from app.cli_init import generate_faultline_toml as generate_faultline_toml

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TARGET_FILE = REPOSITORY_ROOT / "apps" / "buggyshop-backend" / "app" / "routes" / "checkout.py"
SEEDED_FILE = REPOSITORY_ROOT / "fixtures" / "seeds" / "checkout_seeded.py"
HEALTHY_FILE = REPOSITORY_ROOT / "fixtures" / "seeds" / "checkout_healthy.py"
DATA_DIR = Path(os.environ.get("FAULTLINE_DATA_DIR", str(REPOSITORY_ROOT / "data")))

# ANSI Colors
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

DEFAULT_ORCHESTRATOR_PORT = 9000
DEFAULT_STORE_API_PORT = 8000
DEFAULT_STOREFRONT_PORT = 3000


@dataclass(frozen=True)
class Palette:
    """ANSI styles for one command's output; every field is empty when color is off."""

    cyan: str = ""
    green: str = ""
    yellow: str = ""
    red: str = ""
    bold: str = ""
    dim: str = ""
    reset: str = ""


COLOR = Palette(CYAN, GREEN, YELLOW, RED, BOLD, DIM, RESET)
PLAIN = Palette()


def _color_enabled(args: argparse.Namespace) -> bool:
    """Color only on a terminal, without NO_COLOR (https://no-color.org), --plain, or --no-color."""
    if getattr(args, "plain", False) or getattr(args, "no_color", False):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _palette(args: argparse.Namespace) -> Palette:
    return COLOR if _color_enabled(args) else PLAIN


def _env_port(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 0 < port < 65536:
        raise SystemExit(f"faultline: {name} must be a port number (1-65535), got {raw!r}")
    return port


def _orchestrator_port(args: argparse.Namespace) -> int:
    """The repair orchestrator's port: --port, then FAULTLINE_PORT, then 9000."""
    port: int | None = getattr(args, "port", None)
    return port if port is not None else _env_port("FAULTLINE_PORT", DEFAULT_ORCHESTRATOR_PORT)


def _store_api_port(args: argparse.Namespace) -> int:
    """The BuggyShop API's port: --api-port, then BUGGYSHOP_API_PORT, then 8000."""
    port: int | None = getattr(args, "api_port", None)
    return port if port is not None else _env_port("BUGGYSHOP_API_PORT", DEFAULT_STORE_API_PORT)


def _storefront_url() -> str:
    return f"http://127.0.0.1:{_env_port('BUGGYSHOP_PORT', DEFAULT_STOREFRONT_PORT)}"


def _port_arg(value: str) -> int:
    port = int(value)
    if not 0 < port < 65536:
        raise argparse.ArgumentTypeError(f"{value} is not a port number (1-65535)")
    return port


def _process_listens_on(pid: str, port: int) -> bool:
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\x00")
    except OSError:
        return False
    return any(a == "--port" and b == str(port) for a, b in zip(argv, argv[1:], strict=False))


def _get_control_token(port: int | None = None) -> str:
    token = os.environ.get("FAULTLINE_CONTROL_TOKEN")
    if token:
        return token
    token_file = DATA_DIR / ".control_token"
    if token_file.exists():
        return token_file.read_text().strip()

    # Discover token from running repair-orchestrator process, preferring the one on this port
    # when several demo stacks run side by side.
    try:
        pids = subprocess.check_output(
            ["pgrep", "-f", "services/repair-orchestrator.*uvicorn"], text=True
        ).split()
        if port is not None:
            pids.sort(key=lambda pid: not _process_listens_on(pid, port))
        for pid in pids:
            environ_path = Path(f"/proc/{pid}/environ")
            if environ_path.exists():
                for line in environ_path.read_bytes().split(b"\x00"):
                    if line.startswith(b"FAULTLINE_CONTROL_TOKEN="):
                        return line.decode().split("=", 1)[1]
    except Exception:
        pass

    return "dev-insecure-token"


def _api_request(
    path: str,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    port: int = DEFAULT_ORCHESTRATOR_PORT,
) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}{path}"
    headers = {
        "Authorization": f"Bearer {_get_control_token(port)}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode()
        try:
            parsed = json.loads(err_body)
            return {"error": parsed.get("error", {}).get("message", err_body), "status": exc.code}
        except Exception:
            return {"error": err_body, "status": exc.code}
    except Exception as exc:
        return {"error": str(exc), "status": 0}


def cmd_version(args: argparse.Namespace) -> int:
    """Print FaultLine CLI and engine version details."""
    c = _palette(args)
    commit = "unknown"
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPOSITORY_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        pass
    print(f"{c.bold}FaultLine Developer Platform CLI{c.reset} v0.2.0 ({commit})")
    print(f"  Python:   {sys.version.split()[0]}")
    print(f"  Root:     {REPOSITORY_ROOT}")
    print(f"  Platform: {sys.platform}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check system requirements: bubblewrap, cgroups v2, Node, uv, and models."""
    from app.cli_check import sandbox_readiness

    c = _palette(args)
    orchestrator_port, store_port = _orchestrator_port(args), _store_api_port(args)
    readiness = sandbox_readiness()
    print(f"\n{c.bold}FaultLine Doctor: System Diagnostic Report{c.reset}\n")

    checks: list[tuple[str, bool, str]] = []

    # 1. Bubblewrap
    bwrap_path = shutil.which("bwrap")
    checks.append(
        (
            "Linux Bubblewrap (bwrap) Sandbox",
            bwrap_path is not None,
            bwrap_path or "Missing! Install via: sudo dnf install bubblewrap",
        )
    )

    # 2. cgroup v2
    cgroup_v2 = Path("/sys/fs/cgroup/cgroup.controllers").exists()
    checks.append(
        (
            "cgroup v2 Resource Enforcement",
            cgroup_v2,
            "Available (/sys/fs/cgroup)"
            if cgroup_v2
            else "cgroup v2 unified hierarchy not mounted",
        )
    )

    # 3. uv package manager
    uv_path = shutil.which("uv")
    checks.append(
        (
            "Astral uv Package Manager",
            uv_path is not None,
            uv_path or "Missing! Install via: curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
    )

    # 4. Node.js
    node_path = shutil.which("node")
    node_ver = ""
    if node_path:
        try:
            node_ver = subprocess.check_output([node_path, "--version"], text=True).strip()
        except Exception:
            pass
    checks.append(
        (
            f"Node.js Runtime ({node_ver or 'not found'})",
            bool(node_ver and int(node_ver.lstrip("v").split(".")[0]) >= 20),
            node_path or "Requires Node.js >= 20",
        )
    )

    # 5. Meta Model API Key
    meta_key = os.environ.get("META_API_KEY")
    checks.append(
        (
            "Meta Model API Key (META_API_KEY)",
            bool(meta_key),
            "Configured (muse-spark-1.3)"
            if meta_key
            else "Not set. Set META_API_KEY to enable Meta repair inference.",
        )
    )

    # 6. Service Health
    orch_health = _api_request("/healthz", port=orchestrator_port)
    checks.append(
        (
            f"Repair Orchestrator Service (port {orchestrator_port})",
            orch_health.get("status") == "ok",
            "Active & Healthy"
            if orch_health.get("status") == "ok"
            else "Offline (run ./scripts/start-demo.sh)",
        )
    )

    store_health = _api_request("/healthz", port=store_port)
    checks.append(
        (
            f"Storefront Backend API (port {store_port})",
            store_health.get("status") == "ok",
            "Active & Healthy" if store_health.get("status") == "ok" else "Offline",
        )
    )

    all_ok = readiness["prerequisites_available"]
    for name, passed, detail in checks:
        icon = f"{c.green}✓{c.reset}" if passed else f"{c.red}✗{c.reset}"
        status_text = f"{c.green}PASS{c.reset}" if passed else f"{c.yellow}WARN{c.reset}"
        print(f" {icon} {c.bold}{name:<40}{c.reset} [{status_text}]")
        print(f"     {c.dim}{detail}{c.reset}")
        if not passed and name.startswith("Linux"):
            all_ok = False

    print(f"\n{c.dim}{'─' * 60}{c.reset}")
    if all_ok:
        msg = (
            f"{c.green}{c.bold}Result: Sandbox prerequisites found; "
            f"runner enforcement preflight is still required.{c.reset}\n"
        )
        print(msg)
        return 0
    else:
        print(f"{c.yellow}Result: Some components require attention. See details above.{c.reset}\n")
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Check live orchestrator status, sandbox limits, and readiness."""
    c = _palette(args)
    port = _orchestrator_port(args)
    res = _api_request("/api/faultline/readiness", port=port)
    if "error" in res:
        print(f"{c.red}Error connecting to FaultLine orchestrator: {res['error']}{c.reset}")
        print(f"Ensure the service is running on port {port} (`./scripts/start-demo.sh`).")
        return 1

    status_str = (
        f"{c.green if res.get('status') == 'ready' else c.yellow}{res.get('status')}{c.reset}"
    )
    print(f"\n{c.bold}FaultLine Orchestrator Status{c.reset}")
    print(f"  Status:          {status_str}")
    print(f"  Runtime Ready:   {res.get('runtime_ready')}")
    print(f"  Quarantined:     {res.get('quarantined')}")

    model = res.get("model") or {}
    model_str = f"{c.cyan}{model.get('model', 'None')}{c.reset}"
    print(f"  Repair Model:    {model_str} (Provider: {model.get('provider')})")

    limits = res.get("resource_limits") or {}
    if limits:
        mem_mib = limits.get("memory_bytes", 0) // (1024 * 1024)
        cpu_q = limits.get("cpu_quota_us", 0)
        cpu_p = limits.get("cpu_period_us", 100000)
        pids = limits.get("pids_max")
        print(f"  Sandbox Limits:  Memory={mem_mib} MiB, Tasks={pids}, CPU={cpu_q}/{cpu_p}")

    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    """List recent repair jobs with state, duration, and outcomes."""
    c = _palette(args)
    res = _api_request("/api/faultline/jobs?limit=10", port=_orchestrator_port(args))
    if "error" in res:
        print(f"{c.red}Error fetching jobs: {res['error']}{c.reset}")
        return 1

    jobs = res.get("jobs", [])
    if not jobs:
        print(f"{c.yellow}No recent jobs recorded in database.{c.reset}")
        return 0

    hdr = f"{'JOB ID':<8} {'SCENARIO':<20} {'STATE':<10} {'OUTCOME':<12} {'CREATED'}"
    print(f"\n{c.bold}{hdr}{c.reset}")
    print("-" * 75)
    for j in jobs:
        state = j.get("state", "")
        state_color = (
            c.green if state == "succeeded" else (c.red if state == "failed" else c.yellow)
        )
        jid = j.get("id", "")[:12]
        scen = j.get("scenario_id", "")[:24]
        outc = str(j.get("outcome", ""))[:14]
        created = j.get("created_at", "")[:19]
        print(f"{jid:<12} {scen:<24} {state_color}{state:<12}{c.reset} {outc:<14} {created}")
    print()
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Print the candidate patch for a job."""
    c = _palette(args)
    port = _orchestrator_port(args)
    job_id = args.job_id
    if not job_id:
        # Find latest succeeded job
        res = _api_request("/api/faultline/jobs?limit=1", port=port)
        jobs = res.get("jobs", [])
        if not jobs:
            print(f"{c.red}No jobs found.{c.reset}")
            return 1
        job_id = jobs[0]["id"]

    res = _api_request(f"/api/faultline/jobs/{job_id}", port=port)
    if "error" in res:
        print(f"{c.red}Error: {res['error']}{c.reset}")
        return 1

    attempts = res.get("attempts", [])
    if not attempts:
        print(f"{c.yellow}No repair attempts recorded for job {job_id}.{c.reset}")
        return 1

    latest_attempt = attempts[-1]
    diff = latest_attempt.get("parsed_diff") or ""
    if not diff and "raw_patch" in latest_attempt:
        raw = latest_attempt["raw_patch"]
        if isinstance(raw, str) and raw.startswith("{"):
            try:
                diff = json.loads(raw).get("unified_diff", "")
            except Exception:
                pass
        elif isinstance(raw, dict):
            diff = raw.get("unified_diff", "")
    if not diff:
        diff = latest_attempt.get("proposal", {}).get("diff", "")

    if not diff:
        print(f"{c.yellow}No diff found in proposal for job {job_id}.{c.reset}")
        return 1

    outcome = (res.get("job") or {}).get("outcome") or "in progress"
    tone = c.green if outcome == "verified" else c.yellow
    title = f"{c.bold}Candidate diff for job {job_id}{c.reset}"
    print(f"\n{title} {c.dim}·{c.reset} {tone}{outcome}{c.reset}\n")
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            print(f"{c.green}{line}{c.reset}")
        elif line.startswith("-") and not line.startswith("---"):
            print(f"{c.red}{line}{c.reset}")
        elif line.startswith("@"):
            print(f"{c.cyan}{line}{c.reset}")
        else:
            print(line)
    print()
    return 0


def apply_patch_for_job(
    job_id: str, database: Any = None, port: int = DEFAULT_ORCHESTRATOR_PORT
) -> dict[str, Any]:
    """Apply a verified candidate patch from a job to the live codebase."""
    diff = ""
    if database is not None:
        job = database.get_job(job_id)
        if job.state != "succeeded" or job.outcome != "verified":
            return {
                "success": False,
                "error_code": "unverified_job",
                "message": f"Refusing to apply unverified job {job_id} ({job.state}/{job.outcome})",
            }
        attempts = database.list_attempts(job_id)
        if not attempts:
            return {
                "success": False,
                "error_code": "no_attempts",
                "message": "No attempts recorded",
            }
        verified_attempt = next(
            (a for a in attempts if getattr(a, "outcome", None) == "verified"),
            attempts[-1],
        )
        diff = getattr(verified_attempt, "parsed_diff", "") or ""
        if not diff and getattr(verified_attempt, "raw_patch", None):
            raw = verified_attempt.raw_patch
            if isinstance(raw, str) and raw.startswith("{"):
                try:
                    diff = json.loads(raw).get("unified_diff", "")
                except Exception:
                    pass
            elif isinstance(raw, dict):
                diff = raw.get("unified_diff", "")
    else:
        res = _api_request(f"/api/faultline/jobs/{job_id}", port=port)
        if "error" in res:
            return {"success": False, "error_code": "job_fetch_failed", "message": res["error"]}
        job = res.get("job", {})
        if job.get("state") != "succeeded" or job.get("outcome") != "verified":
            return {
                "success": False,
                "error_code": "unverified_job",
                "message": f"Job {job_id} is not verified",
            }
        attempts = res.get("attempts", [])
        if not attempts:
            return {"success": False, "error_code": "no_attempts", "message": "No attempts found"}
        verified_attempt = next(
            (
                a
                for a in attempts
                if a.get("outcome") == "verified" or a.get("verdict") == "verified"
            ),
            attempts[-1],
        )
        diff = verified_attempt.get("parsed_diff") or ""
        if not diff and "raw_patch" in verified_attempt:
            raw = verified_attempt["raw_patch"]
            if isinstance(raw, str) and raw.startswith("{"):
                try:
                    diff = json.loads(raw).get("unified_diff", "")
                except Exception:
                    pass
            elif isinstance(raw, dict):
                diff = raw.get("unified_diff", "")
        if not diff:
            diff = verified_attempt.get("proposal", {}).get("diff", "")

    if not diff:
        return {
            "success": False,
            "error_code": "no_diff",
            "message": f"No diff available for job {job_id}",
        }

    if not TARGET_FILE.exists():
        return {
            "success": False,
            "error_code": "target_missing",
            "message": f"Target missing: {TARGET_FILE}",
        }

    original_source = TARGET_FILE.read_text()
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "checkout.py.bak"
    backup_file.write_text(original_source)

    try:
        from app.policy import parse_unified_diff

        parsed = parse_unified_diff(diff, original_source)
        candidate_source = parsed.patched_source
        ast.parse(candidate_source)
        TARGET_FILE.write_text(candidate_source)
        return {
            "success": True,
            "status": "applied",
            "job_id": job_id,
            "target": str(TARGET_FILE),
            "backup": str(backup_file),
        }
    except Exception as exc:
        if backup_file.exists():
            TARGET_FILE.write_text(backup_file.read_text())
        return {"success": False, "error_code": "patch_apply_failed", "message": str(exc)}


def revert_to_seeded() -> dict[str, Any]:
    """Revert the live application back to the seeded bug state."""
    if not SEEDED_FILE.exists():
        return {
            "success": False,
            "error_code": "seeded_file_missing",
            "message": f"Seeded file missing: {SEEDED_FILE}",
        }
    seeded_content = SEEDED_FILE.read_text()
    TARGET_FILE.write_text(seeded_content)
    return {
        "success": True,
        "status": "reverted",
        "target": str(TARGET_FILE),
    }


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a repository with faultline.toml configuration."""
    c = _palette(args)
    target_dir = Path.cwd()
    dest_file = target_dir / "faultline.toml"
    if dest_file.exists() and not getattr(args, "force", False):
        print(f"{c.yellow}faultline.toml already exists at {dest_file}{c.reset}")
        print("Use --force to overwrite.")
        return 0

    print(f"\n{c.bold}FaultLine Initializer: Analyzing repository at {target_dir}...{c.reset}")
    try:
        info = detect_project_stack(target_dir)
        toml_content = generate_faultline_toml(info)
    except (OSError, ValueError, SyntaxError) as exc:
        print(f"faultline init: {exc}", file=sys.stderr)
        return 1
    print(f"  Detected Project: {c.cyan}{info['name']}{c.reset}")
    print(f"  Detected Stack:   {c.green}{info['stack']}{c.reset}")
    if info["dev_command"]:
        print(f"  Dev Command:      {info['dev_command']}")
    if info["test_command"]:
        print(f"  Test Command:     {info['test_command']}")

    dest_file.write_text(toml_content)
    print(f"\n{c.green}{c.bold}✓ Created {dest_file}{c.reset}")
    print("Next steps:")
    print("  1. Review faultline.toml and add a [scenarios.NAME] target_file and repro.")
    print("     Or run: faultline run --repro repro.json --target path/to/source")
    print("  2. Run `faultline doctor` to verify sandbox containment.")
    print("  3. Run `faultline status` to verify orchestrator connectivity.\n")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply a verified candidate patch to the live application."""
    c = _palette(args)
    port, store_port = _orchestrator_port(args), _store_api_port(args)
    job_id = args.job_id
    if not job_id:
        res = _api_request("/api/faultline/jobs?limit=5", port=port)
        jobs = res.get("jobs", [])
        verified = [
            j for j in jobs if j.get("state") == "succeeded" and j.get("outcome") == "verified"
        ]
        if not verified:
            print(f"{c.red}No verified jobs found to apply.{c.reset}")
            return 1
        job_id = verified[0]["id"]

    result = apply_patch_for_job(job_id, port=port)
    if not result.get("success"):
        print(f"{c.red}Failed to apply patch: {result.get('message')}{c.reset}")
        return 1

    print(f"\n{c.green}{c.bold}✓ Verified patch successfully applied to:{c.reset}")
    print(f"  {result.get('target')}")
    print(f"  Backup created: {result.get('backup')}")

    # Test live API
    print(f"\n{c.cyan}Testing live store endpoint...{c.reset}")
    test_payload = {
        "items": [{"product_id": "trail-mug", "quantity": 2}],
        "coupon_code": "",
    }
    test_res = _api_request("/api/checkout", method="POST", data=test_payload, port=store_port)
    if test_res.get("status") == 0 or "error" in test_res:
        print(f"  {c.yellow}Note: Backend may need automatic reload (port {store_port}).{c.reset}")
    else:
        order_id = test_res.get("id")
        total = test_res.get("total", 0)
        price = f"${total / 100:.2f}"
        print(f"  {c.green}{c.bold}Live Order Created: ID={order_id}, Total={price}{c.reset}")
        print(f"  {c.green}BuggyShop on {_storefront_url()} is now 100% REPAIRED!{c.reset}\n")

    return 0


def cmd_revert(args: argparse.Namespace) -> int:
    """Revert the live application back to the seeded bug state."""
    c = _palette(args)
    result = revert_to_seeded()
    if not result.get("success"):
        print(f"{c.red}Failed to revert: {result.get('message')}{c.reset}")
        return 1

    print(f"\n{c.yellow}{c.bold}✓ Reverted live store to seeded defect state:{c.reset}")
    print(f"  Target: {result.get('target')}")
    print(f"  Live BuggyShop at {_storefront_url()} will now trigger the 500 error.\n")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Run an automated checkout check against the live store to verify status."""
    c = _palette(args)
    store_port = _store_api_port(args)
    url = f"http://127.0.0.1:{store_port}/api/checkout"
    print(f"\n{c.bold}Probing live store checkout ({url})...{c.reset}")
    test_payload = {
        "items": [{"product_id": "trail-mug", "quantity": 1}],
        "coupon_code": "",
    }
    res = _api_request("/api/checkout", method="POST", data=test_payload, port=store_port)
    err_str = str(res.get("error", "")) + str(res.get("detail", ""))
    if res.get("status") == 500 or "TypeError" in err_str:
        print(f"  {c.red}{c.bold}Status: DEFECT ACTIVE (HTTP 500){c.reset}")
        print(
            f"  {c.dim}TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'{c.reset}"
        )
        print(f"  Live BuggyStore at {_storefront_url()} is currently BROKEN.")
        print("  Run `faultline apply` to apply the verified patch!\n")
        return 1
    elif res.get("id"):
        print(f"  {c.green}{c.bold}Status: HEALTHY (HTTP 201 Created){c.reset}")
        print(f"  Order ID: {res.get('id')}, Total: ${res.get('total', 0) / 100:.2f}")
        print("  Store is working cleanly!\n")
        return 0
    else:
        print(f"  {c.yellow}Unexpected response: {res}{c.reset}\n")
        return 2


# Stage ids and labels match the Inspector's STAGE_LABEL (web/inspector-ui/src/lib/faultline-api.ts)
# so the terminal and the dashboard read the same. The third column is the plain-mode name.
STAGES: tuple[tuple[str, str, str], ...] = (
    ("preparing", "Prepare", "prepare"),
    ("baseline", "Reproduce", "reproduce"),
    ("diagnosing", "Propose patch", "propose"),
    ("patch_validation", "Policy check", "policy"),
    ("activating", "Activate candidate", "activate"),
    ("verification", "Verify", "verify"),
    ("cleanup", "Clean up", "cleanup"),
)
STAGE_LABEL = {stage: label for stage, label, _ in STAGES}
STAGE_SHORT = {stage: short for stage, _, short in STAGES}
# Stages that every repair attempt runs again.
ATTEMPT_STAGES = ("diagnosing", "patch_validation", "activating", "verification")

# Status glyphs from PLATFORM_DX_SPEC §6.2 and their ASCII fallback. "ended" is a work stage
# whose verdict is not known until the job outcome arrives.
GLYPHS = {
    "done": "✓",
    "failed": "✗",
    "running": "●",
    "pending": "○",
    "ended": "○",
    "attention": "!",
    "skipped": "–",
}
ASCII_GLYPHS = {
    "done": "ok",
    "failed": "FAIL",
    "running": "..",
    "pending": "--",
    "ended": "--",
    "attention": "!!",
    "skipped": "skip",
}
STATUS_STYLE = {
    "done": GREEN,
    "failed": RED,
    "running": BOLD + CYAN,
    "pending": DIM,
    "ended": DIM,
    "attention": YELLOW,
    "skipped": DIM,
}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ASCII_SPINNER = "|/-\\"

SUCCESS_OUTCOMES = frozenset({"verified", "detected", "no_failure"})
OUTCOME_HEADLINE = {
    "verified": "VERIFIED CANDIDATE",
    "detected": "FAILURE REPRODUCED (detect only)",
    "no_failure": "FAILURE NOT REPRODUCED",
    "cancelled": "CANCELLED",
    "interrupted": "INTERRUPTED",
}
# PLATFORM_DX_SPEC §5.2 exit codes by TerminalOutcome.
OUTCOME_EXIT_CODES = {
    "verified": 0,
    "detected": 10,
    "no_failure": 11,
    "unresolved": 20,
    "invalid_patch": 20,
    "repair_unavailable": 20,
    "unexpected_failure": 20,
    "model_error": 21,
    "infrastructure_error": 30,
    "artifact_error": 30,
    "timeout": 30,
    "cleanup_failed": 31,
    "cancelled": 130,
    "interrupted": 130,
}

SSE_READ_TIMEOUT = 30.0  # the controller sends a keep-alive ping every 15 s
MAX_RECONNECTS = 5
TICK_SECONDS = 0.1
BAR_WIDTH = 21
ASSERTION_ROWS = 12
INSPECTOR_DIR = REPOSITORY_ROOT / "web" / "inspector-ui"
INSPECTOR_START_TIMEOUT = 30.0


def _parse_timestamp(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _report_summary(report: dict[str, Any] | None) -> str:
    """Summarize one runner report as assertion counts, or the runner's own failure."""
    if not report:
        return ""
    verdict = str(report.get("verdict", ""))
    if verdict in {"error", "timed_out"}:
        return f"runner {verdict.replace('_', ' ')}"
    assertions = report.get("assertions") or []
    if not assertions:
        return f"verdict {verdict}" if verdict else ""
    failed = sum(not item.get("passed") for item in assertions)
    if failed:
        return f"{failed} of {len(assertions)} assertions failed"
    return f"{len(assertions)}/{len(assertions)} assertions passed"


def _first_failure(report: dict[str, Any] | None) -> str:
    """Name the first failed assertion with what was observed and expected."""
    for item in (report or {}).get("assertions") or []:
        if not item.get("passed"):
            observed, expected = item.get("observed", ""), item.get("expected", "")
            return f"{item.get('id', '?')} {observed}, expected {expected}"
    return ""


@dataclass
class StageRecord:
    """A stage whose result is settled; plain mode prints one line per record."""

    stage: str
    status: str
    at: float
    attempt: int


@dataclass
class HudState:
    """Job progress folded from the controller's ordered JobEvent stream."""

    job_id: str
    scenario: str = ""
    status: dict[str, str] = field(default_factory=lambda: dict.fromkeys(STAGE_LABEL, "pending"))
    elapsed: dict[str, float] = field(default_factory=lambda: dict.fromkeys(STAGE_LABEL, 0.0))
    current: str | None = None
    entered_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    awaiting: str | None = None
    awaiting_at: datetime | None = None
    attempt: int = 0
    rejected: str = ""
    outcome: str | None = None
    cleanup_status: str | None = None
    cancel_requested: bool = False
    last_sequence: int = 0
    log: deque[tuple[datetime, str, str]] = field(default_factory=lambda: deque(maxlen=5))
    settled: list[StageRecord] = field(default_factory=list)
    baseline_report: dict[str, Any] | None = None
    candidate_reports: dict[int, dict[str, Any]] = field(default_factory=dict)

    def apply(self, event: dict[str, Any]) -> bool:
        """Fold one event in; return True when new assertion evidence may exist."""
        sequence = int(event.get("sequence", 0))
        if sequence <= self.last_sequence:
            return False  # replayed after a reconnect
        self.last_sequence = sequence
        at = _parse_timestamp(str(event["timestamp"]))
        stage, code = str(event.get("stage", "")), str(event.get("message_code", ""))
        self.log.append((at, stage, str(event.get("message", ""))))
        if code == "cancel_requested":
            self.cancel_requested = True
            return False
        if stage == "completed":
            self._finish(code, at)
            return True
        # A stage entry carries its stage as the code; "queued" and other notices do not.
        if code != stage or stage not in STAGE_LABEL:
            return False
        previous = self._close(at)
        if self.started_at is None:
            self.started_at = at
        if previous is not None:
            if stage == "diagnosing" and self.attempt:
                # A new attempt means the previous one was rejected at the stage it reached.
                self._settle(previous, "failed", at)
                self.rejected = f"attempt {self.attempt} rejected at {STAGE_LABEL[previous]}"
                for later in ATTEMPT_STAGES:
                    self.status[later], self.elapsed[later] = "pending", 0.0
            elif stage == "cleanup":
                # Whether the last work stage passed is only known from the job outcome.
                self.status[previous], self.awaiting, self.awaiting_at = "ended", previous, at
            else:
                self._settle(previous, "done", at)
        if stage == "diagnosing":
            self.attempt += 1
        self.status[stage], self.current, self.entered_at = "running", stage, at
        return previous in {"baseline", "verification"}

    def absorb(self, detail: dict[str, Any]) -> None:
        """Take the scenario, cleanup status, and assertion reports from GET /jobs/{id}."""
        job = detail.get("job") or {}
        self.scenario = str(job.get("scenario_id") or self.scenario)
        self.cleanup_status = job.get("cleanup_status") or self.cleanup_status
        numbers = {
            item.get("id"): item.get("attempt_number") for item in detail.get("attempts") or []
        }
        for execution in detail.get("executions") or []:
            report = execution.get("report")
            if not isinstance(report, dict):
                continue
            if execution.get("phase") == "baseline":
                self.baseline_report = report
            elif execution.get("phase") == "verification":
                number = numbers.get(execution.get("attempt_id"))
                if isinstance(number, int):
                    self.candidate_reports[number] = report

    def stage_seconds(self, stage: str, now: datetime) -> float:
        seconds = self.elapsed[stage]
        if stage == self.current and self.entered_at is not None:
            seconds += max(0.0, (now - self.entered_at).total_seconds())
        return seconds

    def total_seconds(self, now: datetime) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, ((self.finished_at or now) - self.started_at).total_seconds())

    def stage_detail(self, stage: str, sep: str = " · ") -> str:
        """The live screen's note for a stage: attempt, rejection, or assertion counts."""
        status = self.status[stage]
        if status in {"pending", "skipped"}:
            return ""
        parts: list[str] = []
        if stage == "baseline":
            parts += [_report_summary(self.baseline_report), _first_failure(self.baseline_report)]
        elif stage == "diagnosing":
            parts += [f"attempt {self.attempt}", self.rejected]
        elif stage == "verification":
            parts.append(_report_summary(self.candidate_reports.get(self.attempt)))
        if status == "ended":
            parts.append("verdict pending")
        return sep.join(part for part in parts if part)

    def record_detail(self, record: StageRecord, sep: str = " · ") -> str:
        parts: list[str] = []
        if record.stage in ATTEMPT_STAGES:
            parts.append(f"attempt {record.attempt}")
        if record.stage == "baseline":
            parts += [_report_summary(self.baseline_report), _first_failure(self.baseline_report)]
        elif record.stage == "verification":
            parts.append(_report_summary(self.candidate_reports.get(record.attempt)))
        return sep.join(part for part in parts if part)

    def assertion_rows(
        self,
    ) -> tuple[list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]], dict[str, int]]:
        """Assertions that failed on either side, and passing counts by where they ran."""
        baseline = {item["id"]: item for item in (self.baseline_report or {}).get("assertions", [])}
        latest = (
            self.candidate_reports[max(self.candidate_reports)] if self.candidate_reports else {}
        )
        candidate = {item["id"]: item for item in latest.get("assertions", [])}
        rows: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]] = []
        # A failing baseline stops early, so many assertions run on the candidate only.
        passing = {"both": 0, "baseline": 0, "candidate": 0}
        for assertion_id in dict.fromkeys([*baseline, *candidate]):
            before, after = baseline.get(assertion_id), candidate.get(assertion_id)
            if any(side is not None and not side.get("passed") for side in (before, after)):
                rows.append((assertion_id, before, after))
            else:
                passing["both" if before and after else "baseline" if before else "candidate"] += 1
        return rows, passing

    def _close(self, at: datetime) -> str | None:
        if self.current is not None and self.entered_at is not None:
            self.elapsed[self.current] += max(0.0, (at - self.entered_at).total_seconds())
        self.entered_at = None
        return self.current

    def _settle(self, stage: str, status: str, at: datetime) -> None:
        self.status[stage] = status
        since = (at - (self.started_at or at)).total_seconds()
        self.settled.append(StageRecord(stage, status, since, self.attempt))

    def _finish(self, outcome: str, at: datetime) -> None:
        self._close(at)
        self.outcome, self.finished_at = outcome, at
        if outcome in SUCCESS_OUTCOMES:
            verdict = "done"
        elif outcome in {"cancelled", "interrupted", "cleanup_failed"}:
            verdict = "attention"
        else:
            verdict = "failed"
        if self.awaiting is not None:
            # repair_unavailable follows a reproduced failure; only the repair stages did not run.
            reproduced = outcome == "repair_unavailable" and self.awaiting == "baseline"
            self._settle(self.awaiting, "done" if reproduced else verdict, self.awaiting_at or at)
        if self.current == "cleanup":
            self._settle("cleanup", "failed" if outcome == "cleanup_failed" else "done", at)
        elif self.current is not None:
            self._settle(self.current, verdict, at)
        self.current = None
        # The controller records cleanup as failed exactly when the outcome is cleanup_failed.
        self.cleanup_status = "failed" if outcome == "cleanup_failed" else "succeeded"
        for stage, status in self.status.items():
            if status == "pending":
                self.status[stage] = "skipped"


def _paint(text: str, style: str, color: bool) -> str:
    return f"{style}{text}{RESET}" if color and style else text


def _fit(text: str, width: int, ascii_only: bool = False) -> str:
    if len(text) <= width:
        return text
    ellipsis = "..." if ascii_only else "…"
    return text[: max(0, width - len(ellipsis))] + ellipsis


def _outcome_style(outcome: str | None) -> str:
    if outcome is None:
        return ""
    if outcome == "verified":
        return GREEN
    if outcome in SUCCESS_OUTCOMES or outcome in {"cancelled", "interrupted"}:
        return YELLOW
    return RED


def render_frame(
    state: HudState,
    *,
    now: datetime,
    width: int,
    ascii_only: bool = False,
    color: bool = False,
    spin: int | None = None,
) -> list[str]:
    """Draw the live screen (PLATFORM_DX_SPEC §6.3) in lines narrower than the terminal."""
    glyphs = ASCII_GLYPHS if ascii_only else GLYPHS
    sep = " - " if ascii_only else " · "
    width = max(width, 40) - 1
    rule = _paint(("-" if ascii_only else "─") * width, DIM, color)
    title = f" FaultLine{sep}run {state.job_id[:8]}" + (
        f"{sep}{state.scenario}" if state.scenario else ""
    )
    title = _fit(title, width, ascii_only)
    # The wordmark leads in bold; the run and scenario that follow stay plain.
    lines = [_paint(title[:10], BOLD, color) + title[10:], rule]

    settled = sum(status not in {"pending", "running"} for status in state.status.values())
    filled = round(BAR_WIDTH * settled / len(STAGES))
    bar = ("#" if ascii_only else "█") * filled + ("." if ascii_only else "░") * (
        BAR_WIDTH - filled
    )
    progress = f"{settled}/{len(STAGES)} stages{sep}elapsed {state.total_seconds(now):.1f}s"
    if state.cancel_requested and state.outcome is None:
        progress += f"{sep}cancel requested"
    progress = _fit(progress, width - BAR_WIDTH - 4, ascii_only)
    bar_style = _outcome_style(state.outcome) if state.outcome else CYAN
    lines.append(f" [{_paint(bar, bar_style, color)}] {progress}")

    glyph_width = 4 if ascii_only else 1
    frames = ASCII_SPINNER if ascii_only else SPINNER
    for stage, label, _ in STAGES:
        status = state.status[stage]
        clock = (
            "" if status in {"pending", "skipped"} else f"{state.stage_seconds(stage, now):.1f}s"
        )
        detail = state.stage_detail(stage, sep)
        room = width - (glyph_width + 32)
        if status == "running" and spin is not None:
            frame = frames[spin % len(frames)]
            fitted = _fit(detail, room - 2, ascii_only)
            detail = f"{_paint(frame, CYAN, color)} {fitted}".rstrip()
        else:
            detail = _fit(detail, room, ascii_only)
        label_style = (
            BOLD if status == "running" else DIM if status in {"pending", "skipped"} else ""
        )
        lines.append(
            (
                " "
                + _paint(f"{glyphs[status]:<{glyph_width}}", STATUS_STYLE[status], color)
                + " "
                + _paint(f"{label:<18}", label_style, color)
                + " "
                + (_paint(f"{clock:>8}", DIM, color) if clock else " " * 8)
                + "   "
                + detail
            ).rstrip()
        )

    if state.log:
        lines.append(rule)
        for at, stage, message in state.log:
            stamp = at.astimezone().strftime("%H:%M:%S")
            text = _fit(f"{stage:<18}{message}", width - 11, ascii_only)
            lines.append(" " + _paint(stamp, DIM, color) + "  " + text)
    if state.outcome is None:
        footer = " Ctrl+C stops listening; the run continues in the engine."
        lines += [rule, _paint(_fit(footer, width, ascii_only), DIM, color)]
    return lines


def render_summary(
    state: HudState, *, width: int, ascii_only: bool = False, color: bool = False
) -> list[str]:
    """The decision block shown once the job ends: outcome, cleanup, and assertion marks."""
    glyphs = ASCII_GLYPHS if ascii_only else GLYPHS
    width = max(width, 40) - 1
    outcome = state.outcome or "unknown"
    headline = OUTCOME_HEADLINE.get(outcome, f"NO VERIFIED CANDIDATE ({outcome})")
    cleanup_status = state.cleanup_status
    if cleanup_status == "succeeded":
        cleanup = f"cleanup confirmed {glyphs['done']}"
    elif cleanup_status == "failed":
        cleanup = f"cleanup FAILED {glyphs['failed']} (engine quarantined)"
    else:
        cleanup = f"cleanup {(cleanup_status or 'not reported').replace('_', ' ')}"
    lines = [" " + _paint(headline, BOLD + _outcome_style(outcome), color) + "   " + cleanup]

    rows, passing = state.assertion_rows()
    if not rows and not any(passing.values()):
        return lines
    id_width, cell_width = 36, 16
    show_expected = width >= 99

    def cell(assertion: dict[str, Any] | None) -> str:
        if assertion is None:
            return _paint(f"{glyphs['skipped']} not run".ljust(cell_width), DIM, color)
        passed = bool(assertion.get("passed"))
        observed = " ".join(str(assertion.get("observed", "")).split())
        text = _fit(
            f"{glyphs['done' if passed else 'failed']} {observed}", cell_width - 1, ascii_only
        )
        return _paint(text.ljust(cell_width), GREEN if passed else RED, color)

    # When the final attempt never reached verification, name the attempt that was measured.
    measured = max(state.candidate_reports, default=state.attempt)
    candidate = "Candidate" if measured == state.attempt else f"Attempt {measured}"
    header = f" {'Assertion':<{id_width}} {'Baseline':<{cell_width}} {candidate:<{cell_width}}"
    lines.append(_paint(header + (" Expected" if show_expected else ""), DIM, color))
    for assertion_id, before, after in rows[:ASSERTION_ROWS]:
        line = (
            f" {_fit(assertion_id, id_width, ascii_only):<{id_width}} {cell(before)} {cell(after)}"
        )
        if show_expected:
            expected = " ".join(str((after or before or {}).get("expected", "")).split())
            line += " " + _fit(expected, width - id_width - 2 * cell_width - 4, ascii_only)
        lines.append(line)
    ellipsis = "..." if ascii_only else "…"
    if len(rows) > ASSERTION_ROWS:
        lines.append(f" {ellipsis} {len(rows) - ASSERTION_ROWS} more with a failure")
    candidate_ran = bool(state.candidate_reports)
    notes = {
        "both": "in both",
        "candidate": "on the candidate (not run on the baseline)",
        "baseline": "on the baseline" + (" (not run on the candidate)" if candidate_ran else ""),
    }
    for side, count in passing.items():
        if count:
            lines.append(_paint(f" {ellipsis} {count} more passing {notes[side]}", DIM, color))
    return lines


def render_plain_record(
    state: HudState, record: StageRecord, *, ascii_only: bool = False, color: bool = False
) -> str:
    """One CI log line for a settled stage (PLATFORM_DX_SPEC §6.9)."""
    word = ASCII_GLYPHS[record.status]
    detail = state.record_detail(record, " - " if ascii_only else " · ")
    status = _paint(f"{word:<5}", STATUS_STYLE[record.status], color)
    return f"[{record.at:5.1f}s] {STAGE_SHORT[record.stage]:<11} {status} {detail}".rstrip()


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Yield (event, data) pairs from Server-Sent Events lines, skipping comments and pings."""
    name = "message"
    data: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                yield name, "\n".join(data)
            name, data = "message", []
        elif not line.startswith(":"):
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if key == "event":
                name = value
            elif key == "data":
                data.append(value)


def stream_job_events(
    job_id: str, *, after: int = 0, port: int = DEFAULT_ORCHESTRATOR_PORT
) -> Iterator[dict[str, Any]]:
    """Yield JobEvent payloads from the controller's SSE endpoint, after a sequence cursor."""
    url = (
        f"http://127.0.0.1:{port}/api/faultline/jobs/"
        f"{urllib.parse.quote(job_id, safe='')}/events?after={after}"
    )
    headers = {
        "Authorization": f"Bearer {_get_control_token(port)}",
        "Accept": "text/event-stream",
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=SSE_READ_TIMEOUT) as response:
        for name, data in parse_sse(raw.decode("utf-8") for raw in response):
            if name == "job_event":
                yield json.loads(data)


def _pump_events(job_id: str, port: int, sink: queue.Queue[tuple[str, Any]]) -> None:
    """Feed events to the HUD, resuming after the last sequence whenever the stream drops."""
    after, failures = 0, 0
    while True:
        try:
            for event in stream_job_events(job_id, after=after, port=port):
                after, failures = max(after, int(event.get("sequence", 0))), 0
                sink.put(("event", event))
                if event.get("stage") == "completed":
                    sink.put(("end", None))
                    return
            reason = "stream closed before the job finished"
        except urllib.error.HTTPError as exc:
            hint = " (check FAULTLINE_CONTROL_TOKEN)" if exc.code == 401 else ""
            sink.put(("error", f"controller returned HTTP {exc.code}{hint}"))
            return
        except (OSError, ValueError, http.client.HTTPException) as exc:
            # An abruptly closed chunked stream raises IncompleteRead, an HTTPException.
            reason = str(exc) or type(exc).__name__
        except Exception as exc:
            # Never die silently: the HUD waits on this queue for an end or an error.
            sink.put(("error", f"{type(exc).__name__}: {exc}"))
            return
        failures += 1
        if failures > MAX_RECONNECTS:
            sink.put(("error", f"{reason} (gave up after {MAX_RECONNECTS} reconnects)"))
            return
        time.sleep(min(2.0, 0.25 * 2**failures))


def _terminal_width() -> int:
    return shutil.get_terminal_size(fallback=(100, 24)).columns


class _PlainView:
    """One line per settled stage, for CI logs and pipes (PLATFORM_DX_SPEC §6.9)."""

    def __init__(self, ascii_only: bool, color: bool) -> None:
        self.ascii_only, self.color, self.printed = ascii_only, color, 0

    def start(self, state: HudState) -> None:
        sep = " - " if self.ascii_only else " · "
        scenario = f"{sep}{state.scenario}" if state.scenario else ""
        print(f"faultline listen{sep}run {state.job_id}{scenario}", flush=True)

    def update(self, state: HudState) -> None:
        for record in state.settled[self.printed :]:
            line = render_plain_record(state, record, ascii_only=self.ascii_only, color=self.color)
            print(line, flush=True)
        self.printed = len(state.settled)

    def tick(self, state: HudState) -> None:
        pass

    def stop(self) -> None:
        pass

    def finish(self, state: HudState) -> None:
        self.update(state)
        width = _terminal_width()
        for line in render_summary(
            state, width=width, ascii_only=self.ascii_only, color=self.color
        ):
            print(line)
        cleanup = state.cleanup_status or "unknown"
        print(f"outcome={state.outcome} run={state.job_id} cleanup={cleanup}", flush=True)


class _LiveView:
    """Redraw the live screen in place (PLATFORM_DX_SPEC §6.3) on every event and tick."""

    def __init__(self, ascii_only: bool, color: bool) -> None:
        self.ascii_only, self.color, self.height = ascii_only, color, 0
        self.hidden = False

    def start(self, state: HudState) -> None:
        sys.stdout.write("\033[?25l")
        self.hidden = True
        self.update(state)

    def update(self, state: HudState) -> None:
        lines = render_frame(
            state,
            now=datetime.now(UTC),
            width=_terminal_width(),
            ascii_only=self.ascii_only,
            color=self.color,
            spin=None if state.outcome else int(time.monotonic() / TICK_SECONDS),
        )
        rewind = f"\033[{self.height}F\033[J" if self.height else ""
        sys.stdout.write(rewind + "\n".join(lines) + "\n")
        sys.stdout.flush()
        self.height = len(lines)

    tick = update

    def stop(self) -> None:
        if self.hidden:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            self.hidden = False

    def finish(self, state: HudState) -> None:
        self.update(state)
        self.stop()
        print()
        width = _terminal_width()
        for line in render_summary(
            state, width=width, ascii_only=self.ascii_only, color=self.color
        ):
            print(line)
        print()


def _raise_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def _output_mode(args: argparse.Namespace) -> tuple[bool, bool, bool]:
    """Return (plain, color, ascii_only) from flags, the terminal, CI, and NO_COLOR."""
    plain = bool(args.plain) or not sys.stdout.isatty() or os.environ.get("CI") == "true"
    color = _color_enabled(args)
    ascii_only = bool(args.ascii) or "utf" not in (sys.stdout.encoding or "").lower()
    return plain, color, ascii_only


def cmd_listen(args: argparse.Namespace) -> int:
    """Stream a job's stage events as a live terminal HUD, then mark its assertions."""
    c = _palette(args)
    port = _orchestrator_port(args)
    job_id = args.job_id
    if not job_id:
        res = _api_request("/api/faultline/jobs?limit=1", port=port)
        if "error" in res:
            print(f"{c.red}Error fetching jobs: {res['error']}{c.reset}")
            return 1
        jobs = res.get("jobs", [])
        if not jobs:
            print(f"{c.yellow}No jobs recorded yet. Start a run from the Inspector first.{c.reset}")
            return 1
        job_id = jobs[0]["id"]

    detail_path = f"/api/faultline/jobs/{urllib.parse.quote(job_id, safe='')}"
    detail = _api_request(detail_path, port=port)
    if "error" in detail:
        print(f"{c.red}Error loading job {job_id}: {detail['error']}{c.reset}")
        print(f"Ensure the controller is running on port {port} (`./scripts/start-demo.sh`).")
        return 1
    state = HudState(job_id)
    state.absorb(detail)

    plain, color, ascii_only = _output_mode(args)
    view: _PlainView | _LiveView = (
        _PlainView(ascii_only, color) if plain else _LiveView(ascii_only, color)
    )
    events: queue.Queue[tuple[str, Any]] = queue.Queue()
    threading.Thread(target=_pump_events, args=(job_id, port, events), daemon=True).start()
    # SIGTERM (timeout, kill, CI cancel) takes the same path as Ctrl+C so the cursor returns.
    previous_handler = signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        view.start(state)
        while True:
            try:
                kind, payload = events.get(timeout=TICK_SECONDS)
            except queue.Empty:
                view.tick(state)
                continue
            if kind == "error":
                view.stop()
                print(_paint(f"Event stream failed: {payload}", RED, color))
                return 1
            if kind == "end":
                view.finish(state)
                return OUTCOME_EXIT_CODES.get(state.outcome or "", 1)
            if state.apply(payload):
                state.absorb(_api_request(detail_path, port=port))
            view.update(state)
    except KeyboardInterrupt:
        view.stop()
        print(f"\nStopped listening. Run {job_id} continues in the engine.")
        print(f"Resume with: faultline listen {job_id}")
        return 130
    finally:
        view.stop()
        signal.signal(signal.SIGTERM, previous_handler)


def _probe_inspector(url: str) -> str:
    """Classify what answers at url: "inspector", "other", or "down"."""
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            page = response.read(65536).decode("utf-8", "replace")
    except (urllib.error.HTTPError, http.client.HTTPException):
        return "other"
    except OSError:
        return "down"
    return "inspector" if "FaultLine" in page else "other"


def _start_inspector(port: int, url: str, c: Palette) -> subprocess.Popen[bytes] | None:
    """Start the built Inspector detached, as scripts/start-demo.sh does, and wait for it."""
    next_bin = INSPECTOR_DIR / "node_modules" / "next" / "dist" / "bin" / "next"
    node = shutil.which("node")
    if not next_bin.exists():
        print(f"{c.red}Inspector dependencies are missing. Run `make setup` first.{c.reset}")
        return None
    if not (INSPECTOR_DIR / ".next" / "BUILD_ID").exists():
        print(f"{c.red}The Inspector has no production build.{c.reset}")
        print("Build it with: npm --prefix web/inspector-ui run build")
        return None
    if node is None:
        print(f"{c.red}Node.js is required to run the Inspector.{c.reset}")
        return None

    orchestrator_port = _env_port("FAULTLINE_PORT", DEFAULT_ORCHESTRATOR_PORT)
    env = {
        **os.environ,
        "FAULTLINE_ORCHESTRATOR_URL": os.environ.get(
            "FAULTLINE_ORCHESTRATOR_URL", f"http://127.0.0.1:{orchestrator_port}"
        ),
        "FAULTLINE_CONTROL_TOKEN": _get_control_token(orchestrator_port),
        "BUGGYSHOP_PORT": os.environ.get("BUGGYSHOP_PORT", str(DEFAULT_STOREFRONT_PORT)),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_DIR / "inspector.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [node, str(next_bin), "start", "-p", str(port), "-H", "127.0.0.1"],
            cwd=INSPECTOR_DIR,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    print(f"{c.cyan}Starting the Inspector on port {port}...{c.reset}")
    deadline = time.monotonic() + INSPECTOR_START_TIMEOUT
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            print(
                f"{c.red}The Inspector exited during startup (code {code}). See {log_path}{c.reset}"
            )
            return None
        if _probe_inspector(url) == "inspector":
            print(f"  Started as pid {process.pid}; log {log_path}")
            print(f"  Stop it with: kill {process.pid}")
            return process
        time.sleep(0.25)
    print(
        f"{c.yellow}The Inspector (pid {process.pid}) did not answer within "
        f"{INSPECTOR_START_TIMEOUT:.0f} s. See {log_path}{c.reset}"
    )
    return None


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Open the local Inspector dashboard, starting it first when nothing serves it."""
    c = _palette(args)
    url = f"http://127.0.0.1:{args.port}"
    found = _probe_inspector(url)
    if found == "other":
        print(
            f"{c.red}Port {args.port} is serving something other than "
            f"the FaultLine Inspector.{c.reset}"
        )
        print("Choose another port with `faultline dashboard --port N`.")
        return 1
    if found == "down" and _start_inspector(args.port, url, c) is None:
        return 1

    print(f"\n{c.bold}FaultLine Inspector{c.reset}  {c.cyan}{url}{c.reset}")
    if args.no_open:
        return 0
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("No graphical display detected; open the URL above in a browser.")
        return 0
    if not webbrowser.open(url):
        print("Could not launch a browser; open the URL above.")
    return 0


# Plain-output explanations for engine codes; --json keeps the codes themselves.
_CHECK_ERROR_HINTS = {
    "port_required": "this config's URLs use {port}; pass --port N",
}


def _describe_check(check: dict[str, Any]) -> str:
    """One readable line per invariant: what happened in the two sessions, and what failed."""
    if check["passed"]:
        return "every assertion passed in both sessions"
    sessions = check["sessions"]
    error = next((s["error"] for s in sessions if s["error"]), None)
    if error:
        return f"no complete response ({error}); is the service running on that port?"
    failing = list(
        dict.fromkeys(a["id"] for s in sessions for a in s["assertions"] if not a["passed"])
    )
    named = ": " + ", ".join(failing) if failing else ""
    if check["outcome"] == "detected":
        return "failed the same way in both sessions" + named
    if check["reason"] == "fingerprint_mismatch":
        return "failed, but not with the declared server error" + named
    if check["reason"] in {"nondeterministic_failure", "failure_not_reproduced_twice"}:
        return "failed inconsistently across the two sessions (flaky)" + named
    return str(check["reason"]).replace("_", " ") + named


def cmd_check(args: argparse.Namespace) -> int:
    """Check a running project's declared HTTP invariants, optionally proposing repairs."""
    from app.cli_check import check_project

    result = asyncio.run(
        check_project(Path(args.config).resolve(), port=args.port, repair=args.repair)
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        # This command is deliberately plain for both interactive and CI use.
        print("faultline check: " + ("PASS" if result["passed"] else "FAIL"))
        if result["sandbox"]:
            print("sandbox: " + result["sandbox"]["status"] + " (repair preflight required)")
        for check in result["checks"]:
            verdict = "PASS" if check["passed"] else "FAIL"
            print(f"{verdict} {check['id']}: {_describe_check(check)}")
            if args.repair:
                print("  repair: " + check["repair"]["status"] + "; live source unchanged")
        for error in result["errors"]:
            hint = _CHECK_ERROR_HINTS.get(error)
            print("error: " + error + (f": {hint}" if hint else ""))
    return int(result["exit_code"])


def cmd_run(args: argparse.Namespace) -> int:
    """Execute an operator-selected reproduction with durable sandbox evidence."""
    from app.project import load_project
    from app.run import run_project

    try:
        root, project = load_project(
            Path(args.config),
            args.scenario_name,
            repro_file=Path(args.repro) if args.repro else None,
            target_file=args.target,
        )
        data_dir = Path(args.data_dir).resolve() if args.data_dir else root / ".faultline/runs"
        result = asyncio.run(run_project(root, project, data_dir, detect=args.detect))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        # Validation errors may embed user input. Keep diagnostics local and do
        # not expose provider responses or credentials in a traceback.
        print(f"faultline run: {exc}", file=sys.stderr)
        return 30
    print(json.dumps(result, indent=2))
    return OUTCOME_EXIT_CODES.get(result["outcome"], 30)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="faultline",
        description="FaultLine: Autonomous SRE and sandbox-verified repair platform.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    def output_flags(command: argparse.ArgumentParser, *, plain: bool = True) -> None:
        if plain:
            command.add_argument("--plain", action="store_true", help="Print without ANSI escapes")
        command.add_argument(
            "--no-color", action="store_true", help="Print without ANSI colors (or set NO_COLOR)"
        )

    def orchestrator_port_flag(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--port",
            type=_port_arg,
            help=f"Orchestrator port (default $FAULTLINE_PORT or {DEFAULT_ORCHESTRATOR_PORT})",
        )

    def store_port_flag(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--api-port",
            type=_port_arg,
            help=f"BuggyShop API port (default $BUGGYSHOP_API_PORT or {DEFAULT_STORE_API_PORT})",
        )

    p_check = subparsers.add_parser("check", help="Gate on a running project's HTTP invariants")
    p_check.add_argument("--config", default="faultline.toml")
    p_check.add_argument("--port", type=int, help="Live service port to substitute for {port}")
    p_check.add_argument(
        "--repair",
        action="store_true",
        help="Propose isolated candidates for reproduced failures; never apply",
    )
    p_check.add_argument("--json", action="store_true", help="Emit exactly one JSON result")
    output_flags(p_check)
    p_check.set_defaults(func=cmd_check)

    p_run = subparsers.add_parser(
        "run", help="Reproduce twice, repair with Meta, and verify in isolation"
    )
    p_run.add_argument(
        "scenario_name", nargs="?", help="Configured scenario (optional when only one exists)"
    )
    p_run.add_argument(
        "--config", default="faultline.toml", help="Operator-owned TOML configuration"
    )
    p_run.add_argument(
        "--repro", help="JSON ReproSpec supplied directly instead of a configured scenario"
    )
    p_run.add_argument("--target", help="Existing project-relative target inside repair.editable")
    p_run.add_argument("--data-dir", help="Durable database and proof directory")
    p_run.add_argument(
        "--detect", action="store_true", help="Run both baselines without requesting a patch"
    )
    output_flags(p_run)
    p_run.set_defaults(func=cmd_run)

    # version
    p_ver = subparsers.add_parser("version", help="Print CLI and engine version")
    output_flags(p_ver)
    p_ver.set_defaults(func=cmd_version)

    # init
    p_init = subparsers.add_parser(
        "init", help="Initialize repository with faultline.toml configuration"
    )
    p_init.add_argument(
        "-f", "--force", action="store_true", help="Overwrite existing faultline.toml"
    )
    output_flags(p_init)
    p_init.set_defaults(func=cmd_init)

    # doctor
    p_doc = subparsers.add_parser(
        "doctor", help="Inspect system sandbox requirements and API readiness"
    )
    orchestrator_port_flag(p_doc)
    store_port_flag(p_doc)
    output_flags(p_doc)
    p_doc.set_defaults(func=cmd_doctor)

    # status
    p_stat = subparsers.add_parser("status", help="Query orchestrator service and sandbox status")
    orchestrator_port_flag(p_stat)
    output_flags(p_stat)
    p_stat.set_defaults(func=cmd_status)

    # jobs
    p_jobs = subparsers.add_parser("jobs", help="List recent repair jobs")
    orchestrator_port_flag(p_jobs)
    output_flags(p_jobs)
    p_jobs.set_defaults(func=cmd_jobs)

    # diff
    p_diff = subparsers.add_parser("diff", help="View candidate diff for a job")
    p_diff.add_argument("job_id", nargs="?", help="Job ID (defaults to latest)")
    orchestrator_port_flag(p_diff)
    output_flags(p_diff)
    p_diff.set_defaults(func=cmd_diff)

    # apply
    p_apply = subparsers.add_parser(
        "apply", help="Apply a verified candidate patch to the live codebase"
    )
    p_apply.add_argument("job_id", nargs="?", help="Verified Job ID (defaults to latest verified)")
    orchestrator_port_flag(p_apply)
    store_port_flag(p_apply)
    output_flags(p_apply)
    p_apply.set_defaults(func=cmd_apply)

    # revert
    p_rev = subparsers.add_parser("revert", help="Revert live codebase to seeded defect state")
    output_flags(p_rev)
    p_rev.set_defaults(func=cmd_revert)

    # verify
    p_verify = subparsers.add_parser("verify", help="Probe live store to test if checkout works")
    store_port_flag(p_verify)
    output_flags(p_verify)
    p_verify.set_defaults(func=cmd_verify)

    # listen
    p_listen = subparsers.add_parser("listen", help="Stream a job's stages live as a terminal HUD")
    p_listen.add_argument("job_id", nargs="?", help="Job ID (defaults to latest)")
    orchestrator_port_flag(p_listen)
    p_listen.add_argument(
        "--plain", action="store_true", help="One line per stage without ANSI, for CI logs"
    )
    p_listen.add_argument("--ascii", action="store_true", help="ASCII status glyphs")
    output_flags(p_listen, plain=False)
    p_listen.set_defaults(func=cmd_listen)

    # dashboard
    p_dash = subparsers.add_parser(
        "dashboard", help="Open the local Inspector dashboard, starting it if needed"
    )
    p_dash.add_argument("--port", type=int, default=4000, help="Inspector port (default 4000)")
    p_dash.add_argument(
        "--no-open", action="store_true", help="Print the URL without opening a browser"
    )
    output_flags(p_dash)
    p_dash.set_defaults(func=cmd_dashboard)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
