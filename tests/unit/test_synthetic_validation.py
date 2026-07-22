"""Validation tests for generated synthetic records."""

import inspect
from collections import Counter, defaultdict
from copy import deepcopy
from uuid import UUID

from scecs.synthetic._util import parse_timestamp
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


def test_temporal_validation_allows_future_plans_but_rejects_future_observations() -> None:
    """Future business dates are allowed only when the observation existed by as-of."""

    config = ci_config()
    bundle = generate_dataset_bundle(config)
    datasets = deepcopy(bundle.datasets)
    datasets["delivery_schedules"][0]["expected_date"] = "2026-07-15"
    datasets["supplier_commitment_observations"][0]["committed_date"] = "2026-07-15"
    datasets["supplier_commitment_observations"][0]["observed_at"] = config.as_of_timestamp

    result = validate_dataset_bundle(datasets, config)

    assert result.passed, result.errors

    datasets["supplier_commitment_observations"][0]["observed_at"] = "2026-07-01T09:00:00+10:00"
    result = validate_dataset_bundle(datasets, config)

    assert not result.passed
    assert any("supplier_commitment_observations.observed_at" in error for error in result.errors)


def test_post_as_of_operational_receipt_is_rejected_and_future_receipts_are_evaluation_only() -> None:
    """Operational receipts stop at T0; post-T0 realisations live in the evaluation dataset."""

    config = ci_config()
    bundle = generate_dataset_bundle(config)
    as_of = parse_timestamp(config.as_of_timestamp)

    assert bundle.datasets["future_receipt_outcomes"]
    assert all(parse_timestamp(row["posted_at"]) <= as_of for row in bundle.datasets["receipt_transactions"])
    assert all(parse_timestamp(row["posted_at"]) > as_of for row in bundle.datasets["future_receipt_outcomes"])
    assert all("source_load_id" not in row for row in bundle.datasets["future_receipt_outcomes"])
    assert all(row["evaluation_only_flag"] == "true" for row in bundle.datasets["future_receipt_outcomes"])

    datasets = deepcopy(bundle.datasets)
    datasets["receipt_transactions"][0]["posted_at"] = "2026-07-01T09:00:00+10:00"
    result = validate_dataset_bundle(datasets, config)

    assert not result.passed
    assert any("receipt_transactions.posted_at" in error for error in result.errors)


def test_future_realised_receipts_drive_open_line_outcomes_but_not_operational_inputs() -> None:
    """Open-line outcomes should use hidden future receipts without leaking them into source receipts."""

    config = ci_config()
    bundle = generate_dataset_bundle(config)
    final_versions = _final_versions_for_test(bundle.datasets["purchase_order_line_versions"])
    operational_receipt_line_ids = {str(row["po_line_id"]) for row in bundle.datasets["receipt_transactions"]}
    future_receipts_by_line = defaultdict(list)
    for row in bundle.datasets["future_receipt_outcomes"]:
        if row["transaction_type"] == "receipt":
            future_receipts_by_line[str(row["po_line_id"])].append(row)
    outcomes = {
        str(row["po_line_id"]): row
        for row in bundle.datasets["synthetic_outcome_observations"]
    }

    open_line_ids = [
        line_id
        for line_id, row in final_versions.items()
        if str(row["line_status"]) in {"open", "on_hold"}
    ]
    assert open_line_ids
    for line_id in open_line_ids:
        assert future_receipts_by_line[line_id]
        future_ids = {str(row["id"]) for row in future_receipts_by_line[line_id]}
        outcome_ids = set(str(outcomes[line_id]["future_receipt_outcome_ids"]).split(";"))
        assert future_ids.issubset(outcome_ids)
        assert bool(operational_receipt_line_ids) is True
        assert any(
            str(row["late_receipt_flag"]) == "true" for row in future_receipts_by_line[line_id]
        ) == (outcomes[line_id]["material_late"] == "true")


def test_historical_receipts_remain_visible_and_supplier_performance_uses_operational_history() -> None:
    """Closed-line history remains in operational receipts; future rows stay out of performance inputs."""

    config = ci_config()
    bundle = generate_dataset_bundle(config)
    as_of = parse_timestamp(config.as_of_timestamp)
    final_versions = _final_versions_for_test(bundle.datasets["purchase_order_line_versions"])
    closed_line_ids = {
        line_id
        for line_id, row in final_versions.items()
        if str(row["line_status"]) == "closed"
    }

    historical_receipts = [
        row
        for row in bundle.datasets["receipt_transactions"]
        if str(row["po_line_id"]) in closed_line_ids and row["transaction_type"] == "receipt"
    ]
    assert historical_receipts
    assert all(parse_timestamp(row["posted_at"]) <= as_of for row in historical_receipts)
    assert all(
        "source_load_id" not in row
        for row in bundle.datasets["future_receipt_outcomes"]
    )
    assert validate_dataset_bundle(bundle.datasets, config).passed


def test_missing_signal_summary_uses_types_and_flags_not_uuid_text() -> None:
    """Missing-signal metrics should not search scenario UUID text."""

    config = ci_config()
    bundle = generate_dataset_bundle(config)
    result = validate_dataset_bundle(bundle.datasets, config)
    scenario_counts = Counter(str(row["scenario_type"]) for row in bundle.datasets["scenario_registry"])
    missing_inventory_flags = sum(
        1 for row in bundle.datasets["inventory_snapshots"] if row["missing_signal_flag"] == "true"
    )

    assert result.passed, result.errors
    assert all("missing" not in str(row.get("scenario_ids", "")) for rows in bundle.datasets.values() for row in rows)
    assert result.summary["missing_supplier_signal_count"] == scenario_counts["missing_supplier_signal"]
    assert result.summary["missing_inventory_signal_count"] == missing_inventory_flags
    assert result.summary["missing_signal_count"] == (
        scenario_counts["missing_supplier_signal"] + missing_inventory_flags
    )


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


def _final_versions_for_test(rows: list[Record]) -> dict[str, Record]:
    latest: dict[str, Record] = {}
    for row in rows:
        line_id = str(row["po_line_id"])
        if line_id not in latest or int(str(row["amendment_version"])) > int(str(latest[line_id]["amendment_version"])):
            latest[line_id] = row
    return latest
