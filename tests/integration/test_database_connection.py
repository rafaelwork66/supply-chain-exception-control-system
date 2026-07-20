"""PostgreSQL integration tests."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from scecs.database import create_database_engine


@pytest.mark.integration
def test_postgresql_connection_executes_harmless_query() -> None:
    """The configured PostgreSQL database should answer a harmless query."""

    engine = create_database_engine()

    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))

    assert result.scalar_one() == 1


@pytest.mark.integration
def test_postgresql_schema_migration_creates_domain_constraints() -> None:
    """Alembic should create the governed physical schema on PostgreSQL."""

    command.upgrade(Config("alembic.ini"), "head")
    engine = create_database_engine()

    with engine.connect() as connection:
        table_count = connection.execute(
            text(
                """
                select count(*)
                from information_schema.tables
                where table_schema = 'public'
                  and table_name in (
                    'source_systems',
                    'purchase_order_lines',
                    'candidate_risk_evaluations',
                    'exception_episodes',
                    'exception_event_envelopes',
                    'evidence_links',
                    'analytics_publications'
                  )
                """
            )
        ).scalar_one()
        active_index_count = connection.execute(
            text(
                """
                select count(*)
                from pg_indexes
                where schemaname = 'public'
                  and tablename = 'exception_episodes'
                  and indexname = 'uq_exception_episodes_active_line_site'
                  and indexdef like '%WHERE ((current_state)::text <> ''closed''::text)%'
                """
            )
        ).scalar_one()
        overlap_constraint_count = connection.execute(
            text(
                """
                select count(*)
                from pg_constraint
                where contype = 'x'
                  and conname in (
                    'ex_supplier_versions_no_overlap',
                    'ex_product_versions_no_overlap',
                    'ex_product_site_inventory_policies_no_overlap',
                    'ex_ownership_mappings_no_overlap',
                    'ex_uom_conversions_no_overlap'
                  )
                """
            )
        ).scalar_one()

    assert table_count == 7
    assert active_index_count == 1
    assert overlap_constraint_count == 5
