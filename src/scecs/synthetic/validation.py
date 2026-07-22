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
    scenario_by_id = {str(row["scenario_id"]): row for row in datasets["scenario_registry"]}

    final_line_versions = _final_line_versions(datasets["purchase_order_line_versions"])
    _validate_major_foreign_keys(datasets, errors)
    _validate_scenario_ids_exist(datasets, scenario_by_id, errors)
    _validate_po_supplier_consistency(datasets, errors)
    _validate_uom_and_value_reconciliation(datasets, errors)
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

    _validate_receipt_allocation_reconciliation(datasets, errors)
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
    _validate_scenario_behaviour(datasets, config, scenario_by_id, errors)
    _validate_supplier_performance_consistency(datasets, errors)

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


def _validate_major_foreign_keys(datasets: DatasetMap, errors: list[str]) -> None:
    source_system_ids = {str(row["id"]) for row in datasets["source_systems"]}
    source_load_ids = {str(row["id"]) for row in datasets["source_loads"]}
    site_ids = {str(row["id"]) for row in datasets["sites"]}
    supplier_ids = {str(row["id"]) for row in datasets["suppliers"]}
    product_ids = {str(row["id"]) for row in datasets["products"]}
    po_ids = {str(row["id"]) for row in datasets["purchase_orders"]}
    line_ids = {str(row["id"]) for row in datasets["purchase_order_lines"]}
    schedule_ids = {str(row["id"]) for row in datasets["delivery_schedules"]}
    receipt_ids = {str(row["id"]) for row in datasets["receipt_transactions"]}

    for row in datasets["purchase_orders"]:
        _require_fk(row, "source_system_id", source_system_ids, "purchase_orders", errors)
    for row in datasets["purchase_order_versions"]:
        _require_fk(row, "purchase_order_id", po_ids, "purchase_order_versions", errors)
        _require_fk(row, "source_load_id", source_load_ids, "purchase_order_versions", errors)
        _require_fk(row, "supplier_id", supplier_ids, "purchase_order_versions", errors)
    for row in datasets["purchase_order_lines"]:
        _require_fk(row, "purchase_order_id", po_ids, "purchase_order_lines", errors)
    for row in datasets["purchase_order_line_versions"]:
        _require_fk(row, "po_line_id", line_ids, "purchase_order_line_versions", errors)
        _require_fk(row, "source_load_id", source_load_ids, "purchase_order_line_versions", errors)
        _require_fk(row, "product_id", product_ids, "purchase_order_line_versions", errors)
        _require_fk(row, "site_id", site_ids, "purchase_order_line_versions", errors)
        _require_fk(row, "po_supplier_id", supplier_ids, "purchase_order_line_versions", errors)
    for row in datasets["delivery_schedules"]:
        _require_fk(row, "po_line_id", line_ids, "delivery_schedules", errors)
    for row in datasets["supplier_commitment_observations"]:
        _require_fk(row, "source_load_id", source_load_ids, "supplier_commitment_observations", errors)
        _require_fk(row, "po_line_id", line_ids, "supplier_commitment_observations", errors)
        _require_optional_fk(row, "delivery_schedule_id", schedule_ids, "supplier_commitment_observations", errors)
    for row in datasets["receipt_transactions"]:
        _require_fk(row, "source_system_id", source_system_ids, "receipt_transactions", errors)
        _require_fk(row, "source_load_id", source_load_ids, "receipt_transactions", errors)
        _require_fk(row, "po_line_id", line_ids, "receipt_transactions", errors)
        _require_optional_fk(row, "corrects_receipt_id", receipt_ids, "receipt_transactions", errors)
    for row in datasets["receipt_allocations"]:
        _require_fk(row, "receipt_transaction_id", receipt_ids, "receipt_allocations", errors)
        _require_optional_fk(row, "delivery_schedule_id", schedule_ids, "receipt_allocations", errors)
    for dataset_name in ("inventory_snapshots", "demand_requirements"):
        for row in datasets[dataset_name]:
            _require_fk(row, "source_load_id", source_load_ids, dataset_name, errors)
            _require_fk(row, "product_id", product_ids, dataset_name, errors)
            _require_fk(row, "site_id", site_ids, dataset_name, errors)


def _require_fk(row: Record, field: str, valid_ids: set[str], dataset_name: str, errors: list[str]) -> None:
    if str(row[field]) not in valid_ids:
        errors.append(f"{dataset_name}.{field} references missing id {row[field]}.")


def _require_optional_fk(row: Record, field: str, valid_ids: set[str], dataset_name: str, errors: list[str]) -> None:
    value = str(row[field])
    if value and value not in valid_ids:
        errors.append(f"{dataset_name}.{field} references missing id {value}.")


