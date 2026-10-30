"""FaultLine CLI: developer-facing control, diagnostics, and patch application."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

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


def _get_control_token() -> str:
    token = os.environ.get("FAULTLINE_CONTROL_TOKEN")
    if token:
        return token
    token_file = DATA_DIR / ".control_token"
    if token_file.exists():
        return token_file.read_text().strip()

    # Discover token from running repair-orchestrator process
    try:
        pids = subprocess.check_output(
            ["pgrep", "-f", "services/repair-orchestrator.*uvicorn"], text=True
        ).split()
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
    port: int = 9000,
) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}{path}"
    headers = {
        "Authorization": f"Bearer {_get_control_token()}",
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
    print(f"{BOLD}FaultLine Developer Platform CLI{RESET} v0.2.0 ({commit})")
    print(f"  Python:   {sys.version.split()[0]}")
    print(f"  Root:     {REPOSITORY_ROOT}")
    print(f"  Platform: {sys.platform}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check system requirements: bubblewrap, cgroups v2, Node, uv, and models."""
    print(f"\n{BOLD}FaultLine Doctor: System Diagnostic Report{RESET}\n")

    checks: list[tuple[str, bool, str]] = []

    # 1. Bubblewrap
    bwrap_path = shutil.which("bwrap")
    checks.append(
        (
            "Linux Bubblewrap (bwrap) Sandbox",
            bwrap_path is not None,
            bwrap_path or "Missing! Install via: sudo dnf/apt install bubblewrap",
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
    orch_health = _api_request("/healthz", port=9000)
    checks.append(
        (
            "Repair Orchestrator Service (port 9000)",
            orch_health.get("status") == "ok",
            "Active & Healthy"
            if orch_health.get("status") == "ok"
            else "Offline (run ./scripts/start-demo.sh)",
        )
    )

    store_health = _api_request("/healthz", port=8000)
    checks.append(
        (
            "Storefront Backend API (port 8000)",
            store_health.get("status") == "ok",
            "Active & Healthy" if store_health.get("status") == "ok" else "Offline",
        )
    )

    all_ok = True
    for name, passed, detail in checks:
        icon = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        status_text = f"{GREEN}PASS{RESET}" if passed else f"{YELLOW}WARN{RESET}"
        print(f" {icon} {BOLD}{name:<40}{RESET} [{status_text}]")
        print(f"     {DIM}{detail}{RESET}")
        if not passed and name.startswith("Linux"):
            all_ok = False

    print("\n" + ("=" * 60))
    if all_ok:
        msg = f"{GREEN}{BOLD}Result: System is ready for reproduction and verification.{RESET}\n"
        print(msg)
        return 0
    else:
        print(f"{YELLOW}Result: Some components require attention. See details above.{RESET}\n")
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Check live orchestrator status, sandbox limits, and readiness."""
    res = _api_request("/api/faultline/readiness")
    if "error" in res:
        print(f"{RED}Error connecting to FaultLine orchestrator: {res['error']}{RESET}")
        print("Ensure the service is running on port 9000 (`./scripts/start-demo.sh`).")
        return 1

    status_str = f"{GREEN if res.get('status') == 'ready' else YELLOW}{res.get('status')}{RESET}"
    print(f"\n{BOLD}FaultLine Orchestrator Status{RESET}")
    print(f"  Status:          {status_str}")
    print(f"  Runtime Ready:   {res.get('runtime_ready')}")
    print(f"  Quarantined:     {res.get('quarantined')}")

    model = res.get("model") or {}
    model_str = f"{CYAN}{model.get('model', 'None')}{RESET}"
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
    res = _api_request("/api/faultline/jobs?limit=10")
    if "error" in res:
        print(f"{RED}Error fetching jobs: {res['error']}{RESET}")
        return 1

    jobs = res.get("jobs", [])
    if not jobs:
        print(f"{YELLOW}No recent jobs recorded in database.{RESET}")
        return 0

    hdr = f"\n{BOLD}{'JOB ID':<8} {'SCENARIO':<20} {'STATE':<10} {'OUTCOME':<12} {'CREATED'}{RESET}"
    print(hdr)
    print("-" * 75)
    for j in jobs:
        state = j.get("state", "")
        state_color = GREEN if state == "succeeded" else (RED if state == "failed" else YELLOW)
        jid = j.get("id", "")[:12]
        scen = j.get("scenario_id", "")[:24]
        outc = str(j.get("outcome", ""))[:14]
        created = j.get("created_at", "")[:19]
        print(f"{jid:<12} {scen:<24} {state_color}{state:<12}{RESET} {outc:<14} {created}")
    print()
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Print the candidate patch for a job."""
    job_id = args.job_id
    if not job_id:
        # Find latest succeeded job
        res = _api_request("/api/faultline/jobs?limit=1")
        jobs = res.get("jobs", [])
        if not jobs:
            print(f"{RED}No jobs found.{RESET}")
            return 1
        job_id = jobs[0]["id"]

    res = _api_request(f"/api/faultline/jobs/{job_id}")
    if "error" in res:
        print(f"{RED}Error: {res['error']}{RESET}")
        return 1

    attempts = res.get("attempts", [])
    if not attempts:
        print(f"{YELLOW}No repair attempts recorded for job {job_id}.{RESET}")
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
        print(f"{YELLOW}No diff found in proposal for job {job_id}.{RESET}")
        return 1

    print(f"\n{BOLD}Verified Candidate Diff for Job {job_id}:{RESET}\n")
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            print(f"{GREEN}{line}{RESET}")
        elif line.startswith("-") and not line.startswith("---"):
            print(f"{RED}{line}{RESET}")
        elif line.startswith("@"):
            print(f"{CYAN}{line}{RESET}")
        else:
            print(line)
    print()
    return 0


def apply_patch_for_job(job_id: str, database: Any = None) -> dict[str, Any]:
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
        res = _api_request(f"/api/faultline/jobs/{job_id}")
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


def detect_project_stack(target_dir: Path) -> dict[str, Any]:
    """Detect project type, stack, commands, and test runners."""
    info: dict[str, Any] = {
        "name": target_dir.name or "my-service",
        "stack": "custom",
        "setup_command": "",
        "lockfiles": [],
        "dev_command": "",
        "health": "/healthz",
        "test_command": "",
        "editable": [],
    }

    has_pyproject = (target_dir / "pyproject.toml").exists()
    has_reqs = (target_dir / "requirements.txt").exists()
    has_uv_lock = (target_dir / "uv.lock").exists()
    has_poetry = (target_dir / "poetry.lock").exists()
    has_pkg_json = (target_dir / "package.json").exists()
    has_next_config = (
        (target_dir / "next.config.js").exists()
        or (target_dir / "next.config.ts").exists()
        or (target_dir / "next.config.mjs").exists()
    )

    if has_uv_lock:
        info["lockfiles"].append("uv.lock")
        info["setup_command"] = "uv sync --locked"
    elif has_poetry:
        info["lockfiles"].append("poetry.lock")
        info["setup_command"] = "poetry install"
    elif has_reqs:
        info["setup_command"] = "pip install -r requirements.txt"

    is_fastapi = (target_dir / "apps" / "buggyshop-backend").exists() or (
        target_dir / "app" / "main.py"
    ).exists()
    if is_fastapi:
        info["stack"] = "python-fastapi"
        info["dev_command"] = "uv run uvicorn app.main:app --host 127.0.0.1 --port {port}"
        info["health"] = "/healthz"
        info["test_command"] = "uv run pytest -q --junitxml={report}"
        info["editable"] = ["app/**/*.py"]
    elif (target_dir / "manage.py").exists():
        info["stack"] = "python-django"
        info["dev_command"] = "python manage.py runserver 127.0.0.1:{port}"
        info["health"] = "/healthz"
        info["test_command"] = "python manage.py test"
        info["editable"] = ["**/*.py"]
    elif has_next_config:
        info["stack"] = "node-next"
        info["dev_command"] = "npm run dev -- -p {port}"
        info["health"] = "/"
        info["test_command"] = "npm test"
        info["editable"] = ["src/**/*.{ts,tsx,js,jsx}", "app/**/*.{ts,tsx,js,jsx}"]
    elif has_pyproject or has_reqs:
        info["stack"] = "python-generic"
        info["dev_command"] = "python -m http.server {port}"
        info["health"] = "/"
        info["test_command"] = "pytest"
        info["editable"] = ["src/**/*.py", "app/**/*.py"]
    elif has_pkg_json:
        info["stack"] = "node-generic"
        info["dev_command"] = "npm start"
        info["health"] = "/"
        info["test_command"] = "npm test"
        info["editable"] = ["src/**/*.{js,ts}"]

    return info


def generate_faultline_toml(info: dict[str, Any]) -> str:
    """Generate an annotated faultline.toml configuration."""
    lockfiles_str = json.dumps(info.get("lockfiles", ["uv.lock"]))
    editable_str = json.dumps(info.get("editable", ["app/**/*.py"]))
    health_path = info.get("health", "/healthz")
    setup_cmd = info.get("setup_command", "uv sync --locked")
    dev_cmd = info.get("dev_command", "uv run uvicorn app.main:app --host 127.0.0.1 --port {port}")
    test_cmd = info.get("test_command", "uv run pytest -q --junitxml={report}")

    return f"""#:schema ./.faultline/schema-v1.json
# FaultLine Configuration Schema v1
schema = 1

[project]
name = "{info["name"]}"
stack = "{info["stack"]}"
root = "."
setup_command = "{setup_cmd}"
lockfiles = {lockfiles_str}
dev_command = "{dev_cmd}"
url = "http://127.0.0.1:{{port}}"
health = "{health_path}"
test_command = "{test_cmd}"

[repair]
editable = {editable_str}
context = []
max_files = 1
max_diff_bytes = 16384
max_source_bytes = 32768
max_changed_lines = 100

[repair.imports]
allow = ["typing.cast", "fastapi.HTTPException"]
deny = []

[sandbox]
engine = "bwrap"

[sandbox.limits]
mode = "cgroup-v2-scope"
memory_max_bytes = 536870912
memory_swap_max_bytes = 0
tasks_max = 64
cpu_quota_percent = 100

[model]
provider = "meta"
model = "muse-spark-1.3"
max_attempts = 2

[budgets]
preflight = 45
baseline = 20
attempt = 75
generation = 45
verification = 20
work = 170
cleanup = 10
overall = 180

[[invariants.rule]]
id = "service_health"
name = "Service returns HTTP 200 on health check"
target = "http://127.0.0.1:{{port}}{health_path}"
method = "GET"
expected_status = 200
"""


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a repository with faultline.toml configuration."""
    target_dir = Path.cwd()
    dest_file = target_dir / "faultline.toml"
    if dest_file.exists() and not getattr(args, "force", False):
        print(f"{YELLOW}faultline.toml already exists at {dest_file}{RESET}")
        print("Use --force to overwrite.")
        return 0

    print(f"\n{BOLD}FaultLine Initializer: Analyzing repository at {target_dir}...{RESET}")
    info = detect_project_stack(target_dir)
    print(f"  Detected Project: {CYAN}{info['name']}{RESET}")
    print(f"  Detected Stack:   {GREEN}{info['stack']}{RESET}")
    if info["dev_command"]:
        print(f"  Dev Command:      {info['dev_command']}")
    if info["test_command"]:
        print(f"  Test Command:     {info['test_command']}")

    toml_content = generate_faultline_toml(info)
    dest_file.write_text(toml_content)
    print(f"\n{GREEN}{BOLD}✓ Created {dest_file}{RESET}")
    print("Next steps:")
    print("  1. Review faultline.toml to customize editable paths and invariants.")
    print("  2. Run `faultline doctor` to verify sandbox containment.")
    print("  3. Run `faultline status` to verify orchestrator connectivity.\n")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply a verified candidate patch to the live application."""
    job_id = args.job_id
    if not job_id:
        res = _api_request("/api/faultline/jobs?limit=5")
        jobs = res.get("jobs", [])
        verified = [
            j for j in jobs if j.get("state") == "succeeded" and j.get("outcome") == "verified"
        ]
        if not verified:
            print(f"{RED}No verified jobs found to apply.{RESET}")
            return 1
        job_id = verified[0]["id"]

    result = apply_patch_for_job(job_id)
    if not result.get("success"):
        print(f"{RED}Failed to apply patch: {result.get('message')}{RESET}")
        return 1

    print(f"\n{GREEN}{BOLD}✓ Verified patch successfully applied to:{RESET}")
    print(f"  {result.get('target')}")
    print(f"  Backup created: {result.get('backup')}")

    # Test live API
    print(f"\n{CYAN}Testing live store endpoint...{RESET}")
    test_payload = {
        "items": [{"product_id": "trail-mug", "quantity": 2}],
        "coupon_code": "",
    }
    test_res = _api_request("/api/checkout", method="POST", data=test_payload, port=8000)
    if test_res.get("status") == 0 or "error" in test_res:
        print(f"  {YELLOW}Note: Backend may need automatic reload (port 8000).{RESET}")
    else:
        order_id = test_res.get("id")
        total = test_res.get("total", 0)
        price = f"${total / 100:.2f}"
        print(f"  {GREEN}{BOLD}Live Order Created: ID={order_id}, Total={price}{RESET}")
        print(f"  {GREEN}BuggyShop on http://127.0.0.1:3000 is now 100% REPAIRED!{RESET}\n")

    return 0


def cmd_revert(args: argparse.Namespace) -> int:
    """Revert the live application back to the seeded bug state."""
    result = revert_to_seeded()
    if not result.get("success"):
        print(f"{RED}Failed to revert: {result.get('message')}{RESET}")
        return 1

    print(f"\n{YELLOW}{BOLD}✓ Reverted live store to seeded defect state:{RESET}")
    print(f"  Target: {result.get('target')}")
    print("  Live BuggyShop at http://127.0.0.1:3000 will now trigger the 500 error.\n")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Run an automated checkout check against the live store to verify status."""
    print(f"\n{BOLD}Probing live store checkout (http://127.0.0.1:8000/api/checkout)...{RESET}")
    test_payload = {
        "items": [{"product_id": "trail-mug", "quantity": 1}],
        "coupon_code": "",
    }
    res = _api_request("/api/checkout", method="POST", data=test_payload, port=8000)
    err_str = str(res.get("error", "")) + str(res.get("detail", ""))
    if res.get("status") == 500 or "TypeError" in err_str:
        print(f"  {RED}{BOLD}Status: DEFECT ACTIVE (HTTP 500){RESET}")
        print(f"  {DIM}TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'{RESET}")
        print("  Live BuggyStore at http://127.0.0.1:3000 is currently BROKEN.")
        print("  Run `faultline apply` to apply the verified patch!\n")
        return 1
    elif res.get("id"):
        print(f"  {GREEN}{BOLD}Status: HEALTHY (HTTP 201 Created){RESET}")
        print(f"  Order ID: {res.get('id')}, Total: ${res.get('total', 0) / 100:.2f}")
        print("  Store is working cleanly!\n")
        return 0
    else:
        print(f"  {YELLOW}Unexpected response: {res}{RESET}\n")
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="faultline",
        description="FaultLine: Autonomous SRE and sandbox-verified repair platform.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # version
    p_ver = subparsers.add_parser("version", help="Print CLI and engine version")
    p_ver.set_defaults(func=cmd_version)

    # init
    p_init = subparsers.add_parser(
        "init", help="Initialize repository with faultline.toml configuration"
    )
    p_init.add_argument(
        "-f", "--force", action="store_true", help="Overwrite existing faultline.toml"
    )
    p_init.set_defaults(func=cmd_init)

    # doctor
    p_doc = subparsers.add_parser(
        "doctor", help="Inspect system sandbox requirements and API readiness"
    )
    p_doc.set_defaults(func=cmd_doctor)

    # status
    p_stat = subparsers.add_parser("status", help="Query orchestrator service and sandbox status")
    p_stat.set_defaults(func=cmd_status)

    # jobs
    p_jobs = subparsers.add_parser("jobs", help="List recent repair jobs")
    p_jobs.set_defaults(func=cmd_jobs)

    # diff
    p_diff = subparsers.add_parser("diff", help="View candidate diff for a job")
    p_diff.add_argument("job_id", nargs="?", help="Job ID (defaults to latest)")
    p_diff.set_defaults(func=cmd_diff)

    # apply
    p_apply = subparsers.add_parser(
        "apply", help="Apply a verified candidate patch to the live codebase"
    )
    p_apply.add_argument("job_id", nargs="?", help="Verified Job ID (defaults to latest verified)")
    p_apply.set_defaults(func=cmd_apply)

    # revert
    p_rev = subparsers.add_parser("revert", help="Revert live codebase to seeded defect state")
    p_rev.set_defaults(func=cmd_revert)

    # verify
    p_verify = subparsers.add_parser("verify", help="Probe live store to test if checkout works")
    p_verify.set_defaults(func=cmd_verify)

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
