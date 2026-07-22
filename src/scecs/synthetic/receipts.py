"""Supplier commitments, receipt transactions and receipt allocations."""

from __future__ import annotations

from datetime import date
from random import Random

from scecs.synthetic._util import add_days, date_iso, parse_date, parse_timestamp, qty, stable_id, timestamp_for
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.purchase_orders import LineSnapshot
from scecs.synthetic.types import DatasetMap, Record


def _receipt_plan(line: LineSnapshot, rng: Random) -> tuple[float, int]:
    receipt_evidence_scenarios = {
        "supplier_commitment_breach",
        "supplier_deterioration",
        "receipt_correction",
        "receipt_reversal",
    }
    needs_receipt_evidence = bool(set(line.scenario_types) & receipt_evidence_scenarios)
    if line.line_status == "cancelled":
        if needs_receipt_evidence:
            return line.base_quantity * 0.4, 1
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
    hidden_supplier_archetypes: dict[str, str],
) -> DatasetMap:
    """Generate supplier commitments, receipts and allocations."""

    schedule_by_id = {str(row["id"]): row for row in delivery_schedules}
    commitments: list[Record] = []
    receipts: list[Record] = []
    future_receipts: list[Record] = []
    allocations: list[Record] = []
    receipt_sequence = 0
    schedule_remaining = {
        str(row["id"]): float(str(row["scheduled_quantity"]))
        for row in delivery_schedules
    }

    for line in line_snapshots:
        need_date = parse_date(line.need_date)
        expected_date = parse_date(line.expected_date)
        commitment_missing = "missing_supplier_signal" in line.scenario_types or rng.random() < 0.06
        if "supplier_commitment_breach" in line.scenario_types:
            commitment_missing = False
        if not commitment_missing:
            schedule_id = line.schedule_ids[0] if line.schedule_ids and rng.random() < 0.8 else ""
            committed_date = expected_date
            if "supplier_commitment_breach" in line.scenario_types:
                committed_date = add_days(need_date, -2)
            observed_day = min(add_days(need_date, -rng.randint(3, 20)), config.as_of_date)
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
                    "observed_at": timestamp_for(observed_day, 10),
                    "supersedes_commitment_id": "",
                    "scenario_ids": ";".join(line.scenario_ids),
                    "scenario_types": ";".join(line.scenario_types),
                }
            )

        total_receipt_quantity, receipt_count = _receipt_plan(line, rng)
        if receipt_count == 0 or total_receipt_quantity <= 0:
            continue
        per_receipt = total_receipt_quantity / receipt_count
        for receipt_index in range(1, receipt_count + 1):
            receipt_sequence += 1
            receipt_document = f"RCV-{receipt_sequence:09d}"
            late_probability = {
                "stable": 0.09,
                "average": 0.16,
                "volatile": 0.27,
                "fragile": 0.40,
            }[hidden_supplier_archetypes[line.supplier_id]]
            if "supplier_deterioration" in line.scenario_types:
                late_probability += 0.20
            arrival_offset = rng.randint(1, 8) if rng.random() < min(late_probability, 0.75) else -rng.randint(0, 8)
            if "supplier_deterioration" in line.scenario_types:
                arrival_offset = rng.randint(2, 10)
            if "supplier_commitment_breach" in line.scenario_types:
                arrival_offset = 9
            posted_day = add_days(expected_date, arrival_offset)
            if "supplier_deterioration" in line.scenario_types and posted_day <= need_date:
                posted_day = add_days(need_date, rng.randint(2, 10))
            posted_day = _cap_historical_posted_day(config, rng, line, posted_day)
            receipt_id = stable_id(config, "receipt_transaction", receipt_document)
            quantity = per_receipt
            receipt_row = _receipt_row(
                source_system_id=source_system_id,
                source_load_id=source_load_id,
                receipt_id=receipt_id,
                line=line,
                receipt_document=receipt_document,
                transaction_type="receipt",
                quantity=quantity,
                posted_at=timestamp_for(posted_day, 14, receipt_index),
                corrects_receipt_id="",
                late_receipt_flag=posted_day > need_date,
            )
            original_allocations: list[Record] = []
            if _is_as_of_visible(receipt_row["posted_at"], config):
                receipts.append(receipt_row)
                original_allocations = _allocate_receipt_quantity(
                    config,
                    receipt_id=receipt_id,
                    line=line,
                    quantity=quantity,
                    schedule_by_id=schedule_by_id,
                    schedule_remaining=schedule_remaining,
                )
                allocations.extend(original_allocations)
            else:
                future_receipts.append(_future_receipt_row(config, receipt_row, line))

            correction_scenario = "receipt_correction" in line.scenario_types
            reversal_scenario = "receipt_reversal" in line.scenario_types
            correction_rate = config.scenario_rates.receipt_correction_rate
            reversal_rate = config.scenario_rates.receipt_reversal_rate
            if correction_scenario or rng.random() < correction_rate:
                corrected_doc = f"{receipt_document}-COR"
                correction_quantity = max(1.0, quantity * 0.02)
                correction_id = stable_id(config, "receipt_transaction", corrected_doc)
                correction_row = _receipt_row(
                    source_system_id=source_system_id,
                    source_load_id=source_load_id,
                    receipt_id=correction_id,
                    line=line,
                    receipt_document=corrected_doc,
                    transaction_type="correction",
                    quantity=correction_quantity,
                    posted_at=timestamp_for(_cap_historical_posted_day(config, rng, line, add_days(posted_day, 1)), 16),
                    corrects_receipt_id=receipt_id,
                    late_receipt_flag=False,
                )
                if _is_as_of_visible(correction_row["posted_at"], config):
                    receipts.append(correction_row)
                    correction_allocations = _allocate_receipt_quantity(
                        config,
                        receipt_id=correction_id,
                        line=line,
                        quantity=correction_quantity,
                        schedule_by_id=schedule_by_id,
                        schedule_remaining=schedule_remaining,
                        corrected_receipt_id=receipt_id,
                    )
                    allocations.extend(correction_allocations)
                else:
                    future_receipts.append(_future_receipt_row(config, correction_row, line))
            if reversal_scenario or rng.random() < reversal_rate:
                reversed_doc = f"{receipt_document}-REV"
                reversal_id = stable_id(config, "receipt_transaction", reversed_doc)
                reversal_row = _receipt_row(
                    source_system_id=source_system_id,
                    source_load_id=source_load_id,
                    receipt_id=reversal_id,
                    line=line,
                    receipt_document=reversed_doc,
                    transaction_type="reversal",
                    quantity=-quantity,
                    posted_at=timestamp_for(_cap_historical_posted_day(config, rng, line, add_days(posted_day, 2)), 11),
                    corrects_receipt_id=receipt_id,
                    late_receipt_flag=False,
                )
                if _is_as_of_visible(reversal_row["posted_at"], config):
                    receipts.append(reversal_row)
                    reversal_allocations = _reverse_original_allocations(
                        config,
                        reversal_id=reversal_id,
                        line=line,
                        original_receipt_id=receipt_id,
                        original_allocations=original_allocations,
                        schedule_remaining=schedule_remaining,
                    )
                    allocations.extend(reversal_allocations)
                else:
                    future_receipts.append(_future_receipt_row(config, reversal_row, line))

    _ensure_open_line_future_receipts(
        config,
        rng,
        line_snapshots=line_snapshots,
        visible_receipts=receipts,
        future_receipts=future_receipts,
        hidden_supplier_archetypes=hidden_supplier_archetypes,
    )

    return {
        "supplier_commitment_observations": commitments,
        "receipt_transactions": receipts,
        "receipt_allocations": allocations,
        "future_receipt_outcomes": future_receipts,
    }


