"""Helpers for the QA scaffold tests (T-004). Synthetic values only.

Expected behaviour in these tests comes from the T-001 acceptance criteria (A2-A10), not from
the implementation's own tests. The source is used only to learn how to build the app.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from pydantic import SecretStr

from backend.api.app import create_app
from backend.platform.config import Settings

SYNTHETIC_DB_URL = "postgresql://synthetic-user:synthetic-pw@db.invalid/synthetic"


def make_settings(*, dev: bool, **overrides: Any) -> Settings:
    if dev:
        return Settings(env="dev", **overrides)
    return Settings(env="prod", database_url=SecretStr(SYNTHETIC_DB_URL), **overrides)


def make_app(*, dev: bool = True, **overrides: Any) -> Any:
    return create_app(make_settings(dev=dev, **overrides))


def snapshot_logging() -> tuple[list[logging.Handler], int]:
    root = logging.getLogger()
    return list(root.handlers), root.level


def restore_logging(state: tuple[list[logging.Handler], int]) -> None:
    root = logging.getLogger()
    root.handlers[:] = state[0]
    root.setLevel(state[1])


def logging_guard() -> Iterator[None]:
    """create_app() reconfigures the root logger; put it back after each test."""
    state = snapshot_logging()
    try:
        yield
    finally:
        restore_logging(state)
