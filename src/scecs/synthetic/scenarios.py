"""Controlled scenario assignment for synthetic operational data."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import add_days, date_iso, stable_id
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.types import Record

MANDATORY_SCENARIO_TYPES: tuple[str, ...] = (
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
)


def assign_line_scenarios(config: SyntheticGeneratorConfig, rng: Random, line_keys: list[str]) -> dict[str, list[str]]:
    """Assign controlled scenarios to line keys without encoding score or outcome labels."""

    assignments: dict[str, list[str]] = {key: [] for key in line_keys}
    shuffled = line_keys.copy()
    rng.shuffle(shuffled)
    active_window = line_keys[-max(len(MANDATORY_SCENARIO_TYPES), 1) :]
    mandatory_targets = active_window.copy()
    rng.shuffle(mandatory_targets)
    for scenario_type, line_key in zip(MANDATORY_SCENARIO_TYPES, mandatory_targets, strict=True):
        assignments[line_key].append(scenario_type)

    mandatory_target_set = set(mandatory_targets)
    rates = config.scenario_rates
    rate_by_type = {
        "demand_shock": rates.demand_shock_rate,
        "supplier_deterioration": rates.supplier_deterioration_rate,
        "missing_supplier_signal": rates.missing_supplier_signal_rate,
        "missing_inventory_signal": rates.missing_inventory_signal_rate,
        "split_schedule": rates.split_schedule_rate,
    }
    for key in shuffled:
        if key in mandatory_target_set:
            continue
        for scenario_type, rate in rate_by_type.items():
            if rng.random() < rate:
                assignments[key].append(scenario_type)
    return {key: values for key, values in assignments.items() if values}


def build_scenario_registry(
    config: SyntheticGeneratorConfig,
    scenario_map: dict[str, list[str]],
) -> tuple[list[Record], list[Record]]:
    """Create scenario registry and line assignment datasets."""

    registry: list[Record] = []
    assignments: list[Record] = []
    for line_key in sorted(scenario_map):
        for index, scenario_type in enumerate(scenario_map[line_key], start=1):
            scenario_id = stable_id(config, "scenario", f"{line_key}:{scenario_type}:{index}")
            start_date = add_days(config.history_end, -45 + index)
            end_date = add_days(start_date, 14)
            registry.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": scenario_type,
                    "latent_visible_classification": "visible" if "missing" not in scenario_type else "latent",
                    "affected_entity_type": "purchase_order_line",
                    "affected_key": line_key,
                    "start_date": date_iso(start_date),
                    "end_date": date_iso(end_date),
                    "seed_reference": f"{config.generator_version}:{config.seed}:scenario",
                    "intended_test_purpose": "controlled synthetic behaviour coverage",
                    "desired_score_result": "",
                }
            )
            assignments.append(
                {
                    "scenario_id": scenario_id,
                    "canonical_line_key": line_key,
                    "scenario_type": scenario_type,
                }
            )
    return registry, assignments


def scenario_details_by_line(
    scenario_assignments: list[Record],
    scenario_registry: list[Record],
) -> dict[str, list[Record]]:
    """Return scenario detail records grouped by canonical PO-line key."""

    registry_by_id = {str(row["scenario_id"]): row for row in scenario_registry}
    grouped: dict[str, list[Record]] = {}
    for assignment in scenario_assignments:
        line_key = str(assignment["canonical_line_key"])
        scenario_id = str(assignment["scenario_id"])
        scenario = registry_by_id[scenario_id]
        grouped.setdefault(line_key, []).append(
            {
                "scenario_id": scenario_id,
                "scenario_type": scenario["scenario_type"],
                "affected_entity_type": scenario["affected_entity_type"],
                "affected_key": scenario["affected_key"],
                "start_date": scenario["start_date"],
                "end_date": scenario["end_date"],
            }
        )
    return grouped


def scenario_ids(details: list[Record]) -> str:
    """Return semicolon-delimited scenario UUIDs for an operational row."""

    return ";".join(str(row["scenario_id"]) for row in details)


def scenario_types(details: list[Record]) -> str:
    """Return semicolon-delimited readable scenario labels for an operational row."""

    return ";".join(str(row["scenario_type"]) for row in details)
