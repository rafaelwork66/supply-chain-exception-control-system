"""Validation tests for generated synthetic records."""

import inspect
from collections import Counter, defaultdict
from uuid import UUID

from scecs.synthetic.config import ci_config
from scecs.synthetic.generator import generate_dataset_bundle
from scecs.synthetic.outcomes import generate_outcomes
from scecs.synthetic.scenarios import MANDATORY_SCENARIO_TYPES
from scecs.synthetic.types import Record
from scecs.synthetic.validation import validate_dataset_bundle


def test_ci_generation_respects_record_counts_and_required_scenarios() -> None:
    """The sample profile should generate configured counts and all scenario families."""

    config = ci_config()
    bundle = generate_dataset_bundle(config)
    result = validate_dataset_bundle(bundle.datasets, config)

    assert result.passed, result.errors
    assert len(bundle.datasets["sites"]) == config.site_count
    assert len(bundle.datasets["suppliers"]) == config.supplier_count
    assert len(bundle.datasets["products"]) == config.product_count
    assert len(bundle.datasets["purchase_order_lines"]) == config.po_line_count
    assert result.summary["open_line_count"] == config.target_open_line_count
    assert set(MANDATORY_SCENARIO_TYPES).issubset(
        {str(row["scenario_type"]) for row in bundle.datasets["scenario_registry"]}
    )


def test_delivery_schedule_quantities_reconcile_to_line_base_quantity() -> None:
    """Delivery schedules should reconcile exactly to final PO-line base quantity."""

    bundle = generate_dataset_bundle(ci_config())
    final_versions: dict[str, Record] = {}
    for row in bundle.datasets["purchase_order_line_versions"]:
        line_id = str(row["po_line_id"])
        is_newer = line_id not in final_versions or int(str(row["amendment_version"])) > int(
            str(final_versions[line_id]["amendment_version"])
        )
        if is_newer:
            final_versions[line_id] = row
    schedules_by_line = defaultdict(list)
    for row in bundle.datasets["delivery_schedules"]:
        schedules_by_line[str(row["po_line_id"])].append(row)

    for line_id, schedules in schedules_by_line.items():
        expected = float(str(final_versions[line_id]["base_quantity"]))
        actual = sum(float(str(schedule["scheduled_quantity"])) for schedule in schedules)
        assert round(actual - expected, 4) == 0


def test_receipt_allocations_are_line_consistent_and_corrections_reference_existing_receipts() -> None:
    """Receipt allocations and correction/reversal links should be internally valid."""

    bundle = generate_dataset_bundle(ci_config())
    receipt_by_id = {str(row["id"]): row for row in bundle.datasets["receipt_transactions"]}
    schedule_by_id = {str(row["id"]): row for row in bundle.datasets["delivery_schedules"]}

    for allocation in bundle.datasets["receipt_allocations"]:
        receipt = receipt_by_id[str(allocation["receipt_transaction_id"])]
        schedule_id = str(allocation["delivery_schedule_id"])
        if schedule_id:
            assert schedule_by_id[schedule_id]["po_line_id"] == receipt["po_line_id"]
        else:
            assert allocation["allocation_bucket"] == "line_residual"

    for receipt in bundle.datasets["receipt_transactions"]:
        corrected = str(receipt["corrects_receipt_id"])
        if corrected:
            assert corrected in receipt_by_id


def test_scenario_ids_are_registry_uuids_and_scenario_types_remain_readable() -> None:
    """Operational scenario fields should use registry UUIDs plus readable labels."""

    bundle = generate_dataset_bundle(ci_config())
    scenario_ids = {str(row["scenario_id"]) for row in bundle.datasets["scenario_registry"]}
    operational_rows = (
        bundle.datasets["purchase_order_line_versions"]
        + bundle.datasets["delivery_schedules"]
        + bundle.datasets["receipt_transactions"]
        + bundle.datasets["synthetic_outcome_observations"]
    )

    observed_ids: set[str] = set()
    for row in operational_rows:
        for scenario_id in str(row.get("scenario_ids", "")).split(";"):
            if scenario_id:
                UUID(scenario_id)
                assert scenario_id in scenario_ids
                observed_ids.add(scenario_id)
                assert row.get("scenario_types")

    assert observed_ids


