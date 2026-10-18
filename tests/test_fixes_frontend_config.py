"""QA tests for T-006 fix R8 (static part): Node 22 pinned in package.json, .nvmrc and CI.

The frontend commands themselves (npm ci, lint, typecheck, test, build) are run outside pytest,
since they need Node. This file only checks the committed configuration. YAML is read as text
because PyYAML is not an approved dependency.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _frontend_job() -> list[str]:
    lines = CI.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.fullmatch(r"  frontend:\s*", line))
    block = []
    for line in lines[start + 1 :]:
        if re.match(r"  [A-Za-z0-9_-]+:\s*$", line):  # next job at the same indent
            break
        block.append(line)
    return block


def test_r8_engines_node_is_at_least_22_12() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert package["engines"]["node"] == ">=22.12"


def test_r8_nvmrc_pins_node_22() -> None:
    assert (FRONTEND / ".nvmrc").read_text(encoding="utf-8").strip() == "22"


def test_r8_frontend_job_uses_node_22() -> None:
    text = "\n".join(_frontend_job())
    versions = re.findall(r"node-version:\s*[\"']?([^\"'\s#]+)", text)
    assert versions == ["22"]


def test_r8_frontend_job_has_no_detect_step_or_step_conditions() -> None:
    block = _frontend_job()
    text = "\n".join(block)
    assert "detect" not in text.lower()
    assert "steps." not in text
    assert not [line for line in block if re.match(r"\s*(-\s+)?if:", line)]


def test_r8_frontend_job_still_runs_every_command() -> None:
    text = "\n".join(_frontend_job())
    for command in (
        "npm ci",
        "npm run lint",
        "npm run typecheck",
        "npm run test",
        "npm run build",
    ):
        assert command in text


def test_r8_no_job_in_ci_is_gated_on_a_detect_step() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "steps.detect" not in text
    assert 'node-version: "20"' not in text
