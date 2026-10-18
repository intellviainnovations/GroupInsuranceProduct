"""Typed configuration: environment variables plus an optional protected config file.

Precedence: environment variable over config file over default. Environment variables are
``ENV`` (run mode) and ``APP_<FIELD>`` for every other field. The optional file is TOML,
named by ``APP_CONFIG_FILE``, with the field names as keys. Secrets come only from there,
never from code. Error messages name fields, never values.
"""

from __future__ import annotations

import logging
import os
import stat
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

CONFIG_FILE_VAR = "APP_CONFIG_FILE"
_logger = logging.getLogger("backend.config")
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigError(Exception):
    """Startup configuration is missing or invalid. The message never contains secret values."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Run mode. Anything other than "dev" is production, so a missing value is safe.
    env: str = "prod"
    log_level: str = "INFO"
    # Application database (PostgreSQL). Required outside dev; unused until persistence lands.
    database_url: SecretStr | None = None
    throttle_enabled: bool = True
    throttle_max_requests: int = Field(default=120, gt=0)
    throttle_window_seconds: int = Field(default=60, gt=0)

    @property
    def production(self) -> bool:
        return self.env != "dev"

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in _LOG_LEVELS:
            raise ValueError("must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return level

    @model_validator(mode="after")
    def _check_required(self) -> Self:
        missing = self.database_url is None or not self.database_url.get_secret_value()
        if self.production and missing:
            raise ValueError("database_url is required when ENV is not 'dev'")
        return self


def _read_config_file(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise ConfigError(f"{CONFIG_FILE_VAR}: cannot read config file") from exc
    if os.name == "nt":
        # POSIX permission bits carry no meaning on Windows: protect the file with NTFS ACLs.
        _logger.warning(
            "%s: config file permission check skipped on this platform", CONFIG_FILE_VAR
        )
    elif mode & (stat.S_IRWXO | stat.S_IWGRP):
        raise ConfigError(
            f"{CONFIG_FILE_VAR}: config file must not be accessible to other users "
            "or writable by its group"
        )
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{CONFIG_FILE_VAR}: config file is not valid TOML") from exc


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from the environment (default os.environ); raise ConfigError on failure."""
    env = os.environ if environ is None else environ
    values: dict[str, Any] = {}
    config_file = env.get(CONFIG_FILE_VAR)
    if config_file:
        values.update(_read_config_file(config_file))
    if "ENV" in env:
        values["env"] = env["ENV"]
    for name in Settings.model_fields:
        if name == "env":
            continue
        var = f"APP_{name.upper()}"
        if var in env:
            values[name] = env[var]
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        problems = []
        for error in exc.errors(include_input=False, include_url=False, include_context=False):
            loc = ".".join(str(part) for part in error["loc"]) or "settings"
            problems.append(f"{loc}: {error['msg']}")
        raise ConfigError("invalid configuration: " + "; ".join(problems)) from None