def test_mandatory_scenarios_create_observable_source_effects() -> None:
    """Validation should prove scenario registry entries are more than labels."""

    config = ci_config()
    bundle = generate_dataset_bundle(config)
    result = validate_dataset_bundle(bundle.datasets, config)

    assert result.passed, result.errors
    assert set(result.summary["scenario_counts"]).issuperset(
        {
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
    )


def test_purchase_orders_have_one_supplier_and_compatible_header_status() -> None:
    """A PO header supplier should govern every line under that PO."""

    bundle = generate_dataset_bundle(ci_config())
    po_supplier = {
        str(row["purchase_order_id"]): str(row["supplier_id"])
        for row in bundle.datasets["purchase_order_versions"]
    }
    po_status = {
        str(row["purchase_order_id"]): str(row["order_status"])
        for row in bundle.datasets["purchase_order_versions"]
    }
    line_po = {
        str(row["id"]): str(row["purchase_order_id"])
        for row in bundle.datasets["purchase_order_lines"]
    }
    line_statuses_by_po = defaultdict(set)

    for row in bundle.datasets["purchase_order_line_versions"]:
        po_id = line_po[str(row["po_line_id"])]
        assert str(row["po_supplier_id"]) == po_supplier[po_id]
        line_statuses_by_po[po_id].add(str(row["line_status"]))

    for po_id, statuses in line_statuses_by_po.items():
        if statuses & {"open", "on_hold"}:
            assert po_status[po_id] in {"open", "on_hold"}
        elif statuses == {"cancelled"}:
            assert po_status[po_id] == "cancelled"
        else:
            assert po_status[po_id] == "closed"


def test_amendments_recompute_quantities_values_and_preserve_prior_versions() -> None:
    """Each amendment version should reconcile independently to UOM and value fields."""

    bundle = generate_dataset_bundle(ci_config())
    conversions = {
        (str(row["product_id"]), str(row["from_uom"])): float(str(row["conversion_factor"]))
        for row in bundle.datasets["uom_conversions"]
    }
    versions_by_line = defaultdict(list)
    for row in bundle.datasets["purchase_order_line_versions"]:
        versions_by_line[str(row["po_line_id"])].append(row)
        factor = conversions[(str(row["product_id"]), str(row["order_uom"]))]
        assert round(float(str(row["ordered_quantity"])) * factor - float(str(row["base_quantity"])), 4) == 0
        expected_value = float(str(row["base_quantity"])) * float(str(row["unit_price_aud"]))
        assert round(expected_value - float(str(row["line_value_aud"])), 2) == 0

    amended_lines = [rows for rows in versions_by_line.values() if len(rows) > 1]
    assert amended_lines
    changed = False
    for rows in amended_lines:
        sorted_rows = sorted(rows, key=lambda item: int(str(item["amendment_version"])))
        ordered = [float(str(row["ordered_quantity"])) for row in sorted_rows]
        need_dates = [str(row["need_date"]) for row in sorted_rows]
        changed = changed or len(set(ordered)) > 1 or len(set(need_dates)) > 1
    assert changed


def test_receipt_allocations_reconcile_all_transaction_types_and_net_capacity() -> None:
    """Receipt allocations should reconcile receipts, corrections, reversals and residual excess."""

    bundle = generate_dataset_bundle(ci_config())
    allocations_by_receipt = defaultdict(list)
    for allocation in bundle.datasets["receipt_allocations"]:
        allocations_by_receipt[str(allocation["receipt_transaction_id"])].append(allocation)
    receipt_types = Counter(str(row["transaction_type"]) for row in bundle.datasets["receipt_transactions"])
    assert receipt_types["receipt"] > 0
    assert receipt_types["correction"] > 0
    assert receipt_types["reversal"] > 0

    signed_schedule_net: dict[str, float] = defaultdict(float)
    line_residual_receipts = set()
    for receipt in bundle.datasets["receipt_transactions"]:
        receipt_id = str(receipt["id"])
        allocations = allocations_by_receipt[receipt_id]
        assert allocations
        expected = abs(float(str(receipt["base_quantity"])))
        actual = sum(float(str(row["allocated_base_quantity"])) for row in allocations)
        assert round(actual - expected, 4) == 0
        sign = -1 if float(str(receipt["base_quantity"])) < 0 else 1
        for allocation in allocations:
            schedule_id = str(allocation["delivery_schedule_id"])
            if schedule_id:
                signed_schedule_net[schedule_id] += sign * float(str(allocation["allocated_base_quantity"]))
            else:
                line_residual_receipts.add(receipt_id)

    schedule_by_id = {str(row["id"]): row for row in bundle.datasets["delivery_schedules"]}
    for schedule_id, net_quantity in signed_schedule_net.items():
        assert net_quantity <= float(str(schedule_by_id[schedule_id]["scheduled_quantity"])) + 0.0001
    assert line_residual_receipts


def test_outcomes_include_all_opportunity_classes_and_do_not_accept_score_inputs() -> None:
    """Outcome generation should remain independent from future risk-scoring code."""

    bundle = generate_dataset_bundle(ci_config())
    counts = Counter(str(row["opportunity_class"]) for row in bundle.datasets["synthetic_outcome_observations"])
    signature = inspect.signature(generate_outcomes)

    assert counts["true_positive_opportunity"] > 0
    assert counts["false_positive_opportunity"] > 0
    assert counts["true_negative_opportunity"] > 0
    assert counts["false_negative_opportunity"] > 0
    assert "score" not in signature.parameters
    assert "severity" not in signature.parameters
