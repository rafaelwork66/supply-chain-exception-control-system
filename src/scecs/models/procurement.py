"""Procurement and supply observation tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scecs.models.base import Base, RecordedTimestampMixin, UuidPrimaryKeyMixin


class PurchaseOrder(UuidPrimaryKeyMixin, Base):
    """Durable purchase-order header identity."""

    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("source_system_id", "po_number"),)

    source_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_systems.id"), nullable=False
    )
    po_number: Mapped[str] = mapped_column(String(80), nullable=False)


class PurchaseOrderVersion(UuidPrimaryKeyMixin, Base):
    """Versioned purchase-order header facts."""

    __tablename__ = "purchase_order_versions"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "amendment_version"),
        CheckConstraint(
            "order_status in ('open','closed','cancelled','on_hold')", name="order_status"
        ),
    )

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False
    )
    source_load_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_loads.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    amendment_version: Mapped[int] = mapped_column(nullable=False)
    buyer_group: Mapped[str | None] = mapped_column(String(80))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    order_date: Mapped[date] = mapped_column(nullable=False)
    order_status: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PurchaseOrderLine(UuidPrimaryKeyMixin, Base):
    """Canonical purchase-order line identity independent of mutable source keys."""

    __tablename__ = "purchase_order_lines"
    __table_args__ = (UniqueConstraint("canonical_line_key"),)

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False
    )
    canonical_line_key: Mapped[str] = mapped_column(String(120), nullable=False)


class PurchaseOrderLineAlias(UuidPrimaryKeyMixin, Base):
    """Source-key alias and correction history for a canonical PO line."""

    __tablename__ = "purchase_order_line_aliases"
    __table_args__ = (
        UniqueConstraint("source_system_id", "source_po_number", "source_line_number"),
    )

    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id"), nullable=False
    )
    source_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_systems.id"), nullable=False
    )
    source_po_number: Mapped[str] = mapped_column(String(80), nullable=False)
    source_line_number: Mapped[str] = mapped_column(String(80), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correction_reason: Mapped[str | None] = mapped_column(String(160))


class PurchaseOrderLineVersion(UuidPrimaryKeyMixin, Base):
    """Versioned purchase-order line facts."""

    __tablename__ = "purchase_order_line_versions"
    __table_args__ = (
        UniqueConstraint("po_line_id", "amendment_version"),
        CheckConstraint("ordered_quantity > 0", name="positive_ordered_quantity"),
        CheckConstraint(
            "line_status in ('open','closed','cancelled','on_hold')", name="line_status"
        ),
    )

    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id"), nullable=False
    )
    source_load_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_loads.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False)
    amendment_version: Mapped[int] = mapped_column(nullable=False)
    ordered_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    order_uom: Mapped[str] = mapped_column(String(20), nullable=False)
    base_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4))
    unit_price_aud: Mapped[float | None] = mapped_column(Numeric(18, 2))
    line_value_aud: Mapped[float | None] = mapped_column(Numeric(18, 2))
    need_date: Mapped[date] = mapped_column(nullable=False)
    requested_date: Mapped[date | None] = mapped_column()
    line_status: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DeliverySchedule(UuidPrimaryKeyMixin, Base):
    """Delivery schedule component for a purchase-order line."""

    __tablename__ = "delivery_schedules"
    __table_args__ = (
        UniqueConstraint("po_line_id", "source_schedule_key", "schedule_version"),
        CheckConstraint("scheduled_quantity > 0", name="positive_scheduled_quantity"),
    )

    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id"), nullable=False
    )
    source_schedule_key: Mapped[str] = mapped_column(String(100), nullable=False)
    schedule_version: Mapped[int] = mapped_column(nullable=False)
    scheduled_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    requested_date: Mapped[date | None] = mapped_column()
    confirmed_date: Mapped[date | None] = mapped_column()
    expected_date: Mapped[date | None] = mapped_column()
    schedule_status: Mapped[str] = mapped_column(String(30), nullable=False)


class SupplierCommitmentObservation(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Supplier confirmation or commitment observation."""

    __tablename__ = "supplier_commitment_observations"
    __table_args__ = (UniqueConstraint("source_load_id", "source_commitment_ref"),)

    source_load_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_loads.id"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id"), nullable=False
    )
    delivery_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("delivery_schedules.id")
    )
    source_commitment_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    committed_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4))
    committed_date: Mapped[date | None] = mapped_column()
    channel: Mapped[str | None] = mapped_column(String(50))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supersedes_commitment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("supplier_commitment_observations.id")
    )


