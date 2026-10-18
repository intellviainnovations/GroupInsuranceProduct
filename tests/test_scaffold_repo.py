"""QA tests for T-001 criteria A9 (import boundary), A10 (repo hygiene and CI) and the
documented production run command (no server header)."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from scaffold_support import SYNTHETIC_DB_URL

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


# ---------------------------------------------------------------- A9 import boundary


def loaded_backend_modules(import_statement: str) -> set[str]:
    """Run the import in a fresh interpreter and report which backend.* modules got loaded."""
    code = (
        "import sys, json; sys.path.insert(0, sys.argv[1]); "
        f"{import_statement}; "
        "print(json.dumps(sorted(m for m in sys.modules "
        "if m == 'backend' or m.startswith('backend.'))))"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, "-I", "-c", code, str(SRC)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    modules: list[str] = json.loads(result.stdout.strip().splitlines()[-1])
    return set(modules)


def test_a9_importing_domain_loads_no_other_backend_package() -> None:
    modules = loaded_backend_modules("import backend.domain")
    assert "backend.domain" in modules
    foreign = {m for m in modules if m != "backend" and not m.startswith("backend.domain")}
    assert not foreign, f"backend.domain pulled in: {sorted(foreign)}"


def test_a9_domain_submodules_stay_inside_domain() -> None:
    import pkgutil

    domain_dir = SRC / "backend" / "domain"
    names = [m.name for m in pkgutil.iter_modules([str(domain_dir)])]
    for name in names:
        modules = loaded_backend_modules(f"import backend.domain.{name}")
        foreign = {m for m in modules if m != "backend" and not m.startswith("backend.domain")}
        assert not foreign, f"backend.domain.{name} pulled in: {sorted(foreign)}"


def test_a9_boundary_check_detects_cross_package_imports() -> None:
    """Control: the detector reports packages when they really are imported."""
    modules = loaded_backend_modules("import backend.api.app")
    assert "backend.platform.config" in modules
    assert "backend.api.app" in modules


# ---------------------------------------------------------------- A10 repo hygiene and CI


def find_bash() -> str | None:
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        shutil.which("bash"),
    ]
    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        if "system32" in candidate.lower():  # WSL launcher, cannot see Windows paths
            continue
        return candidate
    return None


def test_a10_check_repo_script_passes() -> None:
    bash = find_bash()
    if bash is None:
        pytest.skip("no usable bash on this machine")
    if shutil.which("git") is None:
        pytest.skip("git not available")
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [bash, "scripts/check_repo.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "check_repo: OK" in result.stdout


CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
EXPECTED_JOBS = {"hygiene", "backend", "backend-audit", "frontend"}


def test_a10_ci_yaml_parses_with_expected_jobs() -> None:
    yaml = pytest.importorskip("yaml", reason="PyYAML is not installed and may not be added")
    document = yaml.safe_load(CI_PATH.read_text(encoding="utf-8"))
    assert set(document["jobs"]) >= EXPECTED_JOBS


def test_a10_ci_text_lists_expected_jobs_without_a_yaml_parser() -> None:
    """Fallback for machines without PyYAML: indentation-based scan of the jobs block only."""
    lines = CI_PATH.read_text(encoding="utf-8").splitlines()
    assert "jobs:" in lines
    block = lines[lines.index("jobs:") + 1 :]
    names = {m.group(1) for ln in block if (m := re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", ln))}
    assert names >= EXPECTED_JOBS
    assert "\t" not in CI_PATH.read_text(encoding="utf-8"), "tabs are invalid in YAML"


# ---------------------------------------------------------------- documented run command


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_documented_production_command_serves_without_server_header() -> None:
    port = free_port()
    env = {k: v for k, v in os.environ.items() if k != "ENV" and not k.startswith("APP_")}
    env.update({"ENV": "prod", "APP_DATABASE_URL": SYNTHETIC_DB_URL})
    proc = subprocess.Popen(  # noqa: S603 - fixed interpreter and arguments
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "backend.api.app:create_app",
            "--no-server-header",
            "--app-dir",
            str(SRC),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        response = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
                break
            except httpx.TransportError:
                time.sleep(0.3)
        assert response is not None, "server did not start"
        assert response.status_code == 200
        assert "server" not in response.headers
        assert "x-powered-by" not in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"
        assert httpx.get(f"http://127.0.0.1:{port}/docs", timeout=2).status_code == 404
        assert httpx.get(f"http://127.0.0.1:{port}/openapi.json", timeout=2).status_code == 404
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
