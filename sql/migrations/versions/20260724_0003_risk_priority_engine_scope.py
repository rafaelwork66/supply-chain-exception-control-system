"""allow analytical risk disposition before workflow creation

Revision ID: 20260724_0003
Revises: 20260724_0002
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260724_0003"
down_revision: str | None = "20260724_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_DISPOSITIONS = (
    "'below-opening-threshold',"
    "'opened-new-episode',"
    "'linked-existing-active-episode',"
    "'opening-eligible-no-workflow',"
    "'suppressed-by-existing-control',"
    "'ineligible-after-validation',"
    "'manual-review-data-insufficient',"
    "'scoring-error'"
)

OLD_DISPOSITIONS = (
    "'below-opening-threshold',"
    "'opened-new-episode',"
    "'linked-existing-active-episode',"
    "'suppressed-by-existing-control',"
    "'ineligible-after-validation',"
    "'manual-review-data-insufficient',"
    "'scoring-error'"
)


def upgrade() -> None:
    """Permit a candidate to be opening-eligible without creating workflow rows."""

    _drop_disposition_check()
    op.create_check_constraint(
        "candidate_risk_evaluations_disposition_check",
        "candidate_risk_evaluations",
        f"disposition in ({NEW_DISPOSITIONS})",
    )


def downgrade() -> None:
    """Restore the original lifecycle-era disposition constraint."""

    op.execute(
        "update candidate_risk_evaluations "
        "set disposition = 'below-opening-threshold' "
        "where disposition = 'opening-eligible-no-workflow'"
    )
    _drop_disposition_check()
    op.create_check_constraint(
        "candidate_risk_evaluations_disposition_check",
        "candidate_risk_evaluations",
        f"disposition in ({OLD_DISPOSITIONS})",
    )


def _drop_disposition_check() -> None:
    op.execute(
        """
        do $$
        declare
            constraint_name text;
        begin
            select conname
            into constraint_name
            from pg_constraint
            where conrelid = 'candidate_risk_evaluations'::regclass
              and contype = 'c'
              and pg_get_constraintdef(oid) like '%disposition%'
            limit 1;

            if constraint_name is not null then
                execute format(
                    'alter table candidate_risk_evaluations drop constraint %I',
                    constraint_name
                );
            end if;
        end $$;
        """
    )
