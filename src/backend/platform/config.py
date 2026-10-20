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
from typing import Any, Literal, Self

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


# Run modes that may use synthetic data (memory backend, fake adapters). Decided 2026-10-18.
SYNTHETIC_ENVS = frozenset({"dev", "demo"})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Run mode. Anything other than "dev" is production, so a missing value is safe. "demo" keeps
    # every production hardening but may run on synthetic data.
    env: str = "prod"
    log_level: str = "INFO"
    # Application database (PostgreSQL). Required outside dev when the SQL backend is used.
    database_url: SecretStr | None = None
    throttle_enabled: bool = True
    throttle_max_requests: int = Field(default=120, gt=0)
    throttle_window_seconds: int = Field(default=60, gt=0)

    # Backend and adapter switches (docs/design/repositories.md section 4). None means "not set":
    # dev/demo then use memory and the fakes; any other ENV uses sql and unconfigured adapters,
    # which fail closed. An explicit memory or fake outside dev/demo is refused.
    data_backend: Literal["memory", "sql"] | None = None
    insurer_adapter: Literal["fake", "usgic"] | None = None
    bank_auth: Literal["fake", "esb"] | None = None
    cbs: Literal["fake"] | None = None

    # Sessions and CSRF (docs/contracts/staff-api.md).
    session_secret: SecretStr | None = None
    allowed_origins: str = ""
    session_cookie_secure: bool = True
    session_idle_minutes: int = Field(default=15, gt=0)  # placeholder until Q29
    session_absolute_minutes: int = Field(default=480, gt=0)  # placeholder until Q29
    login_max_failures: int = Field(default=5, gt=0)  # placeholder until Q29
    login_lock_minutes: int = Field(default=15, gt=0)
    otp_challenge_minutes: int = Field(default=5, gt=0)

    # Business plumbing (not insurance rules).
    selectable_account_statuses: str = "ACTIVE"  # Assumption, Q33
    issue_retry_limit: int = Field(default=3, gt=0)
    retry_delay_seconds: int = Field(default=60, ge=0)
    job_worker_enabled: bool = True
    job_poll_seconds: float = Field(default=2.0, gt=0)
    fake_delay_ms: int = Field(default=300, ge=0)
    cbs_timeout_seconds: float = Field(default=5.0, gt=0)

    # USGIC UAT adapter (docs/contracts/usgic-gpa.md). Values only from protected config.
    usgic_base_url: str | None = None
    usgic_user_name: str | None = None
    usgic_password: SecretStr | None = None
    usgic_product_code: str | None = None
    usgic_intermediary_code: str | None = None
    usgic_intermediary_branch_code: str | None = None
    usgic_cipher: Literal["unconfigured", "aes-256-cbc"] = "unconfigured"
    usgic_cipher_key: SecretStr | None = None
    # ABHI API (Azure APIM) subscription key, sent as Ocp-Apim-Subscription-Key header.
    abhi_apim_subscription_key: SecretStr | None = None
    usgic_token_header: str = "TokenId"  # noqa: S105 - a header name, not a secret
    usgic_token_refresh_margin_seconds: int = Field(default=300, ge=0)
    usgic_token_default_ttl_seconds: int = Field(default=3000, gt=0)
    usgic_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    usgic_read_timeout_seconds: float = Field(default=30.0, gt=0)

    @property
    def production(self) -> bool:
        return self.env != "dev"

    @property
    def synthetic_allowed(self) -> bool:
        return self.env in SYNTHETIC_ENVS

    @property
    def resolved_data_backend(self) -> str:
        if self.data_backend is not None:
            return self.data_backend
        return "memory" if self.synthetic_allowed else "sql"

    def resolved_adapter(self, name: Literal["insurer_adapter", "bank_auth", "cbs"]) -> str:
        value: str | None = getattr(self, name)
        if value is not None:
            return value
        return "fake" if self.synthetic_allowed else "unconfigured"

    @property
    def synthetic_data(self) -> bool:
        """True when the memory backend or any fake adapter is active (demo banner)."""
        return self.resolved_data_backend == "memory" or any(
            self.resolved_adapter(n) == "fake" for n in ("insurer_adapter", "bank_auth", "cbs")
        )

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        return frozenset(o.strip() for o in self.allowed_origins.split(",") if o.strip())

    @property
    def selectable_status_set(self) -> frozenset[str]:
        return frozenset(
            s.strip().upper() for s in self.selectable_account_statuses.split(",") if s.strip()
        )

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in _LOG_LEVELS:
            raise ValueError("must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return level

    @model_validator(mode="after")
    def _check_required(self) -> Self:
        if not self.synthetic_allowed:
            if self.data_backend == "memory":
                raise ValueError("data_backend 'memory' is allowed only when ENV is dev or demo")
            for name in ("insurer_adapter", "bank_auth", "cbs"):
                if getattr(self, name) == "fake":
                    raise ValueError(f"{name} 'fake' is allowed only when ENV is dev or demo")
        missing = self.database_url is None or not self.database_url.get_secret_value()
        if self.production and self.resolved_data_backend == "sql" and missing:
            raise ValueError("database_url is required when ENV is not 'dev'")
        if self.session_secret is not None and len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("session_secret must be at least 32 characters")
        if not self.session_cookie_secure and self.env != "dev":
            raise ValueError("session_cookie_secure may be false only when ENV is 'dev'")
        if self.bank_auth == "esb":
            raise ValueError("bank_auth 'esb' is not available yet (waiting for keys, Q29)")
        if self.insurer_adapter == "usgic":
            for name in ("usgic_base_url", "usgic_user_name", "usgic_product_code"):
                if not getattr(self, name):
                    raise ValueError(f"{name} is required when insurer_adapter is 'usgic'")
            if self.usgic_cipher == "aes-256-cbc":
                if self.usgic_cipher_key is None:
                    raise ValueError(
                        "usgic_cipher_key is required when usgic_cipher is 'aes-256-cbc'"
                    )
                key_len = len(self.usgic_cipher_key.get_secret_value().encode("utf-8"))
                if key_len != 32:
                    raise ValueError(
                        "usgic_cipher_key must be exactly 32 bytes for AES-256"
                    )
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