class ReceiptTransaction(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Receipt, correction, or reversal transaction."""

    __tablename__ = "receipt_transactions"
    __table_args__ = (
        UniqueConstraint("source_system_id", "receipt_document", "receipt_item_sequence"),
        CheckConstraint("source_quantity <> 0", name="nonzero_source_quantity"),
        CheckConstraint(
            "base_quantity is null or base_quantity <> 0", name="nonzero_base_quantity"
        ),
    )

    source_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_systems.id"), nullable=False
    )
    source_load_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_loads.id"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id"), nullable=False
    )
    receipt_document: Mapped[str] = mapped_column(String(100), nullable=False)
    receipt_item_sequence: Mapped[str] = mapped_column(String(80), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    source_uom: Mapped[str] = mapped_column(String(20), nullable=False)
    base_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    corrects_receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("receipt_transactions.id")
    )


class ReceiptAllocation(UuidPrimaryKeyMixin, Base):
    """Application of receipt quantity to a schedule or line-level residual bucket."""

    __tablename__ = "receipt_allocations"
    __table_args__ = (
        UniqueConstraint("receipt_transaction_id", "allocation_sequence"),
        CheckConstraint("allocated_base_quantity >= 0", name="nonnegative_allocated_base_quantity"),
        CheckConstraint(
            "(allocation_bucket = 'line_residual' and delivery_schedule_id is null) "
            "or (allocation_bucket <> 'line_residual' and delivery_schedule_id is not null)",
            name="schedule_or_line_residual_bucket",
        ),
    )

    receipt_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipt_transactions.id"),
        nullable=False,
    )
    delivery_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("delivery_schedules.id")
    )
    allocation_sequence: Mapped[int] = mapped_column(nullable=False)
    allocation_bucket: Mapped[str] = mapped_column(String(40), nullable=False)
    allocated_base_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)


class InventorySnapshot(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Product/site inventory observation at a point in time."""

    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_load_id", "product_id", "site_id", "snapshot_at", "snapshot_version"
        ),
    )

    source_load_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_loads.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(nullable=False)
    on_hand_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    allocated_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    available_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    in_transit_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4))
    corrects_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_snapshots.id")
    )


class DemandRequirement(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Dated product/site demand requirement."""

    __tablename__ = "demand_requirements"
    __table_args__ = (
        UniqueConstraint("source_load_id", "source_requirement_ref", "requirement_version"),
        CheckConstraint("required_quantity >= 0", name="nonnegative_required_quantity"),
    )

    source_load_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_loads.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False)
    source_requirement_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    requirement_version: Mapped[int] = mapped_column(nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    required_date: Mapped[date] = mapped_column(nullable=False)
    required_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    corrects_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("demand_requirements.id")
    )


class SupplierPerformanceSnapshot(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Supplier performance observation for an approved measurement window."""

    __tablename__ = "supplier_performance_snapshots"
    __table_args__ = (
        UniqueConstraint("supplier_id", "site_id", "window_start", "window_end", "as_of_date"),
        CheckConstraint("window_end > window_start", name="valid_window"),
        CheckConstraint("denominator_count >= 0", name="nonnegative_denominator_count"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id"))
    definition_version: Mapped[str] = mapped_column(String(40), nullable=False)
    window_start: Mapped[date] = mapped_column(nullable=False)
    window_end: Mapped[date] = mapped_column(nullable=False)
    as_of_date: Mapped[date] = mapped_column(nullable=False)
    numerator_count: Mapped[int] = mapped_column(nullable=False)
    denominator_count: Mapped[int] = mapped_column(nullable=False)
    otif_rate: Mapped[float | None] = mapped_column(Numeric(8, 4))
    sample_sufficient: Mapped[bool] = mapped_column(nullable=False, default=False)


class SyntheticOutcomeObservation(UuidPrimaryKeyMixin, Base):
    """Independent hidden outcome observation separated from scoring inputs."""

    __tablename__ = "synthetic_outcome_observations"
    __table_args__ = (
        UniqueConstraint(
            "po_line_id",
            "site_id",
            "outcome_window_start",
            "outcome_window_end",
            "generator_version",
        ),
    )

    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False)
    outcome_window_start: Mapped[date] = mapped_column(nullable=False)
    outcome_window_end: Mapped[date] = mapped_column(nullable=False)
    generator_version: Mapped[str] = mapped_column(String(40), nullable=False)
    seed_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    outcome_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