def _receipt_row(
    *,
    source_system_id: str,
    source_load_id: str,
    receipt_id: str,
    line: LineSnapshot,
    receipt_document: str,
    transaction_type: str,
    quantity: float,
    posted_at: str,
    corrects_receipt_id: str,
    late_receipt_flag: bool,
) -> Record:
    return {
        "id": receipt_id,
        "source_system_id": source_system_id,
        "source_load_id": source_load_id,
        "po_line_id": line.po_line_id,
        "receipt_document": receipt_document,
        "receipt_item_sequence": "1",
        "transaction_type": transaction_type,
        "source_quantity": qty(quantity),
        "source_uom": "EA",
        "base_quantity": qty(quantity),
        "posted_at": posted_at,
        "corrects_receipt_id": corrects_receipt_id,
        "late_receipt_flag": "true" if late_receipt_flag else "false",
        "scenario_ids": ";".join(line.scenario_ids),
        "scenario_types": ";".join(line.scenario_types),
    }


def _cap_historical_posted_day(
    config: SyntheticGeneratorConfig,
    rng: Random,
    line: LineSnapshot,
    posted_day: date,
) -> date:
    if line.line_status in {"open", "on_hold"} or parse_date(posted_day) <= config.as_of_date:
        return posted_day
    need_date = parse_date(line.need_date)
    if "supplier_deterioration" in line.scenario_types and need_date < config.as_of_date:
        return min(config.as_of_date, add_days(need_date, rng.randint(2, 10)))
    return add_days(config.as_of_date, -rng.randint(1, 30))


