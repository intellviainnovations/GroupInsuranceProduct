"""QA tests for T-001 acceptance criterion A6: missing/invalid config fails fast, no secrets."""

from __future__ import annotations

import traceback
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.api.app import create_app
from backend.platform.config import ConfigError, load_settings
from scaffold_support import logging_guard

SECRET = "DISTINCTIVE-secret-5531"  # secret-scan:allow


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    yield from logging_guard()


def full_text(exc: BaseException) -> str:
    """Message, repr and the whole chained traceback text."""
    return " ".join([str(exc), repr(exc), "".join(traceback.format_exception(exc))])


def test_a6_production_without_database_url_fails_with_clear_error() -> None:
    with pytest.raises(ConfigError) as info:
        load_settings({"ENV": "prod"})
    message = str(info.value).lower()
    assert "database_url" in message


def test_a6_unset_env_defaults_to_production_and_requires_database_url() -> None:
    with pytest.raises(ConfigError) as info:
        load_settings({})
    assert "database_url" in str(info.value).lower()


def test_a6_empty_database_url_is_treated_as_missing() -> None:
    with pytest.raises(ConfigError):
        load_settings({"ENV": "prod", "APP_DATABASE_URL": ""})


def test_a6_error_does_not_contain_secret_supplied_in_another_variable() -> None:
    environ = {
        "ENV": "prod",
        "APP_LOG_LEVEL": SECRET,  # invalid, and distinctive
        "APP_CONFIG_FILE": "",
    }
    with pytest.raises(ConfigError) as info:
        load_settings(environ)
    assert SECRET not in full_text(info.value)


def test_a6_valid_database_url_is_not_echoed_when_another_field_is_invalid() -> None:
    environ = {
        "ENV": "prod",
        "APP_DATABASE_URL": f"postgresql://user:{SECRET}@db.invalid/app",  # secret-scan:allow
        "APP_THROTTLE_MAX_REQUESTS": "not-a-number",
        "APP_LOG_LEVEL": "LOUD",
    }
    with pytest.raises(ConfigError) as info:
        load_settings(environ)
    text = full_text(info.value)
    assert SECRET not in text
    assert "postgresql://" not in text
    assert "throttle_max_requests" in text
    assert "log_level" in text


def test_a6_secret_in_config_file_is_not_echoed_on_failure(tmp_path: Path) -> None:
    config = tmp_path / "settings.toml"
    config.write_text(
        f'database_url = "postgresql://user:{SECRET}@db.invalid/app"\n'  # secret-scan:allow
        'log_level = "NOT-A-LEVEL"\n'
        f'unknown_field = "{SECRET}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as info:
        load_settings({"ENV": "prod", "APP_CONFIG_FILE": str(config)})
    assert SECRET not in full_text(info.value)


def test_a6_malformed_config_file_fails_with_config_error_and_no_content(tmp_path: Path) -> None:
    config = tmp_path / "broken.toml"
    config.write_text(f'database_url = "{SECRET}\nthis is not toml', encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_settings({"ENV": "prod", "APP_CONFIG_FILE": str(config)})
    assert SECRET not in full_text(info.value)


def test_a6_missing_config_file_fails_with_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings({"ENV": "prod", "APP_CONFIG_FILE": str(tmp_path / "absent.toml")})


def test_a6_create_app_without_settings_fails_fast_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("APP_LOG_LEVEL", "INFO")
    with pytest.raises(ConfigError) as info:
        create_app()
    assert "database_url" in str(info.value).lower()


def test_a6_create_app_without_settings_and_no_env_at_all_fails_fast() -> None:
    with pytest.raises(ConfigError):
        create_app()


def test_a6_dev_mode_needs_no_database_url() -> None:
    settings = load_settings({"ENV": "dev"})
    assert settings.production is False
    assert create_app(settings) is not None


@pytest.mark.parametrize("env_value", ["DEV", "Dev", "development", "staging", "production"])
def test_a6_only_exact_dev_waives_the_database_url_requirement(env_value: str) -> None:
    with pytest.raises(ConfigError):
        load_settings({"ENV": env_value})


def test_a6_production_with_database_url_loads() -> None:
    settings = load_settings({"ENV": "prod", "APP_DATABASE_URL": "postgresql://x.invalid/app"})
    assert settings.production is True


def test_a6_secret_value_is_masked_in_settings_repr() -> None:
    settings = load_settings(
        {"ENV": "prod", "APP_DATABASE_URL": f"postgresql://u:{SECRET}@h/d"}  # secret-scan:allow
    )
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
