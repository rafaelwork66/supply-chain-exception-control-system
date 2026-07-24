"""Master and reference data tables for the physical schema."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scecs.models.base import Base, UuidPrimaryKeyMixin


class Site(UuidPrimaryKeyMixin, Base):
    """Receiving or operating site identity."""

    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("site_code"),)

    site_code: Mapped[str] = mapped_column(String(40), nullable=False)
    site_name: Mapped[str] = mapped_column(String(120), nullable=False)
    state_code: Mapped[str] = mapped_column(String(10), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(80), nullable=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Supplier(UuidPrimaryKeyMixin, Base):
    """Durable supplier identity."""

    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("supplier_code"),)

    supplier_code: Mapped[str] = mapped_column(String(60), nullable=False)


class SupplierVersion(UuidPrimaryKeyMixin, Base):
    """Effective-dated supplier attributes."""

    __tablename__ = "supplier_versions"
    __table_args__ = (
        UniqueConstraint("supplier_id", "effective_from"),
        CheckConstraint(
            "effective_to is null or effective_to > effective_from", name="valid_interval"
        ),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    supplier_category: Mapped[str | None] = mapped_column(String(80))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(UuidPrimaryKeyMixin, Base):
    """Durable product/SKU identity."""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("sku"),)

    sku: Mapped[str] = mapped_column(String(80), nullable=False)


class ProductVersion(UuidPrimaryKeyMixin, Base):
    """Effective-dated product attributes and base UOM."""

    __tablename__ = "product_versions"
    __table_args__ = (
        UniqueConstraint("product_id", "effective_from"),
        CheckConstraint(
            "effective_to is null or effective_to > effective_from", name="valid_interval"
        ),
        CheckConstraint("handling_precision >= 0", name="nonnegative_handling_precision"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    base_uom: Mapped[str] = mapped_column(String(20), nullable=False)
    handling_precision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductSiteInventoryPolicy(UuidPrimaryKeyMixin, Base):
    """Effective-dated product/site inventory policy."""

    __tablename__ = "product_site_inventory_policies"
    __table_args__ = (
        UniqueConstraint("product_id", "site_id", "effective_from"),
        CheckConstraint(
            "effective_to is null or effective_to > effective_from", name="valid_interval"
        ),
        CheckConstraint("safety_stock_quantity >= 0", name="nonnegative_safety_stock"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False)
    safety_stock_quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    criticality: Mapped[str | None] = mapped_column(String(40))
    policy_source: Mapped[str] = mapped_column(String(80), nullable=False)
    substitution_group: Mapped[str | None] = mapped_column(String(80))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(UuidPrimaryKeyMixin, Base):
    """Synthetic employee or system actor identity without authentication secrets."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("user_code"),
        CheckConstraint("actor_type in ('human','system','queue')", name="actor_type"),
    )

    user_code: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    role_classification: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OwnershipMapping(UuidPrimaryKeyMixin, Base):
    """Effective-dated owner assignment rule."""

    __tablename__ = "ownership_mappings"
    __table_args__ = (
        UniqueConstraint("precedence", "scope_type", "scope_key", "site_id", "effective_from"),
        CheckConstraint(
            "effective_to is null or effective_to > effective_from", name="valid_interval"
        ),
    )

    precedence: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    owner_queue_code: Mapped[str | None] = mapped_column(String(80))
    approval_reference: Mapped[str | None] = mapped_column(String(160))
    evidence_reference: Mapped[str | None] = mapped_column(String(160))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RuleVersion(UuidPrimaryKeyMixin, Base):
    """Immutable approved scoring-rule package version."""

    __tablename__ = "rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_code", "version"),
        CheckConstraint("status in ('draft','approved','active','retired')", name="status"),
    )

    rule_code: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RuleComponentDefinition(UuidPrimaryKeyMixin, Base):
    """Rule component definition under a scoring-rule package."""

    __tablename__ = "rule_component_definitions"
    __table_args__ = (UniqueConstraint("rule_version_id", "component_code"),)

    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule_versions.id"), nullable=False
    )
    component_code: Mapped[str] = mapped_column(String(80), nullable=False)
    component_family: Mapped[str] = mapped_column(String(80), nullable=False)
    max_points: Mapped[float | None] = mapped_column(Numeric(8, 2))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class CalendarVersion(UuidPrimaryKeyMixin, Base):
    """Immutable business-calendar version for SLA obligations."""

    __tablename__ = "calendar_versions"
    __table_args__ = (UniqueConstraint("calendar_code", "version"),)

    calendar_code: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(80), nullable=False)
    business_hours: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    holiday_set: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UomConversion(UuidPrimaryKeyMixin, Base):
    """Effective product-specific conversion to the product base UOM."""

    __tablename__ = "uom_conversions"
    __table_args__ = (
        UniqueConstraint("product_id", "from_uom", "to_uom", "effective_from"),
        CheckConstraint(
            "conversion_factor > 0 and conversion_factor = trunc(conversion_factor)",
            name="positive_integral_conversion_factor",
        ),
        CheckConstraint(
            "effective_to is null or effective_to > effective_from", name="valid_interval"
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    from_uom: Mapped[str] = mapped_column(String(20), nullable=False)
    to_uom: Mapped[str] = mapped_column(String(20), nullable=False)
    conversion_factor: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