def _future_receipt_row(config: SyntheticGeneratorConfig, receipt: Record, line: LineSnapshot) -> Record:
    return {
        "id": stable_id(config, "future_receipt_outcome", str(receipt["id"])),
        "operational_receipt_id": "",
        "po_line_id": receipt["po_line_id"],
        "receipt_document": receipt["receipt_document"],
        "receipt_item_sequence": receipt["receipt_item_sequence"],
        "transaction_type": receipt["transaction_type"],
        "source_quantity": receipt["source_quantity"],
        "source_uom": receipt["source_uom"],
        "base_quantity": receipt["base_quantity"],
        "posted_at": receipt["posted_at"],
        "corrects_receipt_id": receipt["corrects_receipt_id"],
        "late_receipt_flag": receipt["late_receipt_flag"],
        "need_date": line.need_date,
        "evaluation_only_flag": "true",
        "source_visibility": "post_as_of_hidden_realisation",
        "scenario_ids": receipt["scenario_ids"],
        "scenario_types": receipt["scenario_types"],
    }


def _is_as_of_visible(timestamp: object, config: SyntheticGeneratorConfig) -> bool:
    return parse_timestamp(timestamp) <= parse_timestamp(config.as_of_timestamp)


def _ensure_open_line_future_receipts(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    line_snapshots: list[LineSnapshot],
    visible_receipts: list[Record],
    future_receipts: list[Record],
    hidden_supplier_archetypes: dict[str, str],
) -> None:
    future_line_ids = {str(row["po_line_id"]) for row in future_receipts if row["transaction_type"] == "receipt"}
    visible_quantity_by_line: dict[str, float] = {}
    for receipt in visible_receipts:
        visible_quantity_by_line[str(receipt["po_line_id"])] = visible_quantity_by_line.get(
            str(receipt["po_line_id"]),
            0.0,
        ) + float(str(receipt["base_quantity"]))
    lateness_probability = {"stable": 0.08, "average": 0.14, "volatile": 0.23, "fragile": 0.35}
    for line in line_snapshots:
        if line.line_status not in {"open", "on_hold"} or line.po_line_id in future_line_ids:
            continue
        residual = max(1.0, line.base_quantity - visible_quantity_by_line.get(line.po_line_id, 0.0))
        probability = lateness_probability[hidden_supplier_archetypes[line.supplier_id]]
        probability += 0.18 if "supplier_deterioration" in line.scenario_types else 0.0
        probability += 0.12 if "supplier_commitment_breach" in line.scenario_types else 0.0
        posted_day = add_days(config.as_of_date, rng.randint(1, 21))
        if rng.random() < min(probability, 0.82):
            posted_day = max(posted_day, add_days(parse_date(line.need_date), rng.randint(1, 14)))
        else:
            posted_day = min(posted_day, parse_date(line.need_date))
            if posted_day <= config.as_of_date:
                posted_day = add_days(config.as_of_date, rng.randint(1, 7))
        receipt_id = stable_id(config, "future_receipt_realisation", line.canonical_line_key)
        receipt = _receipt_row(
            source_system_id="",
            source_load_id="",
            receipt_id=receipt_id,
            line=line,
            receipt_document=f"REAL-{line.canonical_line_key}",
            transaction_type="receipt",
            quantity=residual,
            posted_at=timestamp_for(posted_day, 15),
            corrects_receipt_id="",
            late_receipt_flag=posted_day > parse_date(line.need_date),
        )
        future_receipts.append(_future_receipt_row(config, receipt, line))


