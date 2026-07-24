"""Typed source contracts for generated operational CSV files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Final
from uuid import UUID


class RejectionClass(str, Enum):
    """Governed rejection classification."""

    BUNDLE_BLOCKING = "bundle-blocking"
    DATASET_BLOCKING = "dataset-blocking"
    RECORD_REJECTABLE = "record-rejectable"
    WARNING_ONLY = "warning-only"


@dataclass(frozen=True)
class Rejection:
    """One validation failure or warning."""

    dataset_name: str
    row_number: int | None
    code: str
    message: str
    classification: RejectionClass
    field_name: str | None = None
    rejected_value: str | None = None
    natural_key: str | None = None


@dataclass(frozen=True)
class SourceRecord:
    """Typed ingestion boundary for one parsed source row."""

    dataset_name: str
    row_number: int
    values: dict[str, object]
    natural_key: str
    raw_fingerprint: str


@dataclass(frozen=True)
class DatasetContract:
    """Expected source columns and lightweight type controls."""

    dataset_name: str
    required_columns: frozenset[str]
    optional_columns: frozenset[str] = frozenset()

    @property
    def allowed_columns(self) -> frozenset[str]:
        """Return required plus optional columns."""

        return self.required_columns | self.optional_columns


UUID_COLUMNS: Final = frozenset(
    {
        "id",
        "source_system_id",
        "pipeline_run_id",
        "source_load_id",
        "supplier_id",
        "product_id",
        "site_id",
        "owner_user_id",
        "rule_version_id",
        "purchase_order_id",
        "po_line_id",
        "delivery_schedule_id",
        "receipt_transaction_id",
        "corrects_receipt_id",
        "corrects_snapshot_id",
        "corrects_requirement_id",
        "supersedes_commitment_id",
    }
)
DATE_COLUMNS: Final = frozenset(
    {
        "order_date",
        "need_date",
        "requested_date",
        "confirmed_date",
        "expected_date",
        "committed_date",
        "required_date",
        "window_start",
        "window_end",
        "as_of_date",
    }
)
TIMESTAMP_COLUMNS: Final = frozenset(
    {
        "started_at",
        "finished_at",
        "extracted_at",
        "received_at",
        "active_from",
        "active_to",
        "effective_from",
        "effective_to",
        "approved_at",
        "effective_at",
        "valid_from",
        "valid_to",
        "observed_at",
        "posted_at",
        "snapshot_at",
    }
)
DECIMAL_COLUMNS: Final = frozenset(
    {
        "safety_stock_quantity",
        "conversion_factor",
        "ordered_quantity",
        "base_quantity",
        "scheduled_quantity",
        "committed_quantity",
        "source_quantity",
        "allocated_base_quantity",
        "on_hand_quantity",
        "allocated_quantity",
        "available_quantity",
        "in_transit_quantity",
        "required_quantity",
        "otif_rate",
    }
)
INTEGER_COLUMNS: Final = frozenset(
    {
        "row_count",
        "seed",
        "precedence",
        "handling_precision",
        "amendment_version",
        "schedule_version",
        "allocation_sequence",
        "snapshot_version",
        "requirement_version",
        "numerator_count",
        "denominator_count",
    }
)
BOOLEAN_COLUMNS: Final = frozenset(
    {
        "is_active",
        "is_publication_eligible",
        "sample_sufficient",
    }
)
JSON_COLUMNS: Final = frozenset({"business_hours", "holiday_set"})

ALLOWED_VALUES: Final[dict[str, frozenset[str]]] = {
    "order_status": frozenset({"open", "closed", "cancelled", "on_hold"}),
    "line_status": frozenset({"open", "closed", "cancelled", "on_hold"}),
    "actor_type": frozenset({"human", "system", "queue"}),
    "status": frozenset(
        {"draft", "approved", "active", "retired", "pending", "running", "success", "failed", "cancelled"}
    ),
    "transaction_type": frozenset({"receipt", "correction", "reversal"}),
    "allocation_bucket": frozenset({"schedule", "line_residual"}),
}


def build_contracts() -> dict[str, DatasetContract]:
    """Return explicit contracts for all operational datasets."""

    return {
        "source_systems": DatasetContract(
            "source_systems", frozenset({"id", "source_code", "display_name", "source_type", "is_active"})
        ),
        "source_loads": DatasetContract(
            "source_loads",
            frozenset(
                {
                    "id",
                    "pipeline_run_id",
                    "source_system_id",
                    "dataset_type",
                    "object_ref",
                    "content_hash",
                    "schema_version",
                    "extracted_at",
                    "received_at",
                    "row_count",
                }
            ),
        ),
        "sites": DatasetContract(
            "sites",
            frozenset({"id", "site_code", "site_name", "state_code", "timezone_name", "active_from", "active_to"}),
            frozenset({"synthetic_data_flag"}),
        ),
        "suppliers": DatasetContract(
            "suppliers", frozenset({"id", "supplier_code"}), frozenset({"synthetic_data_flag"})
        ),
        "supplier_versions": DatasetContract(
            "supplier_versions",
            frozenset({"id", "supplier_id", "display_name", "supplier_category", "effective_from", "effective_to"}),
            frozenset({"synthetic_data_flag"}),
        ),
        "products": DatasetContract("products", frozenset({"id", "sku"}), frozenset({"synthetic_data_flag"})),
        "product_versions": DatasetContract(
            "product_versions",
            frozenset(
                {
                    "id",
                    "product_id",
                    "description",
                    "category",
                    "base_uom",
                    "handling_precision",
                    "effective_from",
                    "effective_to",
                }
            ),
            frozenset({"abc_class", "xyz_class", "synthetic_data_flag"}),
        ),
        "uom_conversions": DatasetContract(
            "uom_conversions",
            frozenset(
                {"id", "product_id", "from_uom", "to_uom", "conversion_factor", "effective_from", "effective_to"}
            ),
        ),
        "product_site_inventory_policies": DatasetContract(
            "product_site_inventory_policies",
            frozenset(
                {
                    "id",
                    "product_id",
                    "site_id",
                    "safety_stock_quantity",
                    "policy_source",
                    "substitution_group",
                    "effective_from",
                    "effective_to",
                }
            ),
            frozenset({"criticality"}),
        ),
        "users": DatasetContract(
            "users",
            frozenset(
                {"id", "user_code", "display_name", "role_classification", "actor_type", "active_from", "active_to"}
            ),
            frozenset({"synthetic_data_flag"}),
        ),
        "ownership_mappings": DatasetContract(
            "ownership_mappings",
            frozenset(
                {
                    "id",
                    "precedence",
                    "scope_type",
                    "scope_key",
                    "site_id",
                    "owner_user_id",
                    "owner_queue_code",
                    "approval_reference",
                    "evidence_reference",
                    "effective_from",
                    "effective_to",
                }
            ),
            frozenset({"synthetic_data_flag"}),
        ),
        "calendar_versions": DatasetContract(
            "calendar_versions",
            frozenset(
                {"id", "calendar_code", "version", "timezone_name", "business_hours", "holiday_set", "approved_at"}
            ),
        ),
        "rule_versions": DatasetContract(
            "rule_versions",
            frozenset(
                {
                    "id",
                    "rule_code",
                    "version",
                    "status",
                    "owner",
                    "rationale",
                    "approved_at",
                    "effective_from",
                    "effective_to",
                }
            ),
        ),
        "purchase_orders": DatasetContract(
            "purchase_orders", frozenset({"id", "source_system_id", "po_number"}), frozenset({"synthetic_data_flag"})
        ),
        "purchase_order_versions": DatasetContract(
            "purchase_order_versions",
            frozenset(
                {
                    "id",
                    "purchase_order_id",
                    "source_load_id",
                    "supplier_id",
                    "amendment_version",
                    "buyer_group",
                    "currency_code",
                    "order_date",
                    "order_status",
                    "effective_at",
                }
            ),
        ),
        "purchase_order_lines": DatasetContract(
            "purchase_order_lines",
            frozenset({"id", "purchase_order_id", "canonical_line_key"}),
            frozenset({"synthetic_data_flag"}),
        ),
        "purchase_order_line_aliases": DatasetContract(
            "purchase_order_line_aliases",
            frozenset(
                {
                    "id",
                    "po_line_id",
                    "source_system_id",
                    "source_po_number",
                    "source_line_number",
                    "valid_from",
                    "valid_to",
                    "correction_reason",
                }
            ),
        ),
        "purchase_order_line_versions": DatasetContract(
            "purchase_order_line_versions",
            frozenset(
                {
                    "id",
                    "po_line_id",
                    "source_load_id",
                    "product_id",
                    "site_id",
                    "amendment_version",
                    "ordered_quantity",
                    "order_uom",
                    "base_quantity",
                    "need_date",
                    "requested_date",
                    "line_status",
                    "effective_at",
                }
            ),
            frozenset(
                {
                    "po_supplier_id",
                    "unit_price_aud",
                    "line_value_aud",
                    "scenario_ids",
                    "scenario_types",
                    "critical_order_flag",
                }
            ),
        ),
        "delivery_schedules": DatasetContract(
            "delivery_schedules",
            frozenset(
                {
                    "id",
                    "po_line_id",
                    "source_schedule_key",
                    "schedule_version",
                    "scheduled_quantity",
                    "requested_date",
                    "confirmed_date",
                    "expected_date",
                    "schedule_status",
                }
            ),
            frozenset({"scenario_ids", "scenario_types"}),
        ),
        "supplier_commitment_observations": DatasetContract(
            "supplier_commitment_observations",
            frozenset(
                {
                    "id",
                    "source_load_id",
                    "po_line_id",
                    "delivery_schedule_id",
                    "source_commitment_ref",
                    "committed_quantity",
                    "committed_date",
                    "channel",
                    "observed_at",
                    "supersedes_commitment_id",
                }
            ),
            frozenset({"scenario_ids", "scenario_types"}),
        ),
        "receipt_transactions": DatasetContract(
            "receipt_transactions",
            frozenset(
                {
                    "id",
                    "source_system_id",
                    "source_load_id",
                    "po_line_id",
                    "receipt_document",
                    "receipt_item_sequence",
                    "transaction_type",
                    "source_quantity",
                    "source_uom",
                    "base_quantity",
                    "posted_at",
                    "corrects_receipt_id",
                }
            ),
            frozenset({"late_receipt_flag", "scenario_ids", "scenario_types"}),
        ),
        "receipt_allocations": DatasetContract(
            "receipt_allocations",
            frozenset(
                {
                    "id",
                    "receipt_transaction_id",
                    "delivery_schedule_id",
                    "allocation_sequence",
                    "allocation_bucket",
                    "allocated_base_quantity",
                }
            ),
            frozenset({"po_line_id_for_validation", "corrected_receipt_id", "scenario_ids", "scenario_types"}),
        ),
        "inventory_snapshots": DatasetContract(
            "inventory_snapshots",
            frozenset(
                {
                    "id",
                    "source_load_id",
                    "product_id",
                    "site_id",
                    "snapshot_at",
                    "snapshot_version",
                    "on_hand_quantity",
                    "allocated_quantity",
                    "available_quantity",
                    "in_transit_quantity",
                    "corrects_snapshot_id",
                }
            ),
            frozenset({"missing_signal_flag", "scenario_ids", "scenario_types"}),
        ),
        "demand_requirements": DatasetContract(
            "demand_requirements",
            frozenset(
                {
                    "id",
                    "source_load_id",
                    "product_id",
                    "site_id",
                    "source_requirement_ref",
                    "requirement_version",
                    "requirement_type",
                    "required_date",
                    "required_quantity",
                    "corrects_requirement_id",
                }
            ),
            frozenset({"demand_class", "product_category", "demand_shock_flag", "scenario_ids", "scenario_types"}),
        ),
        "supplier_performance_snapshots": DatasetContract(
            "supplier_performance_snapshots",
            frozenset(
                {
                    "id",
                    "supplier_id",
                    "site_id",
                    "definition_version",
                    "window_start",
                    "window_end",
                    "as_of_date",
                    "numerator_count",
                    "denominator_count",
                    "otif_rate",
                    "sample_sufficient",
                }
            ),
        ),
    }


def parse_value(field_name: str, raw_value: str) -> object:
    """Parse one source value according to the governed column type."""

    value = raw_value.strip()
    if value == "":
        return None
    if field_name in UUID_COLUMNS or field_name.endswith("_id"):
        return UUID(value)
    if field_name in DATE_COLUMNS:
        return date.fromisoformat(value)
    if field_name in TIMESTAMP_COLUMNS:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return parsed.astimezone(UTC)
    if field_name in DECIMAL_COLUMNS:
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid decimal") from exc
    if field_name in INTEGER_COLUMNS:
        return int(value)
    if field_name in BOOLEAN_COLUMNS:
        if value.lower() in {"true", "1"}:
            return True
        if value.lower() in {"false", "0"}:
            return False
        raise ValueError("invalid boolean")
    if field_name in JSON_COLUMNS:
        parsed_json = json.loads(value)
        if not isinstance(parsed_json, dict):
            raise ValueError("JSON field must contain an object")
        return parsed_json
    return value


def validate_allowed_value(field_name: str, value: object) -> None:
    """Raise when a controlled code value is not allowed."""

    allowed = ALLOWED_VALUES.get(field_name)
    if allowed is not None and value is not None and str(value) not in allowed:
        raise ValueError(f"{field_name} must be one of {', '.join(sorted(allowed))}")
