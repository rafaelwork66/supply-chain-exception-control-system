"""Validation tests for generated synthetic records."""

import inspect
from collections import Counter, defaultdict

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