def _validate_scenario_ids_exist(
    datasets: DatasetMap,
    scenario_by_id: dict[str, Record],
    errors: list[str],
) -> None:
    for dataset_name, rows in datasets.items():
        if dataset_name == "scenario_registry":
            continue
        for row in rows:
            for scenario_id in _split_semicolon(row.get("scenario_ids", "")):
                if scenario_id not in scenario_by_id:
                    errors.append(f"{dataset_name} references unknown scenario_id {scenario_id}.")


def _validate_po_supplier_consistency(datasets: DatasetMap, errors: list[str]) -> None:
    po_supplier = {
        str(row["purchase_order_id"]): str(row["supplier_id"])
        for row in datasets["purchase_order_versions"]
    }
    line_po = {
        str(row["id"]): str(row["purchase_order_id"])
        for row in datasets["purchase_order_lines"]
    }
    statuses_by_po: dict[str, set[str]] = defaultdict(set)
    for row in datasets["purchase_order_line_versions"]:
        po_id = line_po[str(row["po_line_id"])]
        expected_supplier = po_supplier[po_id]
        if str(row["po_supplier_id"]) != expected_supplier:
            errors.append(f"PO line {row['po_line_id']} supplier does not match PO header supplier.")
        statuses_by_po[po_id].add(str(row["line_status"]))
    for version in datasets["purchase_order_versions"]:
        statuses = statuses_by_po[str(version["purchase_order_id"])]
        expected_status = "closed"
        if statuses & {"open", "on_hold"}:
            expected_status = "on_hold" if "on_hold" in statuses and "open" not in statuses else "open"
        elif statuses == {"cancelled"}:
            expected_status = "cancelled"
        if str(version["order_status"]) != expected_status:
            errors.append(f"PO {version['purchase_order_id']} status is not compatible with line statuses.")


def _validate_uom_and_value_reconciliation(datasets: DatasetMap, errors: list[str]) -> None:
    conversion = {
        (str(row["product_id"]), str(row["from_uom"])): float(str(row["conversion_factor"]))
        for row in datasets["uom_conversions"]
    }
    for row in datasets["purchase_order_line_versions"]:
        factor = conversion[(str(row["product_id"]), str(row["order_uom"]))]
        ordered = float(str(row["ordered_quantity"]))
        base = float(str(row["base_quantity"]))
        if round(ordered * factor - base, 4) != 0:
            errors.append(f"PO line version {row['id']} has inconsistent UOM base quantity.")
        unit_price = float(str(row["unit_price_aud"]))
        line_value = float(str(row["line_value_aud"]))
        if base <= 0 or ordered <= 0:
            errors.append(f"PO line version {row['id']} has non-positive quantity.")
        if unit_price < 0 or line_value < 0:
            errors.append(f"PO line version {row['id']} has negative monetary value.")
        if round(base * unit_price - line_value, 2) != 0:
            errors.append(f"PO line version {row['id']} has inconsistent line value.")


def _validate_receipt_allocation_reconciliation(datasets: DatasetMap, errors: list[str]) -> None:
    allocations_by_receipt: dict[str, list[Record]] = defaultdict(list)
    for allocation in datasets["receipt_allocations"]:
        allocations_by_receipt[str(allocation["receipt_transaction_id"])].append(allocation)
    for receipt in datasets["receipt_transactions"]:
        receipt_id = str(receipt["id"])
        allocated = sum(float(str(row["allocated_base_quantity"])) for row in allocations_by_receipt[receipt_id])
        expected = abs(float(str(receipt["base_quantity"])))
        if round(allocated - expected, 4) != 0:
            errors.append(f"Receipt {receipt_id} allocation total {allocated} does not equal abs quantity {expected}.")

    receipt_by_id = {str(row["id"]): row for row in datasets["receipt_transactions"]}
    schedule_by_id = {str(row["id"]): row for row in datasets["delivery_schedules"]}
    signed_schedule_net: dict[str, float] = defaultdict(float)
    signed_line_net: dict[str, float] = defaultdict(float)
    for receipt_id, rows in allocations_by_receipt.items():
        receipt = receipt_by_id[receipt_id]
        sign = -1.0 if float(str(receipt["base_quantity"])) < 0 else 1.0
        for allocation in rows:
            quantity = float(str(allocation["allocated_base_quantity"])) * sign
            schedule_id = str(allocation["delivery_schedule_id"])
            if schedule_id:
                signed_schedule_net[schedule_id] += quantity
            else:
                signed_line_net[str(receipt["po_line_id"])] += quantity
    for schedule_id, net_quantity in signed_schedule_net.items():
        schedule = schedule_by_id[schedule_id]
        if net_quantity - float(str(schedule["scheduled_quantity"])) > 0.0001:
            errors.append(f"Schedule {schedule_id} net receipt exceeds scheduled capacity.")
    for line_id, net_quantity in signed_line_net.items():
        if net_quantity < -0.0001:
            errors.append(f"Line {line_id} has negative net line-residual allocation.")


