"""Validation and quality-summary controls for synthetic datasets."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.types import DatasetMap, Record


@dataclass(frozen=True)
class ValidationResult:
    """Validation result with blocking errors and measured controls."""

    passed: bool
    errors: list[str]
    summary: dict[str, Any]


def validate_dataset_bundle(datasets: DatasetMap, config: SyntheticGeneratorConfig) -> ValidationResult:
    """Validate key consistency, reconciliation and synthetic safety controls."""

    errors: list[str] = []
    summary: dict[str, Any] = {"row_counts": {name: len(rows) for name, rows in sorted(datasets.items())}}

    _validate_unique(datasets, "purchase_order_lines", "canonical_line_key", errors)
    _validate_unique(datasets, "suppliers", "supplier_code", errors)
    _validate_unique(datasets, "products", "sku", errors)

    line_by_id = {str(row["id"]): row for row in datasets["purchase_order_lines"]}
    schedule_by_id = {str(row["id"]): row for row in datasets["delivery_schedules"]}
    receipt_by_id = {str(row["id"]): row for row in datasets["receipt_transactions"]}

    final_line_versions = _final_line_versions(datasets["purchase_order_line_versions"])
    active_lines = [row for row in final_line_versions.values() if str(row["line_status"]) in {"open", "on_hold"}]
    summary["open_line_count"] = len(active_lines)
    tolerance = max(5, int(config.target_open_line_count * 0.05))
    if abs(len(active_lines) - config.target_open_line_count) > tolerance:
        errors.append(
            "Open line count "
            f"{len(active_lines)} outside tolerance {tolerance} of target {config.target_open_line_count}."
        )

    schedules_by_line: dict[str, list[Record]] = defaultdict(list)
    for schedule in datasets["delivery_schedules"]:
        if str(schedule["po_line_id"]) not in line_by_id:
            errors.append(f"Schedule {schedule['id']} references missing line {schedule['po_line_id']}.")
        schedules_by_line[str(schedule["po_line_id"])].append(schedule)

    for line_id, schedules in schedules_by_line.items():
        expected = float(str(final_line_versions[line_id]["base_quantity"]))
        actual = sum(float(str(schedule["scheduled_quantity"])) for schedule in schedules)
        if round(expected - actual, 4) != 0:
            errors.append(f"Schedule quantity mismatch for line {line_id}: {actual} != {expected}.")

    for allocation in datasets["receipt_allocations"]:
        receipt = receipt_by_id.get(str(allocation["receipt_transaction_id"]))
        if receipt is None:
            errors.append(f"Allocation {allocation['id']} references missing receipt.")
            continue
        bucket = str(allocation["allocation_bucket"])
        schedule_id = str(allocation["delivery_schedule_id"])
        if bucket == "line_residual" and schedule_id:
            errors.append(f"Line-residual allocation {allocation['id']} has a schedule.")
        if bucket != "line_residual" and not schedule_id:
            errors.append(f"Schedule allocation {allocation['id']} is missing a schedule.")
        if schedule_id:
            linked_schedule = schedule_by_id.get(schedule_id)
            if linked_schedule is None:
                errors.append(f"Allocation {allocation['id']} references missing schedule {schedule_id}.")
            elif str(linked_schedule["po_line_id"]) != str(receipt["po_line_id"]):
                errors.append(f"Allocation {allocation['id']} links receipt and schedule from different PO lines.")

    receipt_ids = set(receipt_by_id)
    for receipt in datasets["receipt_transactions"]:
        corrected = str(receipt["corrects_receipt_id"])
        if corrected and corrected not in receipt_ids:
            errors.append(f"Receipt {receipt['id']} corrects/reverses missing receipt {corrected}.")
        if float(str(receipt["base_quantity"])) == 0:
            errors.append(f"Receipt {receipt['id']} has zero base quantity.")

    scenario_types = {str(row["scenario_type"]) for row in datasets["scenario_registry"]}
    summary["scenario_counts"] = dict(Counter(str(row["scenario_type"]) for row in datasets["scenario_registry"]))
    expected_scenarios = {
        "overdue_critical_order",
        "partial_receipt_remaining_exposure",
        "supplier_commitment_breach",
        "demand_shock",
        "receipt_correction",
        "receipt_reversal",
        "split_schedule",
        "supplier_deterioration",
        "inventory_reallocation_opportunity",
        "false_positive_source_data_correction",
        "missing_supplier_signal",
        "missing_inventory_signal",
    }
    missing_scenarios = sorted(expected_scenarios - scenario_types)
    if missing_scenarios:
        errors.append(f"Missing scenario types: {', '.join(missing_scenarios)}.")

    outcome_classes = Counter(str(row["opportunity_class"]) for row in datasets["synthetic_outcome_observations"])
    summary["outcome_opportunity_counts"] = dict(outcome_classes)
    for opportunity_class in (
        "true_positive_opportunity",
        "false_positive_opportunity",
        "true_negative_opportunity",
        "false_negative_opportunity",
    ):
        if outcome_classes[opportunity_class] == 0:
            errors.append(f"No {opportunity_class} records generated.")

    _validate_no_real_data_markers(datasets, errors)
    summary.update(build_distribution_summary(datasets))
    return ValidationResult(passed=not errors, errors=errors, summary=summary)


def _validate_unique(datasets: DatasetMap, dataset_name: str, key: str, errors: list[str]) -> None:
    values = [str(row[key]) for row in datasets[dataset_name]]
    duplicates = len(values) - len(set(values))
    if duplicates:
        errors.append(f"{dataset_name}.{key} has {duplicates} duplicate values.")


def _final_line_versions(rows: list[Record]) -> dict[str, Record]:
    latest: dict[str, Record] = {}
    for row in rows:
        line_id = str(row["po_line_id"])
        current = latest.get(line_id)
        if current is None or int(str(row["amendment_version"])) > int(str(current["amendment_version"])):
            latest[line_id] = row
    return latest


def _validate_no_real_data_markers(datasets: DatasetMap, errors: list[str]) -> None:
    forbidden = ("pty ltd", "acn", "abn", "@", "password", "secret", "token")
    for dataset_name, rows in datasets.items():
        for row_number, row in enumerate(rows, start=1):
            for value in row.values():
                text = str(value).lower()
                if any(marker in text for marker in forbidden):
                    errors.append(f"Potential real/private marker in {dataset_name} row {row_number}.")
                    return


def build_distribution_summary(datasets: DatasetMap) -> dict[str, Any]:
    """Build machine-readable distribution evidence."""

    final_lines = list(_final_line_versions(datasets["purchase_order_line_versions"]).values())
    site_by_id = {str(row["id"]): str(row["site_code"]) for row in datasets["sites"]}
    product_version_by_id = {str(row["product_id"]): row for row in datasets["product_versions"]}
    lines_by_site = Counter(site_by_id[str(row["site_id"])] for row in final_lines)
    lines_by_category = Counter(str(product_version_by_id[str(row["product_id"])]["category"]) for row in final_lines)
    status_distribution = Counter(str(row["line_status"]) for row in final_lines)
    split_schedule_line_ids = {
        str(row["po_line_id"]) for row in datasets["delivery_schedules"] if "-SCH-2" in str(row["source_schedule_key"])
    }
    receipt_line_counts = Counter(
        str(row["po_line_id"])
        for row in datasets["receipt_transactions"]
        if row["transaction_type"] == "receipt"
    )
    partial_line_count = sum(1 for count in receipt_line_counts.values() if count > 1)
    late_receipt_count = sum(1 for row in datasets["receipt_transactions"] if row.get("late_receipt_flag") == "true")
    correction_reversal_count = sum(
        1 for row in datasets["receipt_transactions"] if row["transaction_type"] in {"correction", "reversal"}
    )
    missing_signal_count = sum(
        1
        for row in datasets["supplier_commitment_observations"]
        if str(row["scenario_ids"]).find("missing") >= 0
    ) + sum(1 for row in datasets["inventory_snapshots"] if row["missing_signal_flag"] == "true")
    outcome_distribution = Counter(
        str(row["operational_impact"]) for row in datasets["synthetic_outcome_observations"]
    )
    line_count = max(len(final_lines), 1)
    return {
        "lines_by_site": dict(lines_by_site),
        "lines_by_product_category": dict(lines_by_category),
        "status_distribution": dict(status_distribution),
        "open_line_count": status_distribution["open"] + status_distribution["on_hold"],
        "split_schedule_rate": round(len(split_schedule_line_ids) / line_count, 4),
        "partial_receipt_rate": round(partial_line_count / line_count, 4),
        "late_receipt_rate": round(late_receipt_count / max(len(datasets["receipt_transactions"]), 1), 4),
        "correction_reversal_rate": round(correction_reversal_count / max(len(datasets["receipt_transactions"]), 1), 4),
        "missing_signal_count": missing_signal_count,
        "outcome_distribution": dict(outcome_distribution),
    }


def load_exported_datasets(path: Path) -> DatasetMap:
    """Load generated CSV datasets from an export path."""

    import csv

    datasets: DatasetMap = {}
    for csv_path in sorted(path.glob("*.csv")):
        if csv_path.name == "manifest.csv":
            continue
        with csv_path.open(encoding="utf-8", newline="") as handle:
            datasets[csv_path.stem] = [dict(row) for row in csv.DictReader(handle)]
    return datasets


def write_quality_summary(path: Path, result: ValidationResult) -> None:
    """Write quality summary JSON."""

    payload = result.summary | {"passed": result.passed, "errors": result.errors}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
