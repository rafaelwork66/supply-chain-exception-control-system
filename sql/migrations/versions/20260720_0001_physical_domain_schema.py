"""create physical domain schema

Revision ID: 20260720_0001
Revises:
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk() -> sa.Column[sa.UUID]:
    """Return a PostgreSQL UUID primary-key column."""

    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def recorded_at() -> sa.Column[sa.DateTime]:
    """Return a timezone-aware recorded timestamp column."""

    return sa.Column(
        "recorded_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    """Apply the initial PostgreSQL physical schema."""

    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "btree_gist"')

    op.create_table(
        "source_systems",
        uuid_pk(),
        sa.Column("source_code", sa.String(50), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("source_code"),
    )
    op.create_table(
        "pipeline_runs",
        uuid_pk(),
        sa.Column("run_reference", sa.String(80), nullable=False),
        sa.Column("run_type", sa.String(40), nullable=False),
        sa.Column("trigger_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("release_version", sa.String(80)),
        sa.Column("configuration_hash", sa.String(128)),
        sa.Column(
            "is_publication_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint("status in ('pending','running','success','failed','cancelled')"),
        sa.UniqueConstraint("run_reference"),
    )
    op.create_table(
        "sites",
        uuid_pk(),
        sa.Column("site_code", sa.String(40), nullable=False),
        sa.Column("site_name", sa.String(120), nullable=False),
        sa.Column("state_code", sa.String(10), nullable=False),
        sa.Column("timezone_name", sa.String(80), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_to", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("site_code"),
    )
    op.create_table(
        "suppliers",
        uuid_pk(),
        sa.Column("supplier_code", sa.String(60), nullable=False),
        sa.UniqueConstraint("supplier_code"),
    )
    op.create_table(
        "products",
        uuid_pk(),
        sa.Column("sku", sa.String(80), nullable=False),
        sa.UniqueConstraint("sku"),
    )
    op.create_table(
        "users",
        uuid_pk(),
        sa.Column("user_code", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("role_classification", sa.String(80), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_to", sa.DateTime(timezone=True)),
        sa.CheckConstraint("actor_type in ('human','system','queue')"),
        sa.UniqueConstraint("user_code"),
    )
    op.create_table(
        "supplier_versions",
        uuid_pk(),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("supplier_category", sa.String(80)),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.CheckConstraint("effective_to is null or effective_to > effective_from"),
        sa.UniqueConstraint("supplier_id", "effective_from"),
    )
    op.create_table(
        "product_versions",
        uuid_pk(),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("base_uom", sa.String(20), nullable=False),
        sa.Column("handling_precision", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.CheckConstraint("handling_precision >= 0"),
        sa.CheckConstraint("effective_to is null or effective_to > effective_from"),
        sa.UniqueConstraint("product_id", "effective_from"),
    )
    op.create_table(
        "rule_versions",
        uuid_pk(),
        sa.Column("rule_code", sa.String(80), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("owner", sa.String(120), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status in ('draft','approved','active','retired')"),
        sa.UniqueConstraint("rule_code", "version"),
    )
    op.create_table(
        "calendar_versions",
        uuid_pk(),
        sa.Column("calendar_code", sa.String(80), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("timezone_name", sa.String(80), nullable=False),
        sa.Column(
            "business_hours",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "holiday_set", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("calendar_code", "version"),
    )
    op.create_table(
        "source_loads",
        uuid_pk(),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipeline_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "source_system_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_systems.id"),
            nullable=False,
        ),
        sa.Column("dataset_type", sa.String(50), nullable=False),
        sa.Column("object_ref", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("pipeline_run_id", "source_system_id", "dataset_type", "object_ref"),
    )
    op.create_table(
        "product_site_inventory_policies",
        uuid_pk(),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False
        ),
        sa.Column("safety_stock_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("policy_source", sa.String(80), nullable=False),
        sa.Column("substitution_group", sa.String(80)),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.CheckConstraint("safety_stock_quantity >= 0"),
        sa.CheckConstraint("effective_to is null or effective_to > effective_from"),
        sa.UniqueConstraint("product_id", "site_id", "effective_from"),
    )
    op.create_table(
        "ownership_mappings",
        uuid_pk(),
        sa.Column("precedence", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(40), nullable=False),
        sa.Column("scope_key", sa.String(120), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id")),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("owner_queue_code", sa.String(80)),
        sa.Column("approval_reference", sa.String(160)),
        sa.Column("evidence_reference", sa.String(160)),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.CheckConstraint("effective_to is null or effective_to > effective_from"),
        sa.UniqueConstraint("precedence", "scope_type", "scope_key", "site_id", "effective_from"),
    )
    op.create_table(
        "rule_component_definitions",
        uuid_pk(),
        sa.Column(
            "rule_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rule_versions.id"),
            nullable=False,
        ),
        sa.Column("component_code", sa.String(80), nullable=False),
        sa.Column("component_family", sa.String(80), nullable=False),
        sa.Column("max_points", sa.Numeric(8, 2)),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("rule_version_id", "component_code"),
    )
    op.create_table(
        "uom_conversions",
        uuid_pk(),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("from_uom", sa.String(20), nullable=False),
        sa.Column("to_uom", sa.String(20), nullable=False),
        sa.Column("conversion_factor", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.CheckConstraint("conversion_factor > 0"),
        sa.CheckConstraint("effective_to is null or effective_to > effective_from"),
        sa.UniqueConstraint("product_id", "from_uom", "to_uom", "effective_from"),
    )
    op.create_table(
        "purchase_orders",
        uuid_pk(),
        sa.Column(
            "source_system_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_systems.id"),
            nullable=False,
        ),
        sa.Column("po_number", sa.String(80), nullable=False),
        sa.UniqueConstraint("source_system_id", "po_number"),
    )
    op.create_table(
        "purchase_order_versions",
        uuid_pk(),
        sa.Column(
            "purchase_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_orders.id"),
            nullable=False,
        ),
        sa.Column(
            "source_load_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_loads.id"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column("amendment_version", sa.Integer(), nullable=False),
        sa.Column("buyer_group", sa.String(80)),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("order_status", sa.String(20), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("order_status in ('open','closed','cancelled','on_hold')"),
        sa.UniqueConstraint("purchase_order_id", "amendment_version"),
    )
    op.create_table(
        "purchase_order_lines",
        uuid_pk(),
        sa.Column(
            "purchase_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_orders.id"),
            nullable=False,
        ),
        sa.Column("canonical_line_key", sa.String(120), nullable=False),
        sa.UniqueConstraint("canonical_line_key"),
    )
    op.create_table(
        "pipeline_step_results",
        uuid_pk(),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipeline_runs.id"),
            nullable=False,
        ),
        sa.Column("step_name", sa.String(80), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("input_hash", sa.String(128)),
        sa.Column("output_hash", sa.String(128)),
        sa.Column("error_classification", sa.String(80)),
        sa.CheckConstraint("attempt_number > 0"),
        sa.CheckConstraint("status in ('pending','running','success','failed','skipped')"),
        sa.UniqueConstraint("pipeline_run_id", "step_name", "attempt_number"),
    )
    op.create_table(
        "rejected_records",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "source_load_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_loads.id"),
            nullable=False,
        ),
        sa.Column("source_row_ref", sa.String(120), nullable=False),
        sa.Column("defect_code", sa.String(80), nullable=False),
        sa.Column("field_name", sa.String(80)),
        sa.Column("observed_value_hash", sa.String(128)),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("disposition", sa.String(30), nullable=False),
        sa.Column("resolution_status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("notes", sa.Text()),
        sa.CheckConstraint(
            "disposition in ('reject_row','quarantine_row','stop_dataset','stop_run','warning')"
        ),
    )
    op.create_table(
        "reconciliation_results",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipeline_runs.id"),
            nullable=False,
        ),
        sa.Column("stage_name", sa.String(80), nullable=False),
        sa.Column("metric_name", sa.String(80), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("difference_count", sa.Integer(), nullable=False),
        sa.Column("is_blocking", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint("difference_count >= 0"),
        sa.UniqueConstraint("pipeline_run_id", "stage_name", "metric_name"),
    )
    op.create_table(
        "analytics_publications",
        uuid_pk(),
        recorded_at(),
        sa.Column("publication_reference", sa.String(80), nullable=False),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipeline_runs.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("reconciliation_hash", sa.String(128)),
        sa.Column(
            "is_current_success", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint("status in ('success','failed','superseded')"),
        sa.UniqueConstraint("publication_reference"),
    )
    op.create_index(
        "uq_analytics_publications_one_current_success",
        "analytics_publications",
        ["is_current_success"],
        unique=True,
        postgresql_where=sa.text("is_current_success"),
    )

    _create_procurement_tables()
    _create_scoring_and_workflow_tables()
    _create_postgresql_constraints()


def _create_procurement_tables() -> None:
    """Create procurement and supply observation tables."""

    op.create_table(
        "purchase_order_line_aliases",
        uuid_pk(),
        sa.Column(
            "po_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "source_system_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_systems.id"),
            nullable=False,
        ),
        sa.Column("source_po_number", sa.String(80), nullable=False),
        sa.Column("source_line_number", sa.String(80), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("correction_reason", sa.String(160)),
        sa.UniqueConstraint("source_system_id", "source_po_number", "source_line_number"),
    )
    op.create_table(
        "purchase_order_line_versions",
        uuid_pk(),
        sa.Column(
            "po_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "source_load_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_loads.id"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False
        ),
        sa.Column("amendment_version", sa.Integer(), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("order_uom", sa.String(20), nullable=False),
        sa.Column("base_quantity", sa.Numeric(18, 4)),
        sa.Column("need_date", sa.Date(), nullable=False),
        sa.Column("requested_date", sa.Date()),
        sa.Column("line_status", sa.String(20), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordered_quantity > 0"),
        sa.CheckConstraint("line_status in ('open','closed','cancelled','on_hold')"),
        sa.UniqueConstraint("po_line_id", "amendment_version"),
    )
    op.create_table(
        "delivery_schedules",
        uuid_pk(),
        sa.Column(
            "po_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id"),
            nullable=False,
        ),
        sa.Column("source_schedule_key", sa.String(100), nullable=False),
        sa.Column("schedule_version", sa.Integer(), nullable=False),
        sa.Column("scheduled_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("requested_date", sa.Date()),
        sa.Column("confirmed_date", sa.Date()),
        sa.Column("expected_date", sa.Date()),
        sa.Column("schedule_status", sa.String(30), nullable=False),
        sa.CheckConstraint("scheduled_quantity > 0"),
        sa.UniqueConstraint("po_line_id", "source_schedule_key", "schedule_version"),
    )
    op.create_table(
        "supplier_commitment_observations",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "source_load_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_loads.id"),
            nullable=False,
        ),
        sa.Column(
            "po_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "delivery_schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("delivery_schedules.id"),
        ),
        sa.Column("source_commitment_ref", sa.String(120), nullable=False),
        sa.Column("committed_quantity", sa.Numeric(18, 4)),
        sa.Column("committed_date", sa.Date()),
        sa.Column("channel", sa.String(50)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "supersedes_commitment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplier_commitment_observations.id"),
        ),
        sa.UniqueConstraint("source_load_id", "source_commitment_ref"),
    )
    op.create_table(
        "receipt_transactions",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "source_system_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_systems.id"),
            nullable=False,
        ),
        sa.Column(
            "source_load_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_loads.id"),
            nullable=False,
        ),
        sa.Column(
            "po_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id"),
            nullable=False,
        ),
        sa.Column("receipt_document", sa.String(100), nullable=False),
        sa.Column("receipt_item_sequence", sa.String(80), nullable=False),
        sa.Column("transaction_type", sa.String(30), nullable=False),
        sa.Column("source_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("source_uom", sa.String(20), nullable=False),
        sa.Column("base_quantity", sa.Numeric(18, 4)),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "corrects_receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receipt_transactions.id"),
        ),
        sa.CheckConstraint("source_quantity <> 0"),
        sa.CheckConstraint("base_quantity is null or base_quantity <> 0"),
        sa.UniqueConstraint("source_system_id", "receipt_document", "receipt_item_sequence"),
    )
    op.create_table(
        "receipt_allocations",
        uuid_pk(),
        sa.Column(
            "receipt_transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receipt_transactions.id"),
            nullable=False,
        ),
        sa.Column(
            "delivery_schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("delivery_schedules.id"),
        ),
        sa.Column("allocation_sequence", sa.Integer(), nullable=False),
        sa.Column("allocation_bucket", sa.String(40), nullable=False),
        sa.Column("allocated_base_quantity", sa.Numeric(18, 4), nullable=False),
        sa.CheckConstraint("allocated_base_quantity >= 0"),
        sa.CheckConstraint(
            "delivery_schedule_id is not null or allocation_bucket = 'line_residual'"
        ),
        sa.UniqueConstraint("receipt_transaction_id", "allocation_sequence"),
    )
    op.create_table(
        "inventory_snapshots",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "source_load_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_loads.id"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False
        ),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("on_hand_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("allocated_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("available_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("in_transit_quantity", sa.Numeric(18, 4)),
        sa.Column(
            "corrects_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_snapshots.id"),
        ),
        sa.UniqueConstraint(
            "source_load_id", "product_id", "site_id", "snapshot_at", "snapshot_version"
        ),
    )
    op.create_table(
        "demand_requirements",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "source_load_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_loads.id"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False
        ),
        sa.Column("source_requirement_ref", sa.String(120), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.Column("requirement_type", sa.String(40), nullable=False),
        sa.Column("required_date", sa.Date(), nullable=False),
        sa.Column("required_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "corrects_requirement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("demand_requirements.id"),
        ),
        sa.CheckConstraint("required_quantity >= 0"),
        sa.UniqueConstraint("source_load_id", "source_requirement_ref", "requirement_version"),
    )
    op.create_table(
        "supplier_performance_snapshots",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id")),
        sa.Column("definition_version", sa.String(40), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("numerator_count", sa.Integer(), nullable=False),
        sa.Column("denominator_count", sa.Integer(), nullable=False),
        sa.Column("otif_rate", sa.Numeric(8, 4)),
        sa.Column(
            "sample_sufficient", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint("window_end > window_start"),
        sa.CheckConstraint("denominator_count >= 0"),
        sa.UniqueConstraint("supplier_id", "site_id", "window_start", "window_end", "as_of_date"),
    )
    op.create_table(
        "synthetic_outcome_observations",
        uuid_pk(),
        sa.Column(
            "po_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False
        ),
        sa.Column("outcome_window_start", sa.Date(), nullable=False),
        sa.Column("outcome_window_end", sa.Date(), nullable=False),
        sa.Column("generator_version", sa.String(40), nullable=False),
        sa.Column("seed_reference", sa.String(120), nullable=False),
        sa.Column(
            "outcome_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint(
            "po_line_id",
            "site_id",
            "outcome_window_start",
            "outcome_window_end",
            "generator_version",
        ),
    )


def _create_scoring_and_workflow_tables() -> None:
    """Create scoring and workflow tables."""

    op.create_table(
        "exception_episodes",
        uuid_pk(),
        sa.Column(
            "po_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False
        ),
        sa.Column("episode_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "opening_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipeline_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "predecessor_episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
        ),
        sa.Column("current_state", sa.String(30), nullable=False),
        sa.Column("calculated_severity", sa.String(20), nullable=False),
        sa.Column("effective_severity", sa.String(20), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "current_owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")
        ),
        sa.CheckConstraint(
            "current_state in ("
            "'open','assigned','investigating','action_agreed','monitoring',"
            "'resolved','suppressed','closed')"
        ),
        sa.CheckConstraint(
            "(current_state = 'closed' and closed_at is not null) "
            "or (current_state <> 'closed' and closed_at is null)"
        ),
        sa.CheckConstraint("predecessor_episode_id is null or predecessor_episode_id <> id"),
        sa.CheckConstraint("calculated_severity in ('monitor','low','medium','high','critical')"),
        sa.CheckConstraint("effective_severity in ('monitor','low','medium','high','critical')"),
        sa.CheckConstraint("episode_sequence > 0"),
        sa.UniqueConstraint("po_line_id", "site_id", "episode_sequence"),
    )
    op.create_table(
        "candidate_risk_evaluations",
        uuid_pk(),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipeline_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "po_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False
        ),
        sa.Column(
            "rule_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rule_versions.id"),
            nullable=False,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_fingerprint", sa.String(128), nullable=False),
        sa.Column("eligibility_status", sa.String(40), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("calculated_severity", sa.String(20), nullable=False),
        sa.Column("score_confidence", sa.String(30), nullable=False),
        sa.Column("disposition", sa.String(50), nullable=False),
        sa.Column(
            "linked_episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
        ),
        sa.Column("explanation_summary", sa.Text()),
        sa.Column(
            "missing_signal_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("score >= 0 and score <= 100"),
        sa.CheckConstraint("calculated_severity in ('monitor','low','medium','high','critical')"),
        sa.CheckConstraint(
            "disposition in ("
            "'below-opening-threshold','opened-new-episode','linked-existing-active-episode',"
            "'suppressed-by-existing-control','ineligible-after-validation',"
            "'manual-review-data-insufficient','scoring-error')"
        ),
        sa.UniqueConstraint("pipeline_run_id", "po_line_id", "site_id"),
    )
    op.add_column(
        "exception_episodes",
        sa.Column(
            "opening_candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_risk_evaluations.id"),
        ),
    )
    op.add_column(
        "exception_episodes",
        sa.Column(
            "current_candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_risk_evaluations.id"),
        ),
    )
    op.alter_column("exception_episodes", "opening_candidate_id", nullable=False)
    op.create_table(
        "candidate_risk_contributions",
        uuid_pk(),
        sa.Column(
            "candidate_evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_risk_evaluations.id"),
            nullable=False,
        ),
        sa.Column(
            "rule_component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rule_component_definitions.id"),
        ),
        sa.Column("component_code", sa.String(80), nullable=False),
        sa.Column("component_family", sa.String(80), nullable=False),
        sa.Column("availability_status", sa.String(30), nullable=False),
        sa.Column("observed_value", sa.String(160)),
        sa.Column("comparator", sa.String(20)),
        sa.Column("threshold_value", sa.String(80)),
        sa.Column("triggered", sa.Boolean(), nullable=False),
        sa.Column("gross_points", sa.Numeric(8, 2), nullable=False),
        sa.Column(
            "cap_adjustment",
            sa.Numeric(8, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("applied_points", sa.Numeric(8, 2), nullable=False),
        sa.Column("missing_signal_reason", sa.Text()),
        sa.Column("explanation_code", sa.String(80), nullable=False),
        sa.Column(
            "input_lineage",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "availability_status in ('available-not-triggered','triggered','unavailable','invalid')"
        ),
        sa.CheckConstraint("applied_points = gross_points + cap_adjustment"),
        sa.UniqueConstraint("candidate_evaluation_id", "component_code"),
    )
    _create_workflow_tables()


def _create_workflow_tables() -> None:
    """Create workflow detail tables."""

    op.create_table(
        "exception_event_envelopes",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("reason_code", sa.String(80)),
        sa.Column("reason_text", sa.Text()),
        sa.Column("correlation_id", sa.String(120)),
        sa.Column(
            "causation_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_event_envelopes.id"),
        ),
        sa.Column(
            "pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipeline_runs.id")
        ),
        sa.Column(
            "rule_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rule_versions.id")
        ),
        sa.Column(
            "calendar_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calendar_versions.id"),
        ),
        sa.Column("before_payload", postgresql.JSONB()),
        sa.Column("after_payload", postgresql.JSONB()),
        sa.CheckConstraint("event_sequence > 0"),
        sa.UniqueConstraint("episode_id", "event_sequence"),
        sa.UniqueConstraint("episode_id", "idempotency_key"),
    )
    op.create_table(
        "approval_requests",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column("request_reference", sa.String(120), nullable=False),
        sa.Column("request_type", sa.String(80), nullable=False),
        sa.Column(
            "requester_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "requested_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("episode_id", "request_reference"),
    )
    op.create_table(
        "suppression_controls",
        uuid_pk(),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column(
            "approval_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approval_requests.id"),
            nullable=False,
        ),
        sa.Column("prior_state", sa.String(30), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_at", sa.DateTime(timezone=True)),
        sa.Column(
            "recurrence_criteria",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sla_consumed_minutes_at_pause", sa.Integer()),
        sa.CheckConstraint(
            "prior_state in ('open','assigned','investigating','action_agreed','monitoring','resolved','suppressed')"
        ),
        sa.CheckConstraint("expires_at > starts_at"),
    )
    op.create_table(
        "resolution_records",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column("resolution_sequence", sa.Integer(), nullable=False),
        sa.Column("resolution_category", sa.String(80), nullable=False),
        sa.Column("cause_code", sa.String(80), nullable=False),
        sa.Column(
            "resolver_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("residual_risk_statement", sa.Text(), nullable=False),
        sa.Column("outcome_quantity", sa.Numeric(18, 4)),
        sa.Column("outcome_date", sa.DateTime(timezone=True)),
        sa.Column("monitoring_result", sa.Text()),
        sa.Column(
            "approval_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approval_requests.id"),
        ),
        sa.Column(
            "current_candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_risk_evaluations.id"),
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("resolution_sequence > 0"),
        sa.UniqueConstraint("episode_id", "resolution_sequence"),
    )
    op.create_table(
        "exception_state_events",
        uuid_pk(),
        sa.Column(
            "event_envelope_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_event_envelopes.id"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(30)),
        sa.Column("to_state", sa.String(30), nullable=False),
        sa.Column("transition_reason", sa.String(100), nullable=False),
        sa.Column("authority", sa.String(80), nullable=False),
        sa.Column(
            "resolution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resolution_records.id")
        ),
        sa.Column(
            "suppression_control_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppression_controls.id"),
        ),
        sa.CheckConstraint(
            "from_state is null or from_state in ("
            "'open','assigned','investigating','action_agreed','monitoring',"
            "'resolved','suppressed','closed')"
        ),
        sa.CheckConstraint(
            "to_state in ("
            "'open','assigned','investigating','action_agreed','monitoring',"
            "'resolved','suppressed','closed')"
        ),
        sa.CheckConstraint("(from_state is null and to_state = 'open') or from_state is not null"),
        sa.UniqueConstraint("event_envelope_id"),
    )
    op.create_table(
        "exception_actions",
        uuid_pk(),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column(
            "event_envelope_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_event_envelopes.id"),
            nullable=False,
        ),
        sa.Column("action_sequence", sa.Integer(), nullable=False),
        sa.Column("action_category", sa.String(80), nullable=False),
        sa.Column("action_status", sa.String(40), nullable=False),
        sa.Column("action_owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column(
            "action_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "supersedes_action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_actions.id"),
        ),
        sa.UniqueConstraint("episode_id", "action_sequence"),
    )
    op.create_table(
        "ownership_events",
        uuid_pk(),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column(
            "event_envelope_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_event_envelopes.id"),
            nullable=False,
        ),
        sa.Column("ownership_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "previous_owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")
        ),
        sa.Column("new_owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "ownership_mapping_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ownership_mappings.id"),
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("authority", sa.String(80), nullable=False),
        sa.UniqueConstraint("episode_id", "ownership_sequence"),
    )
    op.create_table(
        "sla_obligations",
        uuid_pk(),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column("sla_type", sa.String(60), nullable=False),
        sa.Column("obligation_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "calendar_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calendar_versions.id"),
            nullable=False,
        ),
        sa.Column("severity_basis", sa.String(20), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("satisfied_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("obligation_sequence > 0"),
        sa.UniqueConstraint("episode_id", "sla_type", "obligation_sequence"),
    )
    op.create_table(
        "sla_events",
        uuid_pk(),
        sa.Column(
            "sla_obligation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sla_obligations.id"),
            nullable=False,
        ),
        sa.Column(
            "event_envelope_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_event_envelopes.id"),
            nullable=False,
        ),
        sa.Column("sla_event_sequence", sa.Integer(), nullable=False),
        sa.Column("sla_event_type", sa.String(50), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("business_minutes_consumed", sa.Integer()),
        sa.Column(
            "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.UniqueConstraint("sla_obligation_id", "sla_event_sequence"),
    )
    op.create_table(
        "approval_decisions",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "approval_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approval_requests.id"),
            nullable=False,
        ),
        sa.Column("decision_role", sa.String(80), nullable=False),
        sa.Column(
            "approver_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("conditions", sa.Text()),
        sa.Column("independence_check_passed", sa.Boolean(), nullable=False),
        sa.CheckConstraint("outcome in ('approved','rejected','conditional','expired')"),
        sa.UniqueConstraint("approval_request_id", "decision_role"),
    )
    op.create_table(
        "evidence_references",
        uuid_pk(),
        recorded_at(),
        sa.Column("evidence_type", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("evidence_source", sa.String(80), nullable=False),
        sa.Column("external_reference", sa.String(180), nullable=False),
        sa.Column("evidence_version", sa.String(40), nullable=False),
        sa.Column("integrity_hash", sa.String(128)),
        sa.Column("availability_status", sa.String(30), nullable=False),
        sa.Column(
            "correction_of_evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence_references.id"),
        ),
        sa.CheckConstraint("availability_status in ('available','missing','broken','corrected')"),
        sa.UniqueConstraint("evidence_source", "external_reference", "evidence_version"),
    )
    op.create_table(
        "evidence_links",
        uuid_pk(),
        sa.Column(
            "evidence_reference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence_references.id"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_reason", sa.String(120)),
        sa.CheckConstraint(
            "target_type in ("
            "'event','action','approval_request','approval_decision','suppression_control',"
            "'resolution','receipt','source_correction')"
        ),
        sa.UniqueConstraint("evidence_reference_id", "target_type", "target_id"),
    )
    op.create_table(
        "episode_relationships",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "from_episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column(
            "to_episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(80), nullable=False),
        sa.Column("relationship_reason", sa.Text()),
        sa.CheckConstraint("from_episode_id <> to_episode_id"),
        sa.UniqueConstraint("from_episode_id", "to_episode_id", "relationship_type"),
    )
    op.create_table(
        "notification_events",
        uuid_pk(),
        recorded_at(),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_episodes.id"),
            nullable=False,
        ),
        sa.Column("notification_type", sa.String(80), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("recipient_queue", sa.String(120)),
        sa.Column(
            "trigger_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_event_envelopes.id"),
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_status", sa.String(30), nullable=False),
        sa.Column("provider_reference", sa.String(180)),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("failure_reason", sa.Text()),
        sa.CheckConstraint("attempt_number > 0"),
        sa.CheckConstraint(
            "delivery_status in ('requested','queued','sent','failed','cancelled','skipped')"
        ),
        sa.UniqueConstraint("episode_id", "idempotency_key"),
    )


def _create_postgresql_constraints() -> None:
    """Create PostgreSQL-specific indexes and exclusion constraints."""

    op.create_index(
        "uq_exception_episodes_active_line_site",
        "exception_episodes",
        ["po_line_id", "site_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    for table, cols in [
        ("supplier_versions", ["supplier_id"]),
        ("product_versions", ["product_id"]),
        ("product_site_inventory_policies", ["product_id", "site_id"]),
        ("ownership_mappings", ["precedence", "scope_type", "scope_key", "site_id"]),
        ("uom_conversions", ["product_id", "from_uom", "to_uom"]),
    ]:
        equality_terms = ", ".join(f"{col} WITH =" for col in cols)
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ex_{table}_no_overlap "
            f"EXCLUDE USING gist ({equality_terms}, "
            "tstzrange(effective_from, coalesce(effective_to, 'infinity'::timestamptz), '[)') WITH &&)"
        )
    op.create_index(
        "ix_candidate_risk_evaluations_episode", "candidate_risk_evaluations", ["linked_episode_id"]
    )
    op.create_index(
        "ix_exception_events_episode_sequence",
        "exception_event_envelopes",
        ["episode_id", "event_sequence"],
    )
    op.create_index(
        "ix_receipt_allocations_receipt", "receipt_allocations", ["receipt_transaction_id"]
    )
    _create_constraint_triggers()


def _create_constraint_triggers() -> None:
    """Create PostgreSQL constraint triggers for cross-table governance controls."""

    op.execute(
        """
        CREATE FUNCTION enforce_material_approval_independence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            request_user uuid;
            approval_type text;
        BEGIN
            SELECT requester_user_id, request_type
            INTO request_user, approval_type
            FROM approval_requests
            WHERE id = NEW.approval_request_id;

            IF approval_type IN (
                'suppression',
                'resolution',
                'severity_override',
                'material_recurrence',
                'closure'
            ) AND NEW.approver_user_id = request_user THEN
                RAISE EXCEPTION 'material approval cannot be self-approved'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_material_approval_independence
        AFTER INSERT OR UPDATE OF approval_request_id, approver_user_id
        ON approval_decisions
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW
        EXECUTE FUNCTION enforce_material_approval_independence();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_successor_predecessor_closed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            predecessor_state text;
            predecessor_closed_at timestamptz;
        BEGIN
            IF NEW.predecessor_episode_id IS NULL THEN
                RETURN NEW;
            END IF;

            IF NEW.predecessor_episode_id = NEW.id THEN
                RAISE EXCEPTION 'successor episode cannot reference itself as predecessor'
                    USING ERRCODE = '23514';
            END IF;

            SELECT current_state, closed_at
            INTO predecessor_state, predecessor_closed_at
            FROM exception_episodes
            WHERE id = NEW.predecessor_episode_id;

            IF predecessor_state <> 'closed' OR predecessor_closed_at IS NULL THEN
                RAISE EXCEPTION 'material recurrence predecessor must be formally closed'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_successor_predecessor_closed
        AFTER INSERT OR UPDATE OF predecessor_episode_id
        ON exception_episodes
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW
        EXECUTE FUNCTION enforce_successor_predecessor_closed();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_material_relationship_predecessor_closed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            predecessor_state text;
            predecessor_closed_at timestamptz;
        BEGIN
            IF NEW.relationship_type <> 'material_recurrence' THEN
                RETURN NEW;
            END IF;

            SELECT current_state, closed_at
            INTO predecessor_state, predecessor_closed_at
            FROM exception_episodes
            WHERE id = NEW.from_episode_id;

            IF predecessor_state <> 'closed' OR predecessor_closed_at IS NULL THEN
                RAISE EXCEPTION 'material recurrence relationship predecessor must be formally closed'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_material_relationship_predecessor_closed
        AFTER INSERT OR UPDATE OF from_episode_id, relationship_type
        ON episode_relationships
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW
        EXECUTE FUNCTION enforce_material_relationship_predecessor_closed();
        """
    )


def downgrade() -> None:
    """Drop the physical schema."""

    op.execute("DROP FUNCTION IF EXISTS enforce_material_relationship_predecessor_closed() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS enforce_successor_predecessor_closed() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS enforce_material_approval_independence() CASCADE")
    tables = [
        "notification_events",
        "episode_relationships",
        "evidence_links",
        "evidence_references",
        "approval_decisions",
        "sla_events",
        "sla_obligations",
        "ownership_events",
        "exception_actions",
        "exception_state_events",
        "resolution_records",
        "suppression_controls",
        "approval_requests",
        "exception_event_envelopes",
        "candidate_risk_contributions",
        "candidate_risk_evaluations",
        "exception_episodes",
        "synthetic_outcome_observations",
        "supplier_performance_snapshots",
        "demand_requirements",
        "inventory_snapshots",
        "receipt_allocations",
        "receipt_transactions",
        "supplier_commitment_observations",
        "delivery_schedules",
        "purchase_order_line_versions",
        "purchase_order_line_aliases",
        "purchase_order_lines",
        "purchase_order_versions",
        "purchase_orders",
        "analytics_publications",
        "reconciliation_results",
        "rejected_records",
        "pipeline_step_results",
        "source_loads",
        "uom_conversions",
        "rule_component_definitions",
        "ownership_mappings",
        "product_site_inventory_policies",
        "calendar_versions",
        "rule_versions",
        "product_versions",
        "supplier_versions",
        "users",
        "products",
        "suppliers",
        "sites",
        "pipeline_runs",
        "source_systems",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
