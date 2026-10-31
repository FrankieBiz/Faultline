"""Operator-owned project configuration and immutable, repository-independent exports."""

import ast
import hashlib
import json
import shlex
import shutil
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from app.policy import PatchPolicyError, parse_unified_diff
from app.repro import AssertStep, ReproSpec, ServicePath
from app.snapshots import Snapshot, SnapshotManager, contained_path
from shared.config import Scenario
from shared.contracts.models import ContractModel, PatchValidationResult


def source_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or any(part.startswith(".") for part in path.parts)
        or any(char.isspace() for char in value)
        or "\\" in value
        or any(part.lower() in {"meta-provided", "id_rsa", "id_ed25519"} for part in path.parts)
        or path.suffix in {".pem", ".key"}
    ):
        raise ValueError("expected an ordinary, non-secret project-relative path")
    return value


class ProjectSettings(ContractModel):
    name: str = "project"
    root: str = "."
    dev_command: str | list[str]
    health: ServicePath = "/"
    url: str = "http://127.0.0.1:{port}"
    stack: str = ""
    setup_command: str = ""
    test_command: str = ""
    lockfiles: list[str] = Field(default_factory=list)


class RepairSettings(ContractModel):
    editable: list[str] = Field(min_length=1)
    target_file: str | None = None
    context: list[str] = Field(default_factory=list)
    max_files: Literal[1] = 1
    max_diff_bytes: int = Field(default=16384, ge=1, le=16384)
    max_source_bytes: int = Field(default=32768, ge=1, le=32768)
    max_changed_lines: int = Field(default=100, ge=1, le=100)
    imports: dict[str, list[str]] = Field(default_factory=dict)


class ProjectRun(ContractModel):
    """A detached, validated selection; never stored in the global demo registry."""

    project: ProjectSettings
    repair: RepairSettings
    scenario: Scenario
    repro: ReproSpec
    model: str = "muse-spark-1.3"
    max_attempts: int = Field(default=2, ge=1, le=2)
    budgets: dict[str, float] = Field(default_factory=dict)

    def command(self, port: int) -> list[str]:
        value = self.project.dev_command
        argv = shlex.split(value) if isinstance(value, str) else list(value)
        if not argv or not all(isinstance(arg, str) and arg for arg in argv):
            raise ValueError("project.dev_command must contain an executable and arguments")
        return [arg.replace("{port}", str(port)) for arg in argv]


