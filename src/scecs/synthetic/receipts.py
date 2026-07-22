"""Supplier commitments, receipt transactions and receipt allocations."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import add_days, date_iso, parse_date, qty, stable_id, timestamp_for
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.purchase_orders import LineSnapshot
from scecs.synthetic.types import DatasetMap, Record


def _receipt_plan(line: LineSnapshot, rng: Random) -> tuple[float, int]:
    if line.line_status == "cancelled":
        return 0.0, 0
    if line.line_status in {"open", "on_hold"}:
        if "partial_receipt_remaining_exposure" in line.scenario_types:
            return line.base_quantity * 0.45, 2
        return line.base_quantity * rng.uniform(0.0, 0.75), 1 if rng.random() < 0.7 else 2
    if rng.random() < 0.04:
        return line.base_quantity * rng.uniform(1.01, 1.08), 1
    if rng.random() < 0.20:
        return line.base_quantity, rng.randint(2, 4)
    return line.base_quantity, 1


def generate_receipts_and_commitments(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    source_system_id: str,
    source_load_id: str,
    line_snapshots: list[LineSnapshot],
    delivery_schedules: list[Record],
) -> DatasetMap:
    """Generate supplier commitments, receipts and allocations."""

    schedule_by_id = {str(row["id"]): row for row in delivery_schedules}
    commitments: list[Record] = []
    receipts: list[Record] = []
    allocations: list[Record] = []
    receipt_sequence = 0

    for line in line_snapshots:
        need_date = parse_date(line.need_date)
        expected_date = parse_date(line.expected_date)
        commitment_missing = "missing_supplier_signal" in line.scenario_types or rng.random() < 0.06
        if not commitment_missing:
            schedule_id = line.schedule_ids[0] if line.schedule_ids and rng.random() < 0.8 else ""
            committed_date = expected_date
            if "supplier_commitment_breach" in line.scenario_types:
                committed_date = add_days(need_date, -2)
            commitments.append(
                {
                    "id": stable_id(config, "supplier_commitment", line.canonical_line_key),
                    "source_load_id": source_load_id,
                    "po_line_id": line.po_line_id,
                    "delivery_schedule_id": schedule_id,
                    "source_commitment_ref": f"COM-{line.canonical_line_key}",
                    "committed_quantity": qty(line.base_quantity),
                    "committed_date": date_iso(committed_date),
                    "channel": "portal" if rng.random() < 0.75 else "email_extract",
                    "observed_at": timestamp_for(add_days(need_date, -rng.randint(3, 20)), 10),
                    "supersedes_commitment_id": "",
                    "scenario_ids": ";".join(line.scenario_types),
                }
            )

        total_receipt_quantity, receipt_count = _receipt_plan(line, rng)
        if receipt_count == 0 or total_receipt_quantity <= 0:
            continue
        per_receipt = total_receipt_quantity / receipt_count
        for receipt_index in range(1, receipt_count + 1):
            receipt_sequence += 1
            receipt_document = f"RCV-{receipt_sequence:09d}"
            arrival_offset = rng.randint(1, 6) if rng.random() < 0.16 else -rng.randint(0, 8)
            if "supplier_commitment_breach" in line.scenario_types:
                arrival_offset = 9
            posted_day = add_days(expected_date, arrival_offset)
            receipt_id = stable_id(config, "receipt_transaction", receipt_document)
            quantity = per_receipt
            receipts.append(
                {
                    "id": receipt_id,
                    "source_system_id": source_system_id,
                    "source_load_id": source_load_id,
                    "po_line_id": line.po_line_id,
                    "receipt_document": receipt_document,
                    "receipt_item_sequence": "1",
                    "transaction_type": "receipt",
                    "source_quantity": qty(quantity),
                    "source_uom": "EA",
                    "base_quantity": qty(quantity),
                    "posted_at": timestamp_for(posted_day, 14, receipt_index),
                    "corrects_receipt_id": "",
                    "late_receipt_flag": "true" if posted_day > need_date else "false",
                    "scenario_ids": ";".join(line.scenario_types),
                }
            )

            allocation_sequence = 1
            if line.schedule_ids and rng.random() > 0.10:
                schedule_id = line.schedule_ids[min(receipt_index - 1, len(line.schedule_ids) - 1)]
                schedule = schedule_by_id[schedule_id]
                allocation_bucket = "schedule"
                delivery_schedule_id = schedule_id
                allocated_quantity = min(quantity, float(str(schedule["scheduled_quantity"])))
            else:
                allocation_bucket = "line_residual"
                delivery_schedule_id = ""
                allocated_quantity = quantity
            allocations.append(
                {
                    "id": stable_id(config, "receipt_allocation", f"{receipt_id}:{allocation_sequence}"),
                    "receipt_transaction_id": receipt_id,
                    "delivery_schedule_id": delivery_schedule_id,
                    "allocation_sequence": allocation_sequence,
                    "allocation_bucket": allocation_bucket,
                    "allocated_base_quantity": qty(allocated_quantity),
                    "po_line_id_for_validation": line.po_line_id,
                }
            )

            correction_scenario = "receipt_correction" in line.scenario_types
            reversal_scenario = "receipt_reversal" in line.scenario_types
            correction_rate = config.scenario_rates.receipt_correction_rate
            reversal_rate = config.scenario_rates.receipt_reversal_rate
            if correction_scenario or rng.random() < correction_rate:
                corrected_doc = f"{receipt_document}-COR"
                receipts.append(
                    {
                        "id": stable_id(config, "receipt_transaction", corrected_doc),
                        "source_system_id": source_system_id,
                        "source_load_id": source_load_id,
                        "po_line_id": line.po_line_id,
                        "receipt_document": corrected_doc,
                        "receipt_item_sequence": "1",
                        "transaction_type": "correction",
                        "source_quantity": qty(max(1.0, quantity * 0.02)),
                        "source_uom": "EA",
                        "base_quantity": qty(max(1.0, quantity * 0.02)),
                        "posted_at": timestamp_for(add_days(posted_day, 1), 16),
                        "corrects_receipt_id": receipt_id,
                        "late_receipt_flag": "false",
                        "scenario_ids": ";".join(line.scenario_types),
                    }
                )
            if reversal_scenario or rng.random() < reversal_rate:
                reversed_doc = f"{receipt_document}-REV"
                receipts.append(
                    {
                        "id": stable_id(config, "receipt_transaction", reversed_doc),
                        "source_system_id": source_system_id,
                        "source_load_id": source_load_id,
                        "po_line_id": line.po_line_id,
                        "receipt_document": reversed_doc,
                        "receipt_item_sequence": "1",
                        "transaction_type": "reversal",
                        "source_quantity": qty(-quantity),
                        "source_uom": "EA",
                        "base_quantity": qty(-quantity),
                        "posted_at": timestamp_for(add_days(posted_day, 2), 11),
                        "corrects_receipt_id": receipt_id,
                        "late_receipt_flag": "false",
                        "scenario_ids": ";".join(line.scenario_types),
                    }
                )

    return {
        "supplier_commitment_observations": commitments,
        "receipt_transactions": receipts,
        "receipt_allocations": allocations,
    }
