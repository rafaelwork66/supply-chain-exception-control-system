"""Tests for structured logging configuration."""

from __future__ import annotations

import json
import logging

from scecs.logging_config import JsonLogFormatter


def test_json_log_formatter_outputs_expected_fields() -> None:
    """Formatter should create parseable JSON with stable fields."""

    record = logging.LogRecord(
        name="scecs.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="foundation ready",
        args=(),
        exc_info=None,
    )

    formatted = JsonLogFormatter().format(record)
    payload = json.loads(formatted)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "scecs.test"
    assert payload["message"] == "foundation ready"
    assert "timestamp" in payload