def load_project(
    config: Path,
    name: str | None = None,
    *,
    repro_file: Path | None = None,
    target_file: str | None = None,
) -> tuple[Path, ProjectRun]:
    """Read TOML scenarios or a CLI JSON ReproSpec, rejecting ambiguous selection."""
    config = config.resolve()
    data = tomllib.loads(config.read_text())
    if data.get("schema") != 1:
        raise ValueError("faultline.toml requires schema = 1")
    if "project" not in data or "repair" not in data:
        raise ValueError("faultline.toml requires project and repair tables")
    project = ProjectSettings.model_validate(data["project"])
    repair = RepairSettings.model_validate(data["repair"])
    root = (config.parent / project.root).resolve()
    if not root.is_dir():
        raise ValueError("project.root does not exist")
    definitions = data.get("scenarios", {})
    if isinstance(definitions, list):
        ids = [item["id"] for item in definitions]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate scenario id")
        definitions = {item["id"]: item for item in definitions}
    if not isinstance(definitions, dict):
        raise ValueError("scenarios must be a table or array of tables")
    if repro_file is not None:
        spec = ReproSpec.model_validate_json(repro_file.read_text())
        if name is not None and name != spec.id:
            raise ValueError("scenario name differs from the CLI ReproSpec id")
        selected: dict[str, Any] = {}
        name = spec.id
    else:
        if not definitions and "repro" in data:
            inline = data["repro"]
            definitions = {inline["id"]: {"repro": inline}}
        if name is None:
            if len(definitions) != 1:
                raise ValueError("select a scenario name or supply --repro and --target")
            name = next(iter(definitions))
        if name not in definitions:
            raise ValueError(f"unknown configured scenario: {name}")
        selected = definitions[name]
        raw = selected.get(
            "repro",
            {
                k: v
                for k, v in selected.items()
                if k in {"version", "id", "timeout_ms", "fingerprint", "steps"}
            },
        )
        if isinstance(raw, str):
            spec = ReproSpec.model_validate_json(contained_path(config.parent, raw).read_text())
        else:
            spec = ReproSpec.model_validate({"id": name, **raw})
        if spec.id != name:
            raise ValueError("scenario name differs from its ReproSpec id")
    invariants = data.get("invariants", {})
    if invariants.get("test"):
        raise ValueError("invariants.test is not supported; express checks as ReproSpec steps")
    extra_steps: list[dict[str, Any]] = []
    for rule in invariants.get("rule", []):
        request_id = "invariant." + rule["id"] + ".request"
        request = rule.get("request")
        if request is None:
            url = rule["target"]
            prefix = "http://127.0.0.1:{port}"
            if not url.startswith(prefix + "/"):
                raise ValueError("invariant target must use the configured loopback service")
            request = {"method": rule.get("method", "GET"), "path": url[len(prefix) :]}
            if "json" in rule:
                body = rule["json"]
                if isinstance(body, str) and body.startswith("@"):
                    body = json.loads(contained_path(config.parent, body[1:]).read_text())
                request["body"] = body
            checks = [{"status": rule["expected_status"]}]
        else:
            request = dict(request)
            if "json" in request:
                body = request.pop("json")
                if isinstance(body, str) and body.startswith("@"):
                    body = json.loads(contained_path(config.parent, body[1:]).read_text())
                request["body"] = body
            checks = rule.get("assert", [])
        if not checks:
            raise ValueError("invariant rule requires assertions")
        extra_steps.append({"action": "request", "id": request_id, **request})
        for index, check in enumerate(checks):
            extra_steps.append(
                {
                    "action": "assert",
                    "id": f"invariant.{rule['id']}.{index}",
                    "source": request_id,
                    "check": check,
                }
            )
    if extra_steps:
        spec = ReproSpec.model_validate(
            {**spec.model_dump(), "steps": [s.model_dump() for s in spec.steps] + extra_steps}
        )
    target = source_path(target_file or selected.get("target_file") or repair.target_file or "")
    if not any(PurePosixPath(target).full_match(pattern) for pattern in repair.editable):
        raise ValueError("target_file is outside repair.editable")
    if (
        target == "faultline.toml"
        or "test" in PurePosixPath(target).parts
        or any(
            part in {"tests", "__tests__"}
            or part.startswith("test_")
            or ".test." in part
            or ".spec." in part
            for part in PurePosixPath(target).parts
        )
    ):
        raise ValueError("configuration and tests cannot be repair targets")
    sandbox = data.get("sandbox", {})
    if sandbox.get("engine", "bwrap") != "bwrap":
        raise ValueError("only the bwrap sandbox is supported")
    limits = sandbox.get("limits", {})
    supported = {
        "mode": "cgroup-v2-scope",
        "memory_max_bytes": 536870912,
        "memory_swap_max_bytes": 0,
        "tasks_max": 64,
        "cpu_quota_percent": 100,
    }
    if any(supported.get(key) != value for key, value in limits.items()):
        raise ValueError("unsupported sandbox limits; required profile is 512 MiB/64 tasks/1 CPU")
    model = data.get("model", {})
    if model.get("provider", "meta") != "meta":
        raise ValueError("faultline run requires the Meta provider")
    run = ProjectRun(
        project=project,
        repair=repair,
        repro=spec,
        scenario=Scenario(
            id=name,
            title=selected.get("title", name),
            description=selected.get("description", ""),
            target_file=target,
            route="",
            error_fingerprint=spec.fingerprint or "",
            executor="repro",
            expected_assertions=[s.id for s in spec.steps if isinstance(s, AssertStep)],
        ),
        model=model.get("model", "muse-spark-1.3"),
        max_attempts=model.get("max_attempts", 2),
        budgets={key: float(value) for key, value in data.get("budgets", {}).items()},
    )
    if project.url != "http://127.0.0.1:{port}":
        raise ValueError(
            "project.url must be http://127.0.0.1:{port}; remote mutation is unsupported"
        )
    run.command(8765)
    return root, run


