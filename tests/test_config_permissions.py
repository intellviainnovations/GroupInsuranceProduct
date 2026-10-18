"""POSIX permission checks on the protected config file (T-006 N2). Skipped on Windows."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.platform.config import ConfigError, load_settings

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")

CONTENT = 'log_level = "WARNING"\n'


def _load(path: Path) -> object:
    return load_settings({"ENV": "dev", "APP_CONFIG_FILE": str(path)})


def _config(tmp_path: Path, mode: int) -> Path:
    path = tmp_path / "app.toml"
    path.write_text(CONTENT, encoding="utf-8")
    path.chmod(mode)
    return path


def test_owner_only_file_is_accepted(tmp_path: Path) -> None:
    assert _load(_config(tmp_path, 0o600)) is not None


def test_group_readable_file_is_accepted(tmp_path: Path) -> None:
    assert _load(_config(tmp_path, 0o640)) is not None


@pytest.mark.parametrize("mode", [0o620, 0o660, 0o664, 0o640 | 0o004, 0o602])
def test_group_writable_or_other_accessible_file_is_rejected(tmp_path: Path, mode: int) -> None:
    with pytest.raises(ConfigError) as info:
        _load(_config(tmp_path, mode))
    assert "APP_CONFIG_FILE" in str(info.value)
    assert CONTENT.strip() not in str(info.value)
