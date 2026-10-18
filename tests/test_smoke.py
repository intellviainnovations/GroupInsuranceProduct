"""Smoke placeholder and import-boundary check. QA replaces/extends with spec-derived tests."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.platform.config import Settings

SRC = Path(__file__).resolve().parent.parent / "src"
BACKEND = SRC / "backend"

# package -> backend packages it must NOT import (dependency rule, docs/design/architecture.md).
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "domain": ("api", "services", "adapters", "persistence", "platform"),
    "platform": ("api", "services", "adapters", "persistence", "domain"),
    "persistence": ("api", "services", "adapters"),
    "adapters": ("api", "services"),
    "services": ("api",),
}


def test_health_smoke() -> None:
    app = create_app(Settings(env="dev", throttle_enabled=False))
    response = TestClient(app).get("/health")
    assert response.status_code == 200


def _imported_backend_packages(path: Path) -> set[str]:
    """Top-level backend sub-packages a file imports, including ``from backend import x``."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # Relative imports can hide a boundary crossing; they are not allowed at all.
                found.add(f"<relative import level {node.level}>")
                continue
            if node.module == "backend":
                names = [f"backend.{alias.name}" for alias in node.names]
            elif node.module:
                names = [node.module]
            else:
                continue
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "backend" and len(parts) > 1:
                found.add(parts[1])
    return found


def test_import_boundaries() -> None:
    violations = []
    for package, forbidden in FORBIDDEN.items():
        for path in (BACKEND / package).rglob("*.py"):
            imported = _imported_backend_packages(path)
            bad = imported & set(forbidden)
            bad |= {name for name in imported if name.startswith("<relative")}
            if package == "adapters":
                bad.discard("platform")
            if bad:
                violations.append(f"{path.relative_to(SRC)} imports {sorted(bad)}")
    assert not violations, violations


def test_importing_domain_loads_no_other_backend_package() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(SRC)!r}); import backend.domain; "
        "extra = sorted(m for m in sys.modules "
        "if m.startswith('backend') and m not in ('backend', 'backend.domain')); "
        "print(extra); sys.exit(1 if extra else 0)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_detector_catches_from_backend_import_and_relative_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from backend import services\nfrom backend.api import app\nfrom . import sibling\n"
        "from ..api import other\nimport backend.persistence.x\n",
        encoding="utf-8",
    )
    found = _imported_backend_packages(sample)
    assert {"services", "api", "persistence"} <= found
    assert any(name.startswith("<relative") for name in found)
