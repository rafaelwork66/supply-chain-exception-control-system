"""PostgreSQL integration tests."""

import pytest
from sqlalchemy import text

from scecs.database import create_database_engine


@pytest.mark.integration
def test_postgresql_connection_executes_harmless_query() -> None:
    """The configured PostgreSQL database should answer a harmless query."""

    engine = create_database_engine()

    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))

    assert result.scalar_one() == 1
