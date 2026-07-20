"""Shared pytest configuration."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip PostgreSQL integration tests unless explicitly enabled."""

    if os.getenv("SCECS_RUN_INTEGRATION_TESTS") == "1":
        return

    reason = (
        "Set SCECS_RUN_INTEGRATION_TESTS=1 and configure PostgreSQL "
        "to run integration tests."
    )
    skip_integration = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