class ProjectPatchPolicy:
    """Exact single-file changes; syntax where available, containment for execution.

    Unlike the fixture-specific AST gate, this does not claim that arbitrary
    project source is AST-safe. The runtime, not an import allowlist, contains it.
    """

    def __init__(self, run: ProjectRun) -> None:
        self.run = run

    def validate(
        self, diff: str, source: str, *, base_sha256: str | None = None
    ) -> PatchValidationResult:
        target = self.run.scenario.target_file
        try:
            if base_sha256 != hashlib.sha256(source.encode()).hexdigest():
                raise PatchPolicyError("Proposal base hash is stale")
            limits = self.run.repair
            if (
                len(diff.encode()) > limits.max_diff_bytes
                or len(source.encode()) > limits.max_source_bytes
            ):
                raise PatchPolicyError("Configured patch/source limit exceeded")
            parsed = parse_unified_diff(diff, source, target_file=target)
            changed = sum(line[0] in "+-" for hunk in parsed.hunks for line in hunk.lines)
            if (
                changed > limits.max_changed_lines
                or len(parsed.patched_source.encode()) > limits.max_source_bytes
            ):
                raise PatchPolicyError("Configured candidate limit exceeded")
            if target.endswith(".py"):
                candidate_ast = ast.parse(parsed.patched_source, filename=target)

                def imports(tree: ast.AST) -> set[str]:
                    result: set[str] = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            result.update(alias.name for alias in node.names)
                        elif isinstance(node, ast.ImportFrom):
                            result.update(
                                "." * node.level + (node.module or "") + "." + alias.name
                                for alias in node.names
                            )
                    return result

                candidate_imports = imports(candidate_ast)
                original_imports = imports(ast.parse(source))
                allow = limits.imports.get("allow")
                deny = limits.imports.get("deny", [])
                if allow is not None and not candidate_imports - original_imports <= set(allow):
                    raise PatchPolicyError("New import is outside repair.imports.allow")
                if any(
                    name == blocked or name.startswith(blocked + ".")
                    for name in candidate_imports
                    for blocked in deny
                ):
                    raise PatchPolicyError("Candidate uses a denied import")
            return PatchValidationResult(
                is_valid=True,
                target_file=target,
                syntax_valid=target.endswith(".py"),
                ast_safe=False,
            )
        except (PatchPolicyError, SyntaxError, ValueError, RecursionError) as exc:
            return PatchValidationResult(
                is_valid=False,
                target_file=target,
                syntax_valid=False,
                ast_safe=False,
                error_message=str(exc),
            )


class ProjectSnapshots(SnapshotManager):
    """Freeze tracked working-tree bytes once, including local edits, without mutations."""

    def __init__(self, data_root: Path, repository_root: Path, run: ProjectRun) -> None:
        super().__init__(data_root, repository_root)
        self.run = run
        self.files: dict[str, bytes] = {}
        self.modes: dict[str, int] = {}

    async def manifest(self) -> Mapping[str, Any]:
        commit = (await self._git(self.repository_root, "rev-parse", "HEAD")).decode().strip()
        names = (await self._git(self.repository_root, "ls-files", "-z", "--", ".")).split(b"\0")
        files: dict[str, bytes] = {}
        total = 0
        for raw in names:
            if not raw:
                continue
            name = raw.decode()
            try:
                source_path(name)
            except ValueError:
                continue
            path = contained_path(self.repository_root, name)
            if not path.is_file():
                raise ValueError("tracked source is missing or not an ordinary file")
            size = path.stat().st_size
            total += size
            if size > 8 * 1024 * 1024 or total > 64 * 1024 * 1024:
                raise ValueError("project export exceeds 8 MiB/file or 64 MiB total")
            files[name] = path.read_bytes()
            self.modes[name] = 0o755 if path.stat().st_mode & 0o111 else 0o644
        target = self.run.scenario.target_file
        if target not in files:
            raise ValueError("repair target must be a tracked non-secret file")
        if len(files[target]) > self.run.repair.max_source_bytes:
            raise ValueError("target exceeds configured source limit")
        self.files = files
        return {
            "source_commit": commit,
            "fixture_version": "project-v1",
            "scenario_version": hashlib.sha256(
                self.run.repro.model_dump_json().encode()
            ).hexdigest(),
        }

    async def create(
        self,
        job_id: str,
        manifest: Mapping[str, Any],
        *,
        diff: str | None = None,
        base_sha256: str | None = None,
    ) -> Snapshot:
        files = dict(self.files)
        target = self.run.scenario.target_file
        source = files[target].decode("utf-8")
        if diff is not None:
            result = ProjectPatchPolicy(self.run).validate(diff, source, base_sha256=base_sha256)
            if not result.is_valid:
                raise PatchPolicyError(result.error_message)
            files[target] = parse_unified_diff(
                diff, source, target_file=target
            ).patched_source.encode()
        generation = str(uuid4())
        exported = self._job_root(job_id) / "snapshots" / generation
        exported.mkdir(parents=True)
        for name, content in files.items():
            path = contained_path(exported, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(self.modes[name])
        content = files[target]
        return Snapshot(
            exported,
            exported,
            generation,
            tree_digest(exported),
            content.decode(),
            hashlib.sha256(content).hexdigest(),
            manifest["source_commit"],
        )

    async def cleanup(self, job_id: str) -> None:
        owned = self._job_root(job_id)
        if owned.exists():
            shutil.rmtree(owned)


def tree_digest(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("snapshot symlinks are forbidden")
        if path.is_file():
            entries.append(
                (
                    path.relative_to(root).as_posix(),
                    path.stat().st_mode & 0o777,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
