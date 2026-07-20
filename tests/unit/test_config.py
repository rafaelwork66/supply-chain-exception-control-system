"""Tests for environment-variable configuration."""

import pytest
from pytest import MonkeyPatch

from scecs.config import ConfigurationError, get_database_settings, get_settings


def test_get_settings_uses_environment_variables(monkeypatch: MonkeyPatch) -> None:
    """Settings should use explicit environment values when they exist."""

    monkeypatch.setenv("SCECS_ENVIRONMENT", "test")
    monkeypatch.setenv("SCECS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("SCECS_APP_NAME", "Test App")

    settings = get_settings()

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.app_name == "Test App"


def test_database_settings_fail_when_required_values_are_missing(monkeypatch: MonkeyPatch) -> None:
    """Database settings should fail clearly when required values are absent."""

    monkeypatch.setenv("SCECS_ENVIRONMENT", "test")
    for key in [
        "SCECS_DB_HOST",
        "SCECS_DB_PORT",
        "SCECS_DB_NAME",
        "SCECS_DB_USER",
        "SCECS_DB_PASSWORD",
    ]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigurationError, match="SCECS_DB_NAME"):
        get_database_settings()


def test_database_settings_reject_production_environment(monkeypatch: MonkeyPatch) -> None:
    """Tests and local commands should not connect to production databases."""

    monkeypatch.setenv("SCECS_ENVIRONMENT", "production")
    monkeypatch.setenv("SCECS_DB_HOST", "localhost")
    monkeypatch.setenv("SCECS_DB_PORT", "5432")
    monkeypatch.setenv("SCECS_DB_NAME", "scecs_dev")
    monkeypatch.setenv("SCECS_DB_USER", "scecs_user")
    monkeypatch.setenv("SCECS_DB_PASSWORD", "scecs_password")

    with pytest.raises(ConfigurationError, match="production"):
        get_database_settings()
