"""Builder's checks: ENV=demo safety rules and the generated OpenAPI against the YAML contract."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from backend.api.app import create_app
from backend.platform.config import ConfigError, load_settings
from scaffold_support import logging_guard

ROOT = Path(__file__).resolve().parent.parent
YAML = ROOT / "docs" / "contracts" / "staff-api.openapi.yaml"
SNAPSHOT = ROOT / "docs" / "contracts" / "staff-api.openapi.snapshot.json"


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    yield from logging_guard()


@pytest.mark.parametrize(
    "extra",
    [
        {"APP_DATA_BACKEND": "memory"},
        {"APP_INSURER_ADAPTER": "fake"},
        {"APP_BANK_AUTH": "fake"},
        {"APP_CBS": "fake"},
    ],
)
def test_synthetic_parts_are_refused_outside_dev_and_demo(extra: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_settings({"ENV": "prod", "APP_DATABASE_URL": "postgresql://h.invalid/x", **extra})


def test_demo_defaults_to_memory_and_fakes() -> None:
    settings = load_settings({"ENV": "demo"})
    assert settings.production is True
    assert settings.resolved_data_backend == "memory"
    assert settings.synthetic_data is True


def test_secure_cookie_can_be_dropped_only_in_dev() -> None:
    assert load_settings({"ENV": "dev", "APP_SESSION_COOKIE_SECURE": "false"})
    with pytest.raises(ConfigError):
        load_settings({"ENV": "demo", "APP_SESSION_COOKIE_SECURE": "false"})


def test_short_session_secret_is_refused() -> None:
    with pytest.raises(ConfigError):
        load_settings({"ENV": "demo", "APP_SESSION_SECRET": "too-short"})  # secret-scan:allow


def test_usgic_without_base_url_is_refused() -> None:
    with pytest.raises(ConfigError):
        load_settings({"ENV": "demo", "APP_INSURER_ADAPTER": "usgic"})


def _openapi() -> dict[str, Any]:
    app = create_app(load_settings({"ENV": "demo", "APP_JOB_WORKER_ENABLED": "false"}))
    spec: dict[str, Any] = app.openapi()
    return spec


def _yaml_operations() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    path = None
    for line in YAML.read_text(encoding="utf-8").splitlines():
        if line.startswith("components:"):
            break
        match = re.fullmatch(r"  (/\S+):", line)
        if match:
            path = match.group(1)
        method = re.fullmatch(r"    (get|post|patch|put|delete):", line)
        if method and path:
            found.add((method.group(1), "/api/v1" + path))
    return found


def test_every_contract_operation_exists_with_its_operation_id() -> None:
    spec = _openapi()
    generated = {(m, p) for p, ops in spec["paths"].items() for m in ops if p.startswith("/api/")}
    assert generated == _yaml_operations()
    yaml_ids = set(re.findall(r"operationId: (\w+)", YAML.read_text(encoding="utf-8")))
    ids = {
        op["operationId"]
        for p, ops in spec["paths"].items()
        for op in ops.values()
        if p.startswith("/api/")
    }
    assert ids == yaml_ids


def test_contract_schema_names_exist() -> None:
    spec = _openapi()
    block = YAML.read_text(encoding="utf-8").split("\n  schemas:\n", 1)[1]
    names = set(re.findall(r"^    ([A-Za-z]+):", block, flags=re.MULTILINE))
    primitives = {
        "Uuid",
        "Money",
        "Percent",
        "RefCodeValue",
        "BranchCode",
        "RollNo",
        "PersonName",
        "FullName",
        "Mobile",
        "Email",
        "Pincode",
        "Ifsc",
        "AccountKey",
        "Masked",
        "EnrolmentStatus",
        "Role",
        "AllowedAction",
        "AttentionReason",
        "RefCodeList",
        "ApprovalAction",
    }
    missing = names - primitives - set(spec["components"]["schemas"])
    assert not missing


def test_snapshot_matches_the_running_app() -> None:
    spec = _openapi()
    assert json.loads(SNAPSHOT.read_text(encoding="utf-8")) == json.loads(json.dumps(spec))
