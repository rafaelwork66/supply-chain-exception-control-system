"""Alembic migration environment."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from scecs.config import get_database_settings
from scecs.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_target_metadata() -> object | None:
    """Use model metadata for autogeneration without affecting hand-authored migrations."""

    command_options = getattr(config, "cmd_opts", None)
    if command_options is not None and getattr(command_options, "autogenerate", False):
        return target_metadata
    return None


def run_migrations_offline() -> None:
    """Run migrations without creating a live database connection."""

    url = get_database_settings().sqlalchemy_url
    context.configure(
        url=url,
        target_metadata=get_target_metadata(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations through a live SQLAlchemy connection."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_settings().sqlalchemy_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=get_target_metadata())

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
