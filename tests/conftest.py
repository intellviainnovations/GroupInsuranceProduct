"""Shared test setup. QA adds real fixtures and tests; this keeps the environment isolated."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the developer's ENV or APP_* variables."""
    import os

    for name in list(os.environ):
        if name == "ENV" or name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)