def _allocate_receipt_quantity(
    config: SyntheticGeneratorConfig,
    *,
    receipt_id: str,
    line: LineSnapshot,
    quantity: float,
    schedule_by_id: dict[str, Record],
    schedule_remaining: dict[str, float],
    corrected_receipt_id: str = "",
) -> list[Record]:
    remaining = quantity
    rows: list[Record] = []
    sequence = 1
    for schedule_id in line.schedule_ids:
        if remaining <= 0:
            break
        schedule = schedule_by_id[schedule_id]
        if str(schedule["po_line_id"]) != line.po_line_id:
            raise ValueError("Receipt allocation schedule belongs to a different PO line.")
        capacity = max(schedule_remaining[schedule_id], 0.0)
        if capacity <= 0:
            continue
        allocated = min(remaining, capacity)
        schedule_remaining[schedule_id] = round(schedule_remaining[schedule_id] - allocated, 4)
        rows.append(
            _allocation_row(
                config,
                receipt_id,
                sequence,
                schedule_id,
                "schedule",
                allocated,
                line,
                corrected_receipt_id,
            )
        )
        remaining = round(remaining - allocated, 4)
        sequence += 1
    if remaining > 0:
        rows.append(
            _allocation_row(
                config,
                receipt_id,
                sequence,
                "",
                "line_residual",
                remaining,
                line,
                corrected_receipt_id,
            )
        )
    return rows


def _reverse_original_allocations(
    config: SyntheticGeneratorConfig,
    *,
    reversal_id: str,
    line: LineSnapshot,
    original_receipt_id: str,
    original_allocations: list[Record],
    schedule_remaining: dict[str, float],
) -> list[Record]:
    rows: list[Record] = []
    for sequence, original in enumerate(original_allocations, start=1):
        schedule_id = str(original["delivery_schedule_id"])
        allocated = float(str(original["allocated_base_quantity"]))
        if schedule_id:
            schedule_remaining[schedule_id] = round(schedule_remaining[schedule_id] + allocated, 4)
        rows.append(
            _allocation_row(
                config,
                reversal_id,
                sequence,
                schedule_id,
                str(original["allocation_bucket"]),
                allocated,
                line,
                original_receipt_id,
            )
        )
    return rows


def _allocation_row(
    config: SyntheticGeneratorConfig,
    receipt_id: str,
    sequence: int,
    schedule_id: str,
    bucket: str,
    allocated: float,
    line: LineSnapshot,
    corrected_receipt_id: str,
) -> Record:
    return {
        "id": stable_id(config, "receipt_allocation", f"{receipt_id}:{sequence}"),
        "receipt_transaction_id": receipt_id,
        "delivery_schedule_id": schedule_id,
        "allocation_sequence": sequence,
        "allocation_bucket": bucket,
        "allocated_base_quantity": qty(allocated),
        "po_line_id_for_validation": line.po_line_id,
        "corrected_receipt_id": corrected_receipt_id,
        "scenario_ids": ";".join(line.scenario_ids),
        "scenario_types": ";".join(line.scenario_types),
    }
