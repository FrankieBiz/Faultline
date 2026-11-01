"""The Pre-Flight Agent Gate's snippets match in the Inspector, on the judge page, and on disk."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "faultline-gate" / "SKILL.md"
INSPECTOR = ROOT / "web" / "inspector-ui" / "src" / "lib" / "agent-gate.ts"
JUDGE = ROOT / "docs" / "index.html"
URL = "http://localhost:3000"


def _templates(source: str) -> list[str]:
    """Every JS template literal in `source`, with `${url}` filled in and escapes decoded."""
    bodies = re.findall(r"`((?:[^`\\]|\\.)*)`", source, flags=re.S)
    return [re.sub(r"\\(.)", r"\1", body.replace("${url}", URL), flags=re.S) for body in bodies]


def test_skill_file_is_the_agent_skill_tab_in_both_surfaces() -> None:
    skill = SKILL.read_text(encoding="utf-8").strip()
    assert skill in _templates(INSPECTOR.read_text(encoding="utf-8"))
    assert skill in _templates(JUDGE.read_text(encoding="utf-8"))


def test_every_inspector_snippet_appears_on_the_judge_page() -> None:
    judge = _templates(JUDGE.read_text(encoding="utf-8"))
    starts = ("## Pre-flight gate", "name: FaultLine pre-flight gate", "./faultline gate")
    inspector = [
        body
        for body in _templates(INSPECTOR.read_text(encoding="utf-8"))
        if body.startswith(starts)
    ]
    assert len(inspector) == 3
    for body in inspector:
        assert body in judge


def test_snippets_only_use_the_gate_command_the_cli_defines() -> None:
    cli = (ROOT / "services" / "repair-orchestrator" / "app" / "cli.py").read_text(encoding="utf-8")
    assert 'subparsers.add_parser(\n        "gate",' in cli
    for source in (INSPECTOR, JUDGE):
        commands = set(re.findall(r"faultline (\w+) ", source.read_text(encoding="utf-8")))
        assert "gate" in commands