def _validate_scenario_behaviour(
    datasets: DatasetMap,
    config: SyntheticGeneratorConfig,
    scenario_by_id: dict[str, Record],
    errors: list[str],
) -> None:
    final_lines = _final_line_versions(datasets["purchase_order_line_versions"])
    line_by_key = {str(row["canonical_line_key"]): str(row["id"]) for row in datasets["purchase_order_lines"]}
    schedules_by_line: dict[str, list[Record]] = defaultdict(list)
    for schedule in datasets["delivery_schedules"]:
        schedules_by_line[str(schedule["po_line_id"])].append(schedule)
    receipts_by_line: dict[str, list[Record]] = defaultdict(list)
    for receipt in datasets["receipt_transactions"]:
        receipts_by_line[str(receipt["po_line_id"])].append(receipt)
    commitments_by_line: dict[str, list[Record]] = defaultdict(list)
    for commitment in datasets["supplier_commitment_observations"]:
        commitments_by_line[str(commitment["po_line_id"])].append(commitment)
    demand_by_product_site: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for demand in datasets["demand_requirements"]:
        demand_by_product_site[(str(demand["product_id"]), str(demand["site_id"]))].append(demand)
    inventory_by_product_site: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for inventory in datasets["inventory_snapshots"]:
        inventory_by_product_site[(str(inventory["product_id"]), str(inventory["site_id"]))].append(inventory)

    for scenario in scenario_by_id.values():
        scenario_type = str(scenario["scenario_type"])
        line_id = line_by_key[str(scenario["affected_key"])]
        line = final_lines[line_id]
        scenario_id = str(scenario["scenario_id"])
        if scenario_type == "overdue_critical_order":
            residual = _line_residual_quantity(line_id, final_lines, receipts_by_line)
            if not (
                str(line["line_status"]) == "open"
                and str(line["critical_order_flag"]) == "true"
                and str(line["need_date"]) < config.as_of_date.isoformat()
                and residual > 0
            ):
                errors.append("overdue_critical_order did not create an open critical overdue residual line.")
        elif scenario_type == "partial_receipt_remaining_exposure":
            residual = _line_residual_quantity(line_id, final_lines, receipts_by_line)
            if not (0 < residual < float(str(line["base_quantity"]))):
                errors.append("partial_receipt_remaining_exposure did not leave positive residual exposure.")
        elif scenario_type == "supplier_commitment_breach":
            commitments = commitments_by_line[line_id]
            receipts = [row for row in receipts_by_line[line_id] if row["transaction_type"] == "receipt"]
            committed_dates = [str(row["committed_date"]) for row in commitments if str(row["committed_date"])]
            receipt_dates = [str(row["posted_at"])[:10] for row in receipts]
            if not committed_dates or not receipt_dates or max(receipt_dates) <= min(committed_dates):
                errors.append("supplier_commitment_breach did not create receipt later than commitment.")
        elif scenario_type == "demand_shock":
            rows = demand_by_product_site[(str(line["product_id"]), str(line["site_id"]))]
            if not any(
                row.get("demand_shock_flag") == "true" and scenario_id in _split_semicolon(row["scenario_ids"])
                for row in rows
            ):
                errors.append("demand_shock did not create traceable increased demand.")
        elif scenario_type == "receipt_correction":
            if not any(
                row["transaction_type"] == "correction" and str(row["corrects_receipt_id"])
                for row in receipts_by_line[line_id]
            ):
                errors.append("receipt_correction did not create linked correction transaction.")
        elif scenario_type == "receipt_reversal":
            if not any(
                row["transaction_type"] == "reversal" and str(row["corrects_receipt_id"])
                for row in receipts_by_line[line_id]
            ):
                errors.append("receipt_reversal did not create linked reversal transaction.")
        elif scenario_type == "split_schedule":
            schedule_total = sum(float(str(row["scheduled_quantity"])) for row in schedules_by_line[line_id])
            if len(schedules_by_line[line_id]) < 2 or round(schedule_total - float(str(line["base_quantity"])), 4) != 0:
                errors.append("split_schedule did not create reconciling split schedules.")
        elif scenario_type == "supplier_deterioration":
            receipts = [row for row in receipts_by_line[line_id] if row["transaction_type"] == "receipt"]
            if not any(row["late_receipt_flag"] == "true" for row in receipts):
                errors.append("supplier_deterioration did not create worse delivery behaviour.")
        elif scenario_type == "inventory_reallocation_opportunity":
            if not _has_reallocation_effect(line, datasets["sites"], inventory_by_product_site):
                errors.append("inventory_reallocation_opportunity did not create shortage plus other-site surplus.")
        elif scenario_type == "false_positive_source_data_correction":
            rows = inventory_by_product_site[(str(line["product_id"]), str(line["site_id"]))]
            if not any(str(row["corrects_snapshot_id"]) for row in rows):
                errors.append("false_positive_source_data_correction did not create corrected inventory observation.")
        elif scenario_type == "missing_supplier_signal":
            if commitments_by_line[line_id]:
                errors.append("missing_supplier_signal has a supplier commitment observation.")
        elif scenario_type == "missing_inventory_signal":
            product_site_rows = inventory_by_product_site[(str(line["product_id"]), str(line["site_id"]))]
            matching_rows = [
                row
                for row in product_site_rows
                if scenario_id in _split_semicolon(row["scenario_ids"])
            ]
            if not any(
                str(row["missing_signal_flag"]) == "true" and str(row["snapshot_at"]) != config.as_of_timestamp
                for row in matching_rows
            ):
                errors.append("missing_inventory_signal did not create traceable stale inventory evidence.")
            current_rows = [row for row in product_site_rows if str(row["snapshot_at"]) == config.as_of_timestamp]
            if current_rows:
                errors.append("missing_inventory_signal has a valid current inventory observation.")


