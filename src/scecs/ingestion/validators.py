"""Stage B validation for operational source bundles."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from scecs.ingestion.config import EVALUATION_ONLY_DATASETS, NON_OPERATIONAL_EVIDENCE_DATASETS, OPERATIONAL_DATASETS
from scecs.ingestion.contracts import Rejection, RejectionClass, SourceRecord


def validate_operational_scope(dataset_names: set[str]) -> list[Rejection]:
    """Validate evaluation-only and unapproved operational scope."""

    rejections: list[Rejection] = []
    missing = sorted(set(OPERATIONAL_DATASETS) - dataset_names)
    for dataset_name in missing:
        rejections.append(
            Rejection(dataset_name, None, "MISSING_OPERATIONAL_DATASET", dataset_name, RejectionClass.BUNDLE_BLOCKING)
        )
    leaked = sorted((dataset_names & EVALUATION_ONLY_DATASETS) | (dataset_names & NON_OPERATIONAL_EVIDENCE_DATASETS))
    for dataset_name in leaked:
        rejections.append(
            Rejection(dataset_name, None, "NON_OPERATIONAL_FILE_SKIPPED", dataset_name, RejectionClass.WARNING_ONLY)
        )
    return rejections


def validate_cross_dataset(records_by_dataset: dict[str, list[SourceRecord]], as_of: datetime) -> list[Rejection]:
    """Validate core referential, chronology, and reconciliation controls."""

    rejections: list[Rejection] = []
    ids = {name: {record.values["id"] for record in records} for name, records in records_by_dataset.items()}
    _require_fk(records_by_dataset, "purchase_orders", "source_system_id", ids["source_systems"], rejections)
    _require_fk(records_by_dataset, "source_loads", "source_system_id", ids["source_systems"], rejections)
    _require_fk(records_by_dataset, "supplier_versions", "supplier_id", ids["suppliers"], rejections)
    _require_fk(records_by_dataset, "product_versions", "product_id", ids["products"], rejections)
    _require_fk(records_by_dataset, "uom_conversions", "product_id", ids["products"], rejections)
    _require_fk(records_by_dataset, "product_site_inventory_policies", "product_id", ids["products"], rejections)
    _require_fk(records_by_dataset, "product_site_inventory_policies", "site_id", ids["sites"], rejections)
    _require_fk(records_by_dataset, "purchase_order_versions", "purchase_order_id", ids["purchase_orders"], rejections)
    _require_fk(records_by_dataset, "purchase_order_versions", "source_load_id", ids["source_loads"], rejections)
    _require_fk(records_by_dataset, "purchase_order_versions", "supplier_id", ids["suppliers"], rejections)
    _require_fk(records_by_dataset, "purchase_order_lines", "purchase_order_id", ids["purchase_orders"], rejections)
    _require_fk(
        records_by_dataset, "purchase_order_line_aliases", "po_line_id", ids["purchase_order_lines"], rejections
    )
    _require_fk(
        records_by_dataset, "purchase_order_line_aliases", "source_system_id", ids["source_systems"], rejections
    )
    _require_fk(
        records_by_dataset, "purchase_order_line_versions", "po_line_id", ids["purchase_order_lines"], rejections
    )
    _require_fk(records_by_dataset, "purchase_order_line_versions", "source_load_id", ids["source_loads"], rejections)
    _require_fk(records_by_dataset, "purchase_order_line_versions", "product_id", ids["products"], rejections)
    _require_fk(records_by_dataset, "purchase_order_line_versions", "site_id", ids["sites"], rejections)
    _require_fk(records_by_dataset, "delivery_schedules", "po_line_id", ids["purchase_order_lines"], rejections)
    _require_fk(
        records_by_dataset, "supplier_commitment_observations", "source_load_id", ids["source_loads"], rejections
    )
    _require_fk(
        records_by_dataset, "supplier_commitment_observations", "po_line_id", ids["purchase_order_lines"], rejections
    )
    _require_fk(records_by_dataset, "receipt_transactions", "source_system_id", ids["source_systems"], rejections)
    _require_fk(records_by_dataset, "receipt_transactions", "source_load_id", ids["source_loads"], rejections)
    _require_fk(records_by_dataset, "receipt_transactions", "po_line_id", ids["purchase_order_lines"], rejections)
    _require_fk(
        records_by_dataset, "receipt_allocations", "receipt_transaction_id", ids["receipt_transactions"], rejections
    )
    _require_fk(records_by_dataset, "inventory_snapshots", "source_load_id", ids["source_loads"], rejections)
    _require_fk(records_by_dataset, "inventory_snapshots", "product_id", ids["products"], rejections)
    _require_fk(records_by_dataset, "inventory_snapshots", "site_id", ids["sites"], rejections)
    _require_fk(records_by_dataset, "demand_requirements", "source_load_id", ids["source_loads"], rejections)
    _require_fk(records_by_dataset, "demand_requirements", "product_id", ids["products"], rejections)
    _require_fk(records_by_dataset, "demand_requirements", "site_id", ids["sites"], rejections)
    _require_fk(records_by_dataset, "supplier_performance_snapshots", "supplier_id", ids["suppliers"], rejections)

    _validate_not_after_as_of(records_by_dataset, as_of, rejections)
    _validate_one_supplier_per_po(records_by_dataset, rejections)
    _validate_schedule_line_reconciliation(records_by_dataset, rejections)
    _validate_receipt_allocations(records_by_dataset, rejections)
    _validate_commitment_schedule_consistency(records_by_dataset, rejections)
    return rejections


def has_blocking_rejections(rejections: list[Rejection]) -> bool:
    """Return whether any rejection blocks publication/loading."""

    return any(
        rejection.classification in {RejectionClass.BUNDLE_BLOCKING, RejectionClass.DATASET_BLOCKING}
        for rejection in rejections
    )


def _require_fk(
    records_by_dataset: dict[str, list[SourceRecord]],
    dataset_name: str,
    field_name: str,
    valid_ids: set[object],
    rejections: list[Rejection],
) -> None:
    for record in records_by_dataset.get(dataset_name, []):
        value = record.values.get(field_name)
        if value is not None and value not in valid_ids:
            rejections.append(
                Rejection(
                    dataset_name,
                    record.row_number,
                    "FOREIGN_KEY_MISSING",
                    f"{field_name} references missing id",
                    RejectionClass.DATASET_BLOCKING,
                    field_name,
                    str(value),
                    record.natural_key,
                )
            )


def _validate_not_after_as_of(
    records_by_dataset: dict[str, list[SourceRecord]],
    as_of: datetime,
    rejections: list[Rejection],
) -> None:
    timestamp_fields = {
        "source_loads": ("extracted_at", "received_at"),
        "purchase_order_versions": ("effective_at",),
        "purchase_order_line_aliases": ("valid_from",),
        "purchase_order_line_versions": ("effective_at",),
        "receipt_transactions": ("posted_at",),
        "supplier_commitment_observations": ("observed_at",),
        "inventory_snapshots": ("snapshot_at",),
    }
    for dataset_name, fields in timestamp_fields.items():
        for record in records_by_dataset.get(dataset_name, []):
            for field_name in fields:
                value = record.values.get(field_name)
                if isinstance(value, datetime) and value > as_of:
                    rejections.append(
                        Rejection(
                            dataset_name,
                            record.row_number,
                            "POST_AS_OF_OPERATIONAL_TIMESTAMP",
                            f"{field_name} is after as-of",
                            RejectionClass.DATASET_BLOCKING,
                            field_name,
                            value.isoformat(),
                            record.natural_key,
                        )
                    )


def _validate_one_supplier_per_po(
    records_by_dataset: dict[str, list[SourceRecord]], rejections: list[Rejection]
) -> None:
    suppliers_by_po: dict[object, set[object]] = defaultdict(set)
    for record in records_by_dataset.get("purchase_order_versions", []):
        suppliers_by_po[record.values["purchase_order_id"]].add(record.values["supplier_id"])
    for po_id, supplier_ids in suppliers_by_po.items():
        if len(supplier_ids) > 1:
            rejections.append(
                Rejection(
                    "purchase_order_versions",
                    None,
                    "MULTI_SUPPLIER_PO",
                    f"PO {po_id} has multiple suppliers",
                    RejectionClass.DATASET_BLOCKING,
                )
            )


def _validate_schedule_line_reconciliation(
    records_by_dataset: dict[str, list[SourceRecord]],
    rejections: list[Rejection],
) -> None:
    latest_line_versions: dict[object, SourceRecord] = {}
    for record in records_by_dataset.get("purchase_order_line_versions", []):
        current = latest_line_versions.get(record.values["po_line_id"])
        if current is None or int(str(record.values["amendment_version"])) > int(
            str(current.values["amendment_version"])
        ):
            latest_line_versions[record.values["po_line_id"]] = record
    schedule_totals: dict[object, Decimal] = defaultdict(lambda: Decimal("0"))
    for record in records_by_dataset.get("delivery_schedules", []):
        schedule_totals[record.values["po_line_id"]] += _decimal(record.values["scheduled_quantity"])
    for line_id, total in schedule_totals.items():
        line = latest_line_versions.get(line_id)
        if line is None:
            continue
        expected = _decimal(line.values["base_quantity"])
        if (total - expected).quantize(Decimal("0.0001")) != Decimal("0.0000"):
            rejections.append(
                Rejection(
                    "delivery_schedules",
                    None,
                    "SCHEDULE_LINE_QUANTITY_MISMATCH",
                    f"{line_id}: {total} != {expected}",
                    RejectionClass.DATASET_BLOCKING,
                )
            )


def _validate_receipt_allocations(
    records_by_dataset: dict[str, list[SourceRecord]], rejections: list[Rejection]
) -> None:
    receipts = {record.values["id"]: record for record in records_by_dataset.get("receipt_transactions", [])}
    schedules = {record.values["id"]: record for record in records_by_dataset.get("delivery_schedules", [])}
    totals: dict[object, Decimal] = defaultdict(lambda: Decimal("0"))
    for record in records_by_dataset.get("receipt_allocations", []):
        receipt = receipts.get(record.values["receipt_transaction_id"])
        if receipt is None:
            continue
        schedule_id = record.values.get("delivery_schedule_id")
        if record.values["allocation_bucket"] == "line_residual" and schedule_id is not None:
            rejections.append(
                Rejection(
                    "receipt_allocations",
                    record.row_number,
                    "LINE_RESIDUAL_HAS_SCHEDULE",
                    "Line residual allocation has schedule",
                    RejectionClass.DATASET_BLOCKING,
                    "delivery_schedule_id",
                    str(schedule_id),
                    record.natural_key,
                )
            )
        if record.values["allocation_bucket"] != "line_residual" and schedule_id is None:
            rejections.append(
                Rejection(
                    "receipt_allocations",
                    record.row_number,
                    "SCHEDULE_BUCKET_MISSING_SCHEDULE",
                    "Schedule allocation missing schedule",
                    RejectionClass.DATASET_BLOCKING,
                    "delivery_schedule_id",
                    None,
                    record.natural_key,
                )
            )
        if schedule_id is not None and schedules.get(schedule_id) is not None:
            if schedules[schedule_id].values["po_line_id"] != receipt.values["po_line_id"]:
                rejections.append(
                    Rejection(
                        "receipt_allocations",
                        record.row_number,
                        "RECEIPT_SCHEDULE_LINE_MISMATCH",
                        "Receipt and schedule belong to different PO lines",
                        RejectionClass.DATASET_BLOCKING,
                        "delivery_schedule_id",
                        str(schedule_id),
                        record.natural_key,
                    )
                )
        totals[record.values["receipt_transaction_id"]] += _decimal(record.values["allocated_base_quantity"])
    for receipt_id, receipt in receipts.items():
        expected = abs(_decimal(receipt.values["base_quantity"]))
        actual = totals[receipt_id]
        if (actual - expected).quantize(Decimal("0.0001")) != Decimal("0.0000"):
            rejections.append(
                Rejection(
                    "receipt_allocations",
                    None,
                    "RECEIPT_ALLOCATION_MISMATCH",
                    f"{receipt_id}: {actual} != {expected}",
                    RejectionClass.DATASET_BLOCKING,
                )
            )


def _validate_commitment_schedule_consistency(
    records_by_dataset: dict[str, list[SourceRecord]],
    rejections: list[Rejection],
) -> None:
    schedules = {record.values["id"]: record for record in records_by_dataset.get("delivery_schedules", [])}
    for record in records_by_dataset.get("supplier_commitment_observations", []):
        schedule_id = record.values.get("delivery_schedule_id")
        if schedule_id is not None and schedule_id in schedules:
            if schedules[schedule_id].values["po_line_id"] != record.values["po_line_id"]:
                rejections.append(
                    Rejection(
                        "supplier_commitment_observations",
                        record.row_number,
                        "COMMITMENT_SCHEDULE_LINE_MISMATCH",
                        "Commitment and schedule belong to different PO lines",
                        RejectionClass.DATASET_BLOCKING,
                        "delivery_schedule_id",
                        str(schedule_id),
                        record.natural_key,
                    )
                )


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
