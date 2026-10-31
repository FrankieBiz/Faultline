"""Strict live-check admission and optional, gated project repair orchestration."""

import contextlib
import shlex
import shutil
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator

from app.probes import (
    Invariant,
    ProjectConfig,
    build_spec,
    load_project_config,
    resolve_url,
    run_check,
    split_target,
    validate_target,
)
from app.project import ProjectSettings, RepairSettings, load_project
from app.repro import AssertionCheck, ReproSpec, ServicePath
from app.run import run_project
from shared.contracts.models import ContractModel


class Limits(ContractModel):
    mode: Literal["cgroup-v2-scope"] = "cgroup-v2-scope"
    memory_max_bytes: Literal[536870912] = 536870912
    memory_swap_max_bytes: Literal[0] = 0
    tasks_max: Literal[64] = 64
    cpu_quota_percent: Literal[100] = 100

    @field_validator(
        "memory_max_bytes", "memory_swap_max_bytes", "tasks_max", "cpu_quota_percent", mode="before"
    )
    @classmethod
    def integer_limits(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("sandbox limits must be integers")
        return value


class Sandbox(ContractModel):
    engine: Literal["bwrap"] = "bwrap"
    limits: Limits = Field(default_factory=Limits)


class Model(ContractModel):
    provider: Literal["meta"] = "meta"
    model: str = Field(default="muse-spark-1.3", min_length=1)
    max_attempts: int = Field(default=2, ge=1, le=2)


class Budgets(ContractModel):
    preflight: float = Field(default=45, gt=0, le=3600)
    baseline: float = Field(default=20, gt=0, le=3600)
    attempt: float = Field(default=75, gt=0, le=3600)
    generation: float = Field(default=45, gt=0, le=3600)
    verification: float = Field(default=20, gt=0, le=3600)
    work: float = Field(default=170, gt=0, le=3600)
    cleanup: float = Field(default=10, gt=0, le=3600)
    overall: float = Field(default=180, gt=0, le=3600)


class Request(ContractModel):
    path: ServicePath
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    json_body: Any = Field(default=None, alias="json")


class Rule(ContractModel):
    id: str
    name: str | None = None
    description: str | None = None
    fingerprint: str | None = None
    target: str | None = None
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    expected_status: int | None = Field(default=None, ge=100, le=599)
    json_body: Any = Field(default=None, alias="json")
    request: Request | None = None
    assertions: list[AssertionCheck] = Field(default_factory=list, alias="assert")


class Invariants(ContractModel):
    rule: list[Rule] = Field(default_factory=list)


class Configuration(ContractModel):
    schema_version: Literal[1] = Field(alias="schema")
    project: ProjectSettings
    repair: RepairSettings | None = None
    sandbox: Sandbox = Field(default_factory=Sandbox)
    model: Model = Field(default_factory=Model)
    budgets: Budgets = Field(default_factory=Budgets)
    invariants: Invariants = Field(default_factory=Invariants)
    scenarios: dict[str, dict[str, Any]] | list[dict[str, Any]] = Field(default_factory=dict)
    repro: ReproSpec | None = None


@dataclass(frozen=True)
class CheckedConfig:
    settings: Configuration
    live: ProjectConfig
    root: Path


def validate_config(path: Path) -> CheckedConfig:
    """Validate the entire document before sending even one request."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if type(data.get("schema")) is not int:
        raise ValueError("schema must be the integer 1")
    config = Configuration.model_validate(data)
    command = config.project.dev_command
    argv = shlex.split(command) if isinstance(command, str) else command
    if not argv or any(not arg.strip() for arg in argv):
        raise ValueError("project.dev_command must contain an executable and arguments")
    validate_target(config.project.url, placeholder=True)
    root = (path.parent / config.project.root).resolve()
    if not root.is_dir():
        raise ValueError("project.root does not exist")
    for rule in config.invariants.rule:
        if rule.request is not None:
            if rule.model_fields_set & {"target", "method", "expected_status", "json_body"}:
                raise ValueError("a rule cannot mix request/assert with target/expected_status")
            if not rule.assertions:
                raise ValueError("request rules require assertions")
        elif rule.target is None or rule.expected_status is None or rule.assertions:
            raise ValueError("target rules require target and expected_status only")
    definitions = (
        config.scenarios.values() if isinstance(config.scenarios, dict) else config.scenarios
    )
    allowed = {
        "id",
        "title",
        "description",
        "target_file",
        "repro",
        "version",
        "timeout_ms",
        "fingerprint",
        "steps",
    }
    for definition in definitions:
        if set(definition) - allowed:
            raise ValueError("unknown scenario fields")
        for key in ("id", "title", "description", "target_file"):
            if key in definition and not isinstance(definition[key], str):
                raise ValueError(f"scenario.{key} must be a string")
        if "repro" in definition and set(definition) & {
            "version",
            "timeout_ms",
            "fingerprint",
            "steps",
        }:
            raise ValueError("a scenario cannot mix repro and inline steps")
    if config.repro is not None and config.scenarios:
        raise ValueError("declare scenarios or repro, not both")
    if config.repair and set(config.repair.imports) - {"allow", "deny"}:
        raise ValueError("repair.imports supports only allow and deny")
    live = load_project_config(path, path.parent)
    if live.errors:
        raise ValueError("; ".join(live.errors))
    if not live.invariants:
        raise ValueError("configuration must declare at least one invariant or scenario")
    for invariant in live.invariants:
        if invariant.live_note:
            raise ValueError(f"{invariant.id}: {invariant.live_note} Use faultline run.")
        # Validate generated request steps too, including paths in target-form rules.
        _, route = split_target(invariant.url.replace("{port}", "1"))
        build_spec(invariant, route)
    return CheckedConfig(config, live, root)


def sandbox_readiness() -> dict[str, Any]:
    """Doctor's local prerequisites; existence is never claimed as enforced isolation.

    Checks require these prerequisites but do not execute project code. ProjectRuntime
    performs namespace/cgroup enforcement probes before a repair may launch code.
    """
    prerequisites = {
        "bubblewrap": shutil.which("bwrap") is not None,
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").is_file(),
        "systemd_run": shutil.which("systemd-run") is not None,
        "node": shutil.which("node") is not None,
        "uv": shutil.which("uv") is not None,
    }
    return {
        "prerequisites": prerequisites,
        "prerequisites_available": all(prerequisites.values()),
        "runtime_ready": None,
        "status": "unverified" if all(prerequisites.values()) else "unavailable",
        "note": "Sandbox prerequisites are required. Repair also requires namespace and "
        "cgroup preflight; installed tools alone do not establish readiness.",
    }


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    return str(exc)


async def _repair(path: Path, config: CheckedConfig, invariant: Invariant) -> dict[str, Any]:
    """Select only an explicitly owned target, then let the runner enforce every gate."""
    if invariant.source == "scenario":
        root, run = load_project(path, invariant.id.removeprefix("scenario."))
    elif config.settings.repair and config.settings.repair.target_file:
        # A rule needs an explicit target; never infer one from an HTTP route.
        _, route = split_target(invariant.url.replace("{port}", "1"))
        spec = build_spec(invariant, route)
        with tempfile.TemporaryDirectory(prefix="faultline-check-") as directory:
            repro = Path(directory) / "repro.json"
            repro.write_text(spec.model_dump_json())
            root, run = load_project(path, repro_file=repro)
    else:
        return {
            "status": "unsupported",
            "reason": "Declare repair.target_file or a scenario target_file; no source target "
            "is inferred.",
        }
    result = await run_project(root, run, root / ".faultline/runs", detect=False)
    verified = (
        result.get("outcome") == "verified"
        and result.get("cleanup") == "succeeded"
        and bool(result.get("proof_bundle"))
    )
    return {
        "status": "verified_candidate" if verified else "unresolved",
        "applied": False,
        "result": result,
    }


async def check_project(path: Path, *, port: int | None, repair: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": 1,
        "command": "check",
        "passed": False,
        "checks": [],
        "errors": [],
        "sandbox": None,
        "repair_requested": repair,
        "source_applied": False,
    }
    try:
        config = validate_config(path)
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        # Resolve all ports before sending requests; don't partially check malformed input.
        for invariant in config.live.invariants:
            validate_target(resolve_url(invariant.url, port))
        readiness = sandbox_readiness()
        report["sandbox"] = readiness
        if not readiness["prerequisites_available"]:
            report["errors"].append("Sandbox prerequisites missing; run faultline doctor.")
        for invariant in config.live.invariants:
            record = await run_check(
                invariant, port=port, live_store_url="", scenarios={}, redact=lambda _: "[omitted]"
            )
            expected = len(invariant.matchers())
            # no_failure can mean flaky/mismatched failure, not a pass. Require every
            # assertion in both fresh sessions, with no execution/cleanup error.
            passed = (
                record.outcome == "no_failure"
                and len(record.sessions) == 2
                and all(
                    s.error is None
                    and len(s.assertions) == expected
                    and all(a.passed for a in s.assertions)
                    for s in record.sessions
                )
            )
            item: dict[str, Any] = {
                "id": invariant.id,
                "passed": passed,
                "outcome": record.outcome,
                "reason": record.reason,
                "sessions": [s.model_dump() for s in record.sessions],
                "repair": {"status": "not_requested" if not repair else "not_needed"},
            }
            report["checks"].append(item)
            if repair and not passed:
                if record.outcome != "detected":
                    item["repair"] = {
                        "status": "not_reproduced",
                        "reason": "Live failure did not repeat identically; no repair requested.",
                    }
                elif not readiness["prerequisites_available"]:
                    item["repair"] = {
                        "status": "unavailable",
                        "reason": "Sandbox prerequisites missing; run faultline doctor.",
                    }
                else:
                    try:
                        # Any runner/library diagnostics belong on stderr, even in JSON mode.
                        with contextlib.redirect_stdout(sys.stderr):
                            item["repair"] = await _repair(path, config, invariant)
                    except (OSError, ValueError, RuntimeError) as exc:
                        item["repair"] = {"status": "error", "reason": _safe_error(exc)}
        report["passed"] = (
            not report["errors"]
            and bool(report["checks"])
            and all(c["passed"] for c in report["checks"])
        )
    except (OSError, ValueError, RuntimeError) as exc:
        report["errors"].append(_safe_error(exc))
    report["exit_code"] = 0 if report["passed"] else 1
    return report
