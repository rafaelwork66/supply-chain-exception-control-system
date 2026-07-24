"""protect immutable exception workflow history

Revision ID: 20260724_0004
Revises: 20260724_0003
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260724_0004"
down_revision: str | None = "20260724_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMMUTABLE_TABLES = (
    "exception_event_envelopes",
    "exception_state_events",
    "exception_actions",
    "ownership_events",
    "approval_requests",
    "approval_decisions",
    "suppression_controls",
    "evidence_references",
    "evidence_links",
    "resolution_records",
)


def upgrade() -> None:
    """Prevent direct mutation of workflow audit-history rows."""

    op.execute(
        """
        create or replace function prevent_exception_history_mutation()
        returns trigger
        language plpgsql
        as $$
        begin
            raise exception 'exception workflow history is immutable';
        end;
        $$;
        """
    )
    for table_name in IMMUTABLE_TABLES:
        op.execute(
            f"""
            create trigger {table_name}_immutable
            before update or delete on {table_name}
            for each row execute function prevent_exception_history_mutation();
            """
        )


def downgrade() -> None:
    """Remove immutable-history triggers."""

    for table_name in IMMUTABLE_TABLES:
        op.execute(f"drop trigger if exists {table_name}_immutable on {table_name};")
    op.execute("drop function if exists prevent_exception_history_mutation();")
