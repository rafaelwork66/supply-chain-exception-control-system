"""Environment-based configuration for the application foundation.

The module intentionally keeps configuration small at this stage. Future database,
dashboard, notification, and AI settings can be added when those features exist.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    environment: str = "development"
    log_level: str = "INFO"
    app_name: str = "Supply Chain Exception Control System"


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL connection settings loaded from environment variables."""

    host: str
    port: int
    name: str
    user: str
    password: str

    @property
    def sqlalchemy_url(self) -> str:
        """Build a SQLAlchemy PostgreSQL URL for psycopg."""

        user = quote_plus(self.user)
        password = quote_plus(self.password)
        host = quote_plus(self.host)
        name = quote_plus(self.name)
        return f"postgresql+psycopg://{user}:{password}@{host}:{self.port}/{name}"


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or unsafe."""


def get_settings() -> Settings:
    """Load application settings from environment variables."""

    return Settings(
        environment=os.getenv("SCECS_ENVIRONMENT", "development"),
        log_level=os.getenv("SCECS_LOG_LEVEL", "INFO"),
        app_name=os.getenv("SCECS_APP_NAME", "Supply Chain Exception Control System"),
    )


def get_required_env(name: str) -> str:
    """Return a required environment variable or raise a clear error."""

    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def get_database_settings() -> DatabaseSettings:
    """Load PostgreSQL settings and reject unsafe production targets."""

    settings = get_settings()
    if settings.environment.lower() in {"prod", "production"}:
        raise ConfigurationError("Database access is blocked when SCECS_ENVIRONMENT is production.")

    database_name = get_required_env("SCECS_DB_NAME")
    if "prod" in database_name.lower() or "production" in database_name.lower():
        raise ConfigurationError(
            "Refusing to connect to a database name that looks like production."
        )

    raw_port = get_required_env("SCECS_DB_PORT")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ConfigurationError("SCECS_DB_PORT must be an integer.") from exc

    return DatabaseSettings(
        host=get_required_env("SCECS_DB_HOST"),
        port=port,
        name=database_name,
        user=get_required_env("SCECS_DB_USER"),
        password=get_required_env("SCECS_DB_PASSWORD"),
    )
