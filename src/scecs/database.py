"""SQLAlchemy database infrastructure.

This module provides connection and session helpers only. It does not define
domain tables or supply-chain business logic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from scecs.config import DatabaseSettings, get_database_settings


def create_database_engine(settings: DatabaseSettings | None = None) -> Engine:
    """Create a SQLAlchemy engine from typed database settings."""

    database_settings = settings or get_database_settings()
    return create_engine(database_settings.sqlalchemy_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a typed SQLAlchemy session factory."""

    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide transaction-safe session handling.

    The session commits when the block succeeds. It rolls back and re-raises when
    the block fails, then always closes the session.
    """

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