def _line_residual_quantity(
    line_id: str,
    final_lines: dict[str, Record],
    receipts_by_line: dict[str, list[Record]],
) -> float:
    signed_received = sum(float(str(row["base_quantity"])) for row in receipts_by_line[line_id])
    return round(float(str(final_lines[line_id]["base_quantity"])) - signed_received, 4)


def _has_reallocation_effect(
    line: Record,
    sites: list[Record],
    inventory_by_product_site: dict[tuple[str, str], list[Record]],
) -> bool:
    product_id = str(line["product_id"])
    site_id = str(line["site_id"])
    affected_rows = inventory_by_product_site[(product_id, site_id)]
    affected_current = [row for row in affected_rows if str(row["available_quantity"]) == "0.0000"]
    other_site_ids = [str(site["id"]) for site in sites if str(site["id"]) != site_id]
    surplus = False
    for other_site_id in other_site_ids:
        other_rows = inventory_by_product_site[(product_id, other_site_id)]
        if any(float(str(row["available_quantity"])) > float(str(row["allocated_quantity"])) for row in other_rows):
            surplus = True
    return bool(affected_current and surplus)


def _validate_supplier_performance_consistency(datasets: DatasetMap, errors: list[str]) -> None:
    line_by_id = {str(row["id"]): row for row in datasets["purchase_order_lines"]}
    po_supplier = {
        str(row["purchase_order_id"]): str(row["supplier_id"])
        for row in datasets["purchase_order_versions"]
    }
    final_lines = _final_line_versions(datasets["purchase_order_line_versions"])
    line_supplier_site = {
        line_id: (po_supplier[str(line_by_id[line_id]["purchase_order_id"])], str(row["site_id"]))
        for line_id, row in final_lines.items()
    }
    receipt_history: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for receipt in datasets["receipt_transactions"]:
        if receipt["transaction_type"] != "receipt":
            continue
        supplier_site = line_supplier_site[str(receipt["po_line_id"])]
        receipt_history[supplier_site].append(str(receipt["late_receipt_flag"]) != "true")
    contradictions = 0
    checked = 0
    for row in datasets["supplier_performance_snapshots"]:
        key = (str(row["supplier_id"]), str(row["site_id"]))
        observed = receipt_history.get(key, [])
        if len(observed) < 10:
            continue
        checked += 1
        observed_otif = sum(1 for ok in observed if ok) / len(observed)
        reported_otif = float(str(row["otif_rate"]))
        if abs(observed_otif - reported_otif) > 0.35:
            contradictions += 1
    if checked and contradictions / checked > 0.20:
        errors.append("Supplier-performance snapshots materially contradict generated receipt history.")


def _validate_unique(datasets: DatasetMap, dataset_name: str, key: str, errors: list[str]) -> None:
    values = [str(row[key]) for row in datasets[dataset_name]]
    duplicates = len(values) - len(set(values))
    if duplicates:
        errors.append(f"{dataset_name}.{key} has {duplicates} duplicate values.")


def _split_semicolon(value: object) -> list[str]:
    return [part for part in str(value).split(";") if part]


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
