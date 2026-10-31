"""Conservative project discovery and schema-compatible starter configuration."""

import ast
import json
import re
import shlex
import tomllib
from pathlib import Path
from typing import Any


def _python_entry(root: Path) -> tuple[str, str, str] | None:
    # Inspect ordinary source only; never environment files or arbitrary config.
    for base in (root, root / "app", root / "src", root / "src/app"):
        for name in ("main.py", "app.py", "asgi.py"):
            path = base / name
            if not path.is_file() or path.is_symlink():
                continue
            tree = ast.parse(path.read_text())
            factories: dict[str, str] = {}
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module in {
                    "fastapi",
                    "starlette.applications",
                    "flask",
                }:
                    for alias in node.names:
                        if alias.name in {"FastAPI", "Starlette", "Flask"}:
                            factories[alias.asname or alias.name] = alias.name.lower()
            for node in tree.body:
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                    continue
                call = node.value.func
                if isinstance(call, ast.Name) and call.id in factories:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            relative = path.relative_to(root).as_posix()
                            module = relative.removesuffix(".py").replace("/", ".")
                            return factories[call.id], f"{module}:{target.id}", relative
    return None


def detect_project_stack(target_dir: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": target_dir.name or "my-service",
        "stack": "custom",
        "setup_command": "",
        "lockfiles": [],
        "dev_command": "",
        "health": "/",
        "test_command": "",
        "editable": [],
        "notes": [],
    }
    package = target_dir / "package.json"
    if package.is_file():
        data = json.loads(package.read_text())
        if not isinstance(data, dict):
            raise ValueError("package.json must be an object")
        deps: dict[str, Any] = {}
        for key in ("dependencies", "devDependencies"):
            value = data.get(key, {})
            if not isinstance(value, dict):
                raise ValueError(f"package.json {key} must be an object")
            deps.update(value)
        scripts = data.get("scripts", {})
        if not isinstance(scripts, dict) or any(not isinstance(v, str) for v in scripts.values()):
            raise ValueError("package.json scripts must contain strings")
        locks = {
            "pnpm": "pnpm-lock.yaml",
            "yarn": "yarn.lock",
            "bun": "bun.lock",
            "npm": "package-lock.json",
        }
        present = [manager for manager, lock in locks.items() if (target_dir / lock).is_file()]
        if (target_dir / "bun.lockb").is_file() and "bun" not in present:
            present.append("bun")
            locks["bun"] = "bun.lockb"
        declared = data.get("packageManager", "")
        if not isinstance(declared, str):
            raise ValueError("packageManager must be a string")
        manager = declared.split("@", 1)[0] if declared else (present[0] if present else "npm")
        if manager not in locks:
            raise ValueError("unsupported packageManager")
        if not declared and len(present) > 1:
            raise ValueError("multiple package locks; declare packageManager explicitly")
        locked = manager in present
        classic_yarn = declared.startswith("yarn@1.") or (
            not declared
            and manager == "yarn"
            and "# yarn lockfile v1" in (target_dir / "yarn.lock").read_text()[:1024]
        )
        info["lockfiles"] = [locks[manager]] if locked else []
        info["setup_command"] = {
            "npm": "npm ci" if locked else "npm install",
            "pnpm": "pnpm install --frozen-lockfile" if locked else "pnpm install",
            "yarn": (
                "yarn install --frozen-lockfile" if classic_yarn else "yarn install --immutable"
            )
            if locked
            else "yarn install",
            "bun": "bun install --frozen-lockfile" if locked else "bun install",
        }[manager]
        if manager != "npm":
            info["notes"].append(
                f"{manager} is detected for local setup; the sandbox mounts Node/npm and uv "
                f"only. Adapt dev_command to an installed Node entrypoint before repair."
            )
        script = next((name for name in ("dev", "start") if scripts.get(name)), None)
        command = f"{manager} run {script}" if script else ""
        info["language"] = (
            "typescript"
            if any(target_dir.glob("tsconfig*.json")) or "typescript" in deps
            else "javascript"
        )
        extensions: tuple[str, ...] = ("ts", "tsx", "js", "jsx", "mjs", "cjs")
        if "next" in deps:
            info["stack"] = "node-next"
            roots = [
                p for p in ("app", "pages", "src/app", "src/pages") if (target_dir / p).is_dir()
            ]
            info["router"] = "app" if any(p.endswith("app") for p in roots) else "pages"
            info["editable"] = [f"{p}/**/*.{ext}" for p in roots for ext in extensions]
            if script and "next" in scripts[script]:
                command += (
                    " -- -H 127.0.0.1 -p {port}" if manager == "npm" else " -H 127.0.0.1 -p {port}"
                )
        elif "vite" in deps:
            framework = next((f for f in ("react", "vue", "svelte") if f in deps), "generic")
            info["stack"] = f"node-vite-{framework}"
            extensions += ("vue", "svelte")
            if script and "vite" in scripts[script]:
                command += (
                    " -- --host 127.0.0.1 --port {port} --strictPort"
                    if manager == "npm"
                    else " --host 127.0.0.1 --port {port} --strictPort"
                )
        else:
            info["stack"] = "node-express" if "express" in deps else "node-generic"
        if not command:
            entry = data.get("main", "")
            if isinstance(entry, str) and entry and (target_dir / entry).is_file():
                command = "node " + shlex.quote(entry)
        if not info["editable"]:
            info["editable"] = [f"**/*.{ext}" for ext in extensions]
        info["dev_command"] = f"env PORT={{port}} {command}" if command else ""
        if "test" in scripts and "no test specified" not in scripts["test"]:
            info["test_command"] = f"{manager} run test"
    else:
        pyproject = target_dir / "pyproject.toml"
        requirements = target_dir / "requirements.txt"
        metadata = tomllib.loads(pyproject.read_text()) if pyproject.is_file() else {}
        if (target_dir / "uv.lock").is_file():
            info["lockfiles"] = ["uv.lock"]
            info["setup_command"] = "uv sync --locked"
        elif pyproject.is_file():
            info["setup_command"] = "uv sync"
        elif requirements.is_file():
            info["setup_command"] = "uv venv && uv pip install -r requirements.txt"
        prefix = (
            "uv run"
            if pyproject.is_file()
            else (".venv/bin/python" if requirements.is_file() else "python3.13")
        )
        project = metadata.get("project", {})
        if not isinstance(project, dict):
            raise ValueError("pyproject project must be a table")
        dependencies = project.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(isinstance(d, str) for d in dependencies):
            raise ValueError("project.dependencies must be an array of strings")
        declared = list(dependencies)
        if requirements.is_file():
            declared.extend(requirements.read_text().splitlines())
        names = {re.split(r"[\s\[<>=!~;@]", d.strip().lower(), maxsplit=1)[0] for d in declared}
        python_framework = next(
            (f for f in ("fastapi", "starlette", "django", "flask") if f in names), None
        )
        entry = _python_entry(target_dir)
        if (target_dir / "manage.py").is_file():
            info.update(
                stack="python-django",
                dev_command=f"{prefix} manage.py runserver 127.0.0.1:{{port}} --noreload",
                test_command=f"{prefix} manage.py test",
            )
        elif entry:
            framework, module, source = entry
            info["stack"] = f"python-{framework}"
            if framework == "flask":
                info["dev_command"] = (
                    f"{prefix} -m flask --app {module} run --host 127.0.0.1 --port {{port}} "
                    f"--no-reload"
                )
            else:
                info["dev_command"] = (
                    f"{prefix} -m uvicorn {module} --host 127.0.0.1 --port {{port}}"
                )
            info["notes"].append(
                f"Detected application in {source}; ensure its server dependency is installed."
            )
        elif python_framework:
            info["stack"] = f"python-{python_framework}"
            # A dependency identifies a framework, not an application object. The
            # conventional entrypoint is explicitly marked for operator review.
            if python_framework in {"fastapi", "starlette"}:
                info["dev_command"] = (
                    f"{prefix} -m uvicorn main:app --host 127.0.0.1 --port {{port}}"
                )
            elif python_framework == "flask":
                info["dev_command"] = (
                    f"{prefix} -m flask --app app:app run --host 127.0.0.1 --port {{port}} "
                    f"--no-reload"
                )
            info["notes"].append(
                "Framework detected from dependencies only: customize the conventional "
                "application entrypoint in dev_command before running; "
                "it was not resolved from source."
            )
        elif pyproject.is_file() or requirements.is_file():
            info["stack"] = "python-generic"
        info["editable"] = ["**/*.py"]
        # Do not invent a pytest dependency or silently serve a source directory.
        if "pytest" in str(metadata) or (
            requirements.is_file() and "pytest" in requirements.read_text()
        ):
            info["test_command"] = f"{prefix} -m pytest"
    if info.get("language"):
        info["notes"].append("Detected language: " + info["language"] + ".")
    info["notes"].append(
        "Review the / HTTP 200 invariant against a real application route. Add a scenario "
        "target_file and reproduction before repair; no source target is guessed."
    )
    return info


