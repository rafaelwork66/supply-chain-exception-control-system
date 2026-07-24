"""harden ingestion control lineage

Revision ID: 20260724_0002
Revises: 20260720_0001
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_0002"
down_revision: str | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply additive ingestion-control hardening."""

    op.add_column("pipeline_runs", sa.Column("bundle_reference", sa.String(255)))
    op.add_column("pipeline_runs", sa.Column("manifest_hash", sa.String(128)))
    op.add_column("pipeline_runs", sa.Column("bundle_fingerprint", sa.String(128)))
    op.add_column("pipeline_runs", sa.Column("upstream_generator_version", sa.String(80)))
    op.add_column("pipeline_runs", sa.Column("source_row_count", sa.Integer()))
    op.add_column("pipeline_runs", sa.Column("accepted_row_count", sa.Integer()))
    op.add_column("pipeline_runs", sa.Column("rejected_row_count", sa.Integer()))
    op.add_column("pipeline_runs", sa.Column("failure_reason", sa.Text()))
    op.create_check_constraint(
        "pipeline_runs_source_row_count_nonnegative",
        "pipeline_runs",
        "source_row_count is null or source_row_count >= 0",
    )
    op.create_check_constraint(
        "pipeline_runs_accepted_row_count_nonnegative",
        "pipeline_runs",
        "accepted_row_count is null or accepted_row_count >= 0",
    )
    op.create_check_constraint(
        "pipeline_runs_rejected_row_count_nonnegative",
        "pipeline_runs",
        "rejected_row_count is null or rejected_row_count >= 0",
    )

    op.add_column("source_loads", sa.Column("upstream_source_load_id", postgresql.UUID(as_uuid=True)))
    op.add_column("source_loads", sa.Column("upstream_pipeline_run_id", postgresql.UUID(as_uuid=True)))
    op.add_column("source_loads", sa.Column("manifest_dataset_name", sa.String(80)))
    op.add_column("source_loads", sa.Column("manifest_file_name", sa.String(255)))
    op.add_column("source_loads", sa.Column("manifest_file_hash", sa.String(128)))

    op.add_column(
        "rejected_records",
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipeline_runs.id")),
    )
    op.alter_column("rejected_records", "source_load_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("rejected_records", sa.Column("dataset_name", sa.String(80)))
    op.add_column("rejected_records", sa.Column("source_row_number", sa.Integer()))
    op.add_column("rejected_records", sa.Column("source_natural_key", sa.String(255)))
    op.add_column("rejected_records", sa.Column("raw_row_fingerprint", sa.String(128)))
    op.add_column("rejected_records", sa.Column("classification", sa.String(40)))
    op.add_column(
        "rejected_records",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_check_constraint(
        "rejected_records_source_row_number_positive",
        "rejected_records",
        "source_row_number is null or source_row_number > 0",
    )

    op.add_column("reconciliation_results", sa.Column("inserted_count", sa.Integer()))
    op.add_column("reconciliation_results", sa.Column("existing_count", sa.Integer()))
    op.add_column("reconciliation_results", sa.Column("conflicting_count", sa.Integer()))
    op.add_column("reconciliation_results", sa.Column("rejected_count", sa.Integer()))
    op.add_column("reconciliation_results", sa.Column("matched_target_count", sa.Integer()))
    op.add_column("reconciliation_results", sa.Column("total_table_count", sa.Integer()))
    op.add_column("reconciliation_results", sa.Column("status", sa.String(20)))
    op.add_column("reconciliation_results", sa.Column("explanation", sa.Text()))

    op.add_column("product_site_inventory_policies", sa.Column("criticality", sa.String(40)))
    op.add_column("purchase_order_line_versions", sa.Column("unit_price_aud", sa.Numeric(18, 2)))
    op.add_column("purchase_order_line_versions", sa.Column("line_value_aud", sa.Numeric(18, 2)))
    op.create_check_constraint(
        "polv_unit_price_aud_nonnegative",
        "purchase_order_line_versions",
        "unit_price_aud is null or unit_price_aud >= 0",
    )
    op.create_check_constraint(
        "polv_line_value_aud_nonnegative",
        "purchase_order_line_versions",
        "line_value_aud is null or line_value_aud >= 0",
    )


def downgrade() -> None:
    """Remove additive ingestion-control hardening."""

    op.drop_constraint("polv_line_value_aud_nonnegative", "purchase_order_line_versions", type_="check")
    op.drop_constraint("polv_unit_price_aud_nonnegative", "purchase_order_line_versions", type_="check")
    op.drop_column("purchase_order_line_versions", "line_value_aud")
    op.drop_column("purchase_order_line_versions", "unit_price_aud")
    op.drop_column("product_site_inventory_policies", "criticality")

    for column in (
        "explanation",
        "status",
        "total_table_count",
        "matched_target_count",
        "rejected_count",
        "conflicting_count",
        "existing_count",
        "inserted_count",
    ):
        op.drop_column("reconciliation_results", column)

    op.drop_constraint("rejected_records_source_row_number_positive", "rejected_records", type_="check")
    for column in (
        "rejected_at",
        "classification",
        "raw_row_fingerprint",
        "source_natural_key",
        "source_row_number",
        "dataset_name",
    ):
        op.drop_column("rejected_records", column)
    op.execute("delete from rejected_records where source_load_id is null")
    op.alter_column("rejected_records", "source_load_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("rejected_records", "pipeline_run_id")

    for column in (
        "manifest_file_hash",
        "manifest_file_name",
        "manifest_dataset_name",
        "upstream_pipeline_run_id",
        "upstream_source_load_id",
    ):
        op.drop_column("source_loads", column)

    op.drop_constraint("pipeline_runs_rejected_row_count_nonnegative", "pipeline_runs", type_="check")
    op.drop_constraint("pipeline_runs_accepted_row_count_nonnegative", "pipeline_runs", type_="check")
    op.drop_constraint("pipeline_runs_source_row_count_nonnegative", "pipeline_runs", type_="check")
    for column in (
        "failure_reason",
        "rejected_row_count",
        "accepted_row_count",
        "source_row_count",
        "upstream_generator_version",
        "bundle_fingerprint",
        "manifest_hash",
        "bundle_reference",
    ):
        op.drop_column("pipeline_runs", column)
