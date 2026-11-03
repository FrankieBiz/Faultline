"""Contrarian audit of environment-variable containment in subprocess dispatch.

This file assumes the host environment is hostile. It feeds the exact
environment-construction seams the orchestrator uses — the project dev-command
launcher, the browser-runner dispatch allowlist, and the isolated runtime's
trusted environment — with API keys, tokens, code-injection vectors, and
Linux/macOS/Windows path conventions, then asserts that nothing but an explicit
allowlist can cross into a spawned process.

No sandbox, browser, or service is launched here; every assertion is over the
pure scrubbing functions so the contract is proven on every host, not just the
CI's Linux image.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import crawler_service
from app.crawler_service import runner_environment
from app.isolated_runtime import IsolatedRuntime
from app.project_launcher import (
    _PROJECT_ENVIRONMENT_ALLOWLIST,
    _PROJECT_ENVIRONMENT_FIXED,
    build_environment,
)

# --- hostile corpus -----------------------------------------------------------

# Every credential and code-loading vector a host might carry. Any one of these
# crossing into project or runner code is a credential or injection leak.
SECRET_NAMES: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "META_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITLAB_TOKEN",
    "NPM_TOKEN",
    "FAULTLINE_CONTROL_TOKEN",
    "FAULTLINE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "DOCKER_PASSWORD",
    "DATABASE_URL",
    # Code-loading / shell / interpreter injection vectors.
    "NODE_OPTIONS",
    "NODE_PATH",
    "PYTHONSTARTUP",
    "PYTHONPATH",
    "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES",
    "BASH_ENV",
    "ENV",
)

SECRET_SENTINEL = "fake-secret-sentinel"

WINDOWS_PATH_ENVIRONMENT = {
    "SYSTEMROOT": "C:\\Windows",
    "WINDIR": "C:\\Windows",
    "USERPROFILE": "C:\\Users\\tester",
    "LOCALAPPDATA": "C:\\Users\\tester\\AppData\\Local",
    "TEMP": "C:\\Users\\tester\\AppData\\Local\\Temp",
    "TMP": "C:\\Users\\tester\\AppData\\Local\\Temp",
}


def hostile_environment() -> dict[str, str]:
    """A full host environment spanning Linux, macOS, and Windows conventions."""
    environment: dict[str, str] = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/home/tester",
        "LANG": "en_US.UTF-8",
        "TZ": "UTC",
        # The isolation profile's own flags, present in a realistic sandbox.
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        "PLAYWRIGHT_BROWSERS_PATH": "/home/tester/.cache/ms-playwright",
    }
    for name in SECRET_NAMES:
        environment[name] = SECRET_SENTINEL
    environment.update(WINDOWS_PATH_ENVIRONMENT)
    return environment


def _set_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SECRET_NAMES:
        monkeypatch.setenv(name, SECRET_SENTINEL)


# --- project dev-command launcher --------------------------------------------


def test_build_environment_strips_every_secret_and_keeps_only_allowlist() -> None:
    environment = build_environment(hostile_environment())
    expected_keys = _PROJECT_ENVIRONMENT_ALLOWLIST | set(_PROJECT_ENVIRONMENT_FIXED)
    assert set(environment) == expected_keys
    # No secret value survives under any key, allowlisted or otherwise.
    assert SECRET_SENTINEL not in environment.values()
    for name in SECRET_NAMES:
        if name in _PROJECT_ENVIRONMENT_FIXED:
            # A name the fixed set owns (e.g. PYTHONPATH) is replaced, never
            # inherited, with the trusted value.
            assert environment[name] == _PROJECT_ENVIRONMENT_FIXED[name]
        else:
            assert name not in environment
    # Fixed offline/telemetry-disabled values are present and unchanged.
    assert environment["UV_OFFLINE"] == "1"
    assert environment["UV_NO_SYNC"] == "1"
    assert environment["NEXT_TELEMETRY_DISABLED"] == "1"


def test_build_environment_replaces_hostile_pythonpath_with_trusted_packages() -> None:
    environment = build_environment({"PATH": "/usr/bin", "PYTHONPATH": ".;/attacker"})
    # PYTHONPATH is never inherited: only the fixed "/packages" value crosses.
    assert environment["PYTHONPATH"] == "/packages"
    assert ".;/attacker" not in environment.values()


@pytest.mark.parametrize(
    "name",
    ["openai_api_key", "OpenAI_Api_Key", "meta_api_key", "Path", "path", "PATH "],
)
def test_build_environment_drops_case_and_whitespace_secret_variants(name: str) -> None:
    environment = build_environment({name: SECRET_SENTINEL, "PATH": "/usr/bin"})
    assert name not in environment
    assert SECRET_SENTINEL not in environment.values()


def test_build_environment_does_not_inherit_linux_or_macos_home_secrets() -> None:
    for home in ("/home/tester", "/Users/tester"):
        environment = build_environment({"HOME": home, "PATH": "/usr/bin"})
        assert environment["HOME"] == home  # HOME is allowlisted, the value passes.


def test_build_environment_result_is_a_fresh_dict() -> None:
    source = {"PATH": "/usr/bin", "HOME": "/tmp"}
    result = build_environment(source)
    result["PATH"] = "/attacker"
    result["INJECTED"] = "x"
    assert source["PATH"] == "/usr/bin"
    assert "INJECTED" not in _PROJECT_ENVIRONMENT_FIXED
    assert build_environment(source)["PATH"] == "/usr/bin"


def test_build_environment_ignores_windows_only_spellings() -> None:
    """Windows discovery variables are not part of the dev-command allowlist."""
    environment = build_environment(hostile_environment())
    for name in ("SYSTEMROOT", "WINDIR", "USERPROFILE", "LOCALAPPDATA", "TEMP", "TMP"):
        assert name not in environment


# --- browser-runner dispatch allowlist ----------------------------------------


def test_runner_environment_strips_secrets_and_keeps_windows_discovery() -> None:
    environment = runner_environment(hostile_environment())
    assert set(environment) <= set(crawler_service.RUNNER_ENVIRONMENT)
    assert SECRET_SENTINEL not in environment.values()
    for name in SECRET_NAMES:
        assert name not in environment
    # The Windows process/cache variables the runner needs do cross over.
    assert environment["SYSTEMROOT"] == "C:\\Windows"
    assert environment["USERPROFILE"] == "C:\\Users\\tester"
    assert environment["LOCALAPPDATA"] == "C:\\Users\\tester\\AppData\\Local"


def test_runner_environment_allowlist_names_no_credentials() -> None:
    """The allowlist itself must never name a credential or injection vector."""
    for name in crawler_service.RUNNER_ENVIRONMENT:
        assert not re.search(r"(TOKEN|_KEY|SECRET|PASSWORD|CREDENTIAL)", name.upper()), name
    for banned in ("NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "AWS_SECRET_ACCESS_KEY"):
        assert banned not in crawler_service.RUNNER_ENVIRONMENT


def test_runner_environment_omits_missing_variables() -> None:
    environment = runner_environment({"PATH": "/usr/bin"})
    assert set(environment) == {"PATH"}


def test_runner_environment_is_a_fresh_dict() -> None:
    source = {"PATH": "/usr/bin", "HOME": "/home/tester"}
    result = runner_environment(source)
    result["PATH"] = "/attacker"
    assert source["PATH"] == "/usr/bin"
    assert "PATH" in runner_environment(source)


# --- isolated runtime trusted environment -------------------------------------


def test_trusted_environment_excludes_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_secrets(monkeypatch)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/tmp/browsers")
    runtime = IsolatedRuntime(tmp_path)
    trusted = runtime._trusted_environment()
    assert set(trusted) == {
        "PATH",
        "NODE_ENV",
        "NEXT_TELEMETRY_DISABLED",
        "PLAYWRIGHT_BROWSERS_PATH",
    }
    for name in SECRET_NAMES:
        assert name not in trusted
    assert SECRET_SENTINEL not in trusted.values()


def test_scope_environment_returns_only_manager_addresses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_secrets(monkeypatch)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    runtime = IsolatedRuntime(tmp_path)
    scoped = runtime.scope_environment("faultline-test.scope")
    assert set(scoped) == {"XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}
    for name in SECRET_NAMES:
        assert name not in scoped
    assert SECRET_SENTINEL not in scoped.values()
    # An unscoped launch gets an empty environment, never the host's.
    assert runtime.scope_environment(None) == {}


def test_manager_environment_never_includes_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_secrets(monkeypatch)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    runtime = IsolatedRuntime(tmp_path)
    # manager_environment is the single source for scope_environment; even with
    # a secret in the real environment it stays a two-key allowlist.
    assert set(runtime.manager_environment) <= {"XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}
    for name in SECRET_NAMES:
        assert name not in runtime.manager_environment