def generate_faultline_toml(info: dict[str, Any]) -> str:
    if not info["dev_command"]:
        raise ValueError(
            "No runnable service entrypoint detected; configure project.dev_command manually "
            "(see docs/PROJECT_RUNNER.md)"
        )

    # JSON basic strings are TOML-compatible for these values, including control escapes.
    def quote(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    project = {
        key: info[key]
        for key in (
            "name",
            "stack",
            "setup_command",
            "lockfiles",
            "dev_command",
            "health",
            "test_command",
        )
    }
    project.update(root=".", url="http://127.0.0.1:{port}")
    lines = ["# FaultLine configuration v1", "schema = 1", "", "[project]"]
    lines.extend(f"{key} = {quote(value)}" for key, value in project.items())
    lines += [
        "",
        "[repair]",
        f"editable = {quote(info['editable'])}",
        "max_files = 1",
        "",
        "[sandbox]",
        'engine = "bwrap"',
        "",
        "[model]",
        'provider = "meta"',
        'model = "muse-spark-1.3"',
        "max_attempts = 2",
        "",
        "[[invariants.rule]]",
        'id = "service_health"',
        'name = "Service responds on the configured route"',
        "expected_status = 200",
        f"target = {quote('http://127.0.0.1:{port}' + info['health'])}",
    ]
    lines += [
        "",
        *["# " + note.replace("\n", " ").replace("\r", " ") for note in info["notes"]],
        "",
    ]
    return "\n".join(lines)
