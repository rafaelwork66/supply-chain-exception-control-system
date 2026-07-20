"""Database health-check command.

Run with:
    python -m scecs.db_health
"""

from __future__ import annotations

import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from scecs.config import ConfigurationError
from scecs.database import create_database_engine


def check_database_health() -> bool:
    """Return True when PostgreSQL accepts a simple connection query."""

    engine = create_database_engine()
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        value: object = result.scalar_one()
        return value == 1


def main() -> None:
    """Run the command-line database health check."""

    try:
        if check_database_health():
            print("Database health check passed.")
    except (ConfigurationError, SQLAlchemyError) as exc:
        print(f"Database health check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
