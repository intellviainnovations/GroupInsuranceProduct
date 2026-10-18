"""QA tests for T-006 fix R5: permission check on the protected config file.

POSIX behaviour is simulated on any host by replacing ``os`` (only its ``name``) and ``Path.stat``
inside ``backend.platform.config`` (see ``_simulate``). The simulated tests therefore run on
Windows too, but they only prove the decision logic: they do NOT prove that a real chmod'ed file
on a real POSIX filesystem is rejected. The real-chmod tests at the bottom are skipped on
Windows and never ran on the Windows development host.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import backend.platform.config as config_module
from backend.platform.config import ConfigError, Settings, load_settings

DB_CRED = "DISTINCTIVE-dbpw-4417"  # synthetic
CONTENT = (
    'log_level = "ERROR"\n'
    + "database_url = "
    + f'"postgresql://user:{DB_CRED}@db.invalid/app"\n'  # secret-scan:allow
)

ACCEPTED_MODES = [0o600, 0o640, 0o400]
REJECTED_MODES = {
    "group-writable 0620": 0o620,
    "group-writable 0660": 0o660,
    "group-writable 0664": 0o664,
    "group-writable and read-only others 0624": 0o624,
    "other-readable 0604": 0o604,
    "other-readable 0644": 0o644,
    "other-readable 0614": 0o614,
    "other-writable 0602": 0o602,
    "other-writable 0606": 0o606,
    "world-accessible 0666": 0o666,
    "world-accessible 0777": 0o777,
    "other-executable 0601": 0o601,
}


class _OsShim:
    """Stands in for the ``os`` module inside the config module; only ``name`` differs."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, attr: str) -> Any:
        return getattr(os, attr)


def _simulate(monkeypatch: pytest.MonkeyPatch, *, os_name: str, mode: int) -> None:
    base = type(Path())

    class FakeStatPath(base):  # type: ignore[valid-type, misc]
        def stat(self, **kwargs: Any) -> Any:
            super().stat(**kwargs)  # still fails like the real thing if the file is missing
            return SimpleNamespace(st_mode=stat.S_IFREG | mode)

    monkeypatch.setattr(config_module, "os", _OsShim(os_name))
    monkeypatch.setattr(config_module, "Path", FakeStatPath)


def _write(tmp_path: Path, content: str = CONTENT) -> Path:
    path = tmp_path / "app.toml"
    path.write_text(content, encoding="utf-8")
    return path


def _load(path: Path) -> Settings:
    return load_settings({"ENV": "dev", "APP_CONFIG_FILE": str(path)})


# ---- simulated POSIX ------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ACCEPTED_MODES, ids=[oct(m) for m in ACCEPTED_MODES])
def test_r5_simulated_posix_owner_only_and_group_readable_files_are_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    path = _write(tmp_path)
    _simulate(monkeypatch, os_name="posix", mode=mode)
    settings = _load(path)
    assert settings.log_level == "ERROR", "the accepted file must really have been read"


@pytest.mark.parametrize("mode", REJECTED_MODES.values(), ids=list(REJECTED_MODES))
def test_r5_simulated_posix_group_writable_or_other_accessible_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    path = _write(tmp_path)
    _simulate(monkeypatch, os_name="posix", mode=mode)
    with pytest.raises(ConfigError) as info:
        _load(path)
    message = str(info.value)
    assert "APP_CONFIG_FILE" in message, "message should name the variable"
    assert DB_CRED not in message
    assert "postgresql" not in message
    assert "DISTINCTIVE" not in message


def test_r5_rejection_message_does_not_depend_on_or_leak_the_path_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, 'database_url = "not even valid toml ' + DB_CRED)
    _simulate(monkeypatch, os_name="posix", mode=0o666)
    with pytest.raises(ConfigError) as info:
        _load(path)
    assert DB_CRED not in str(info.value)
    assert info.value.__cause__ is None or DB_CRED not in repr(info.value.__cause__)


def test_r5_rejected_file_content_is_not_used_for_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path)
    _simulate(monkeypatch, os_name="posix", mode=0o664)
    with pytest.raises(ConfigError):
        load_settings({"ENV": "prod", "APP_CONFIG_FILE": str(path)})


def test_r5_environment_variables_do_not_need_the_file_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No config file named: nothing to check, so nothing to reject."""
    _simulate(monkeypatch, os_name="posix", mode=0o666)
    assert load_settings({"ENV": "dev"}).log_level == "INFO"


def test_r5_missing_file_gives_an_error_that_names_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _simulate(monkeypatch, os_name="posix", mode=0o600)
    with pytest.raises(ConfigError, match="APP_CONFIG_FILE"):
        _load(tmp_path / "does-not-exist.toml")


# ---- Windows behaviour (simulated on any host, real on Windows) -----------------------------


def test_r5_simulated_windows_logs_a_warning_and_accepts_any_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path)
    _simulate(monkeypatch, os_name="nt", mode=0o777)
    with caplog.at_level(logging.WARNING):
        settings = _load(path)
    assert settings.log_level == "ERROR"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "a warning must be logged when the permission check is skipped"
    text = " ".join(r.getMessage() for r in warnings)
    assert "APP_CONFIG_FILE" in text
    assert DB_CRED not in text
    assert DB_CRED not in caplog.text


@pytest.mark.skipif(os.name != "nt", reason="exercises the real Windows branch")
def test_r5_real_windows_file_is_accepted_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path)
    with caplog.at_level(logging.WARNING):
        settings = _load(path)
    assert settings.log_level == "ERROR"
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert DB_CRED not in caplog.text


# ---- real chmod (POSIX only; never ran on the Windows development host) ---------------------

posix_only = pytest.mark.skipif(os.name == "nt", reason="real POSIX permission bits needed")


@posix_only
@pytest.mark.parametrize("mode", ACCEPTED_MODES, ids=[oct(m) for m in ACCEPTED_MODES])
def test_r5_real_chmod_accepted_modes(tmp_path: Path, mode: int) -> None:
    path = _write(tmp_path)
    path.chmod(mode)
    assert _load(path).log_level == "ERROR"


@posix_only
@pytest.mark.parametrize("mode", sorted(set(REJECTED_MODES.values())), ids=oct)
def test_r5_real_chmod_rejected_modes(tmp_path: Path, mode: int) -> None:
    path = _write(tmp_path)
    path.chmod(mode)
    with pytest.raises(ConfigError) as info:
        _load(path)
    assert "APP_CONFIG_FILE" in str(info.value)
    assert DB_CRED not in str(info.value)


@posix_only
def test_r5_real_chmod_a_group_writable_file_becomes_acceptable_after_tightening(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path)
    path.chmod(0o660)
    with pytest.raises(ConfigError):
        _load(path)
    path.chmod(0o600)
    assert _load(path).log_level == "ERROR"
