"""Top-level orchestration for deterministic synthetic source datasets."""

from __future__ import annotations

from dataclasses import replace

from scecs.synthetic._util import stable_id
from scecs.synthetic.config import SyntheticGeneratorConfig, configuration_hash
from scecs.synthetic.demand import generate_demand_requirements
from scecs.synthetic.inventory import generate_inventory_snapshots
from scecs.synthetic.master_data import generate_master_data
from scecs.synthetic.organisation import generate_organisation
from scecs.synthetic.outcomes import generate_outcomes
from scecs.synthetic.purchase_orders import LineSnapshot, generate_purchase_orders
from scecs.synthetic.random_context import RandomContext
from scecs.synthetic.receipts import generate_receipts_and_commitments
from scecs.synthetic.scenarios import (
    MANDATORY_SCENARIO_TYPES,
    assign_line_scenarios,
    build_scenario_registry,
    scenario_details_by_line,
)
from scecs.synthetic.supplier_performance import generate_supplier_performance
from scecs.synthetic.types import DatasetMap, GeneratedDatasetBundle, Record


def generate_dataset_bundle(config: SyntheticGeneratorConfig) -> GeneratedDatasetBundle:
    """Generate all synthetic source datasets for a configuration."""

    random_context = RandomContext(config.seed, config.generator_version)
    source_systems, pipeline_runs, source_loads = _generate_control_records(config)
    source_system_id = str(source_systems[0]["id"])
    source_load_by_type = {str(load["dataset_type"]): str(load["id"]) for load in source_loads}

    organisation = generate_organisation(config)
    master, hidden_supplier_archetypes = generate_master_data(
        config,
        random_context.stream("master"),
        organisation["sites"],
    )

    line_keys = [f"POL-{line_number:08d}" for line_number in range(1, config.po_line_count + 1)]
    scenario_map = assign_line_scenarios(config, random_context.stream("scenario"), line_keys)
    scenario_registry, scenario_assignments = build_scenario_registry(config, scenario_map)
    scenario_details = scenario_details_by_line(scenario_assignments, scenario_registry)

    procurement, line_snapshots = generate_purchase_orders(
        config,
        random_context.stream("purchase_orders"),
        source_system_id=source_system_id,
        source_load_id=source_load_by_type["purchase_orders"],
        suppliers=master["suppliers"],
        products=master["products"],
        sites=organisation["sites"],
        uom_conversions=master["uom_conversions"],
        scenario_details=scenario_details,
    )
    scenario_registry, scenario_assignments, line_snapshots = _prune_inventory_signal_conflicts(
        scenario_registry,
        scenario_assignments,
        procurement,
        line_snapshots,
    )

    receipts = generate_receipts_and_commitments(
        config,
        random_context.stream("receipts"),
        source_system_id=source_system_id,
        source_load_id=source_load_by_type["receipts"],
        line_snapshots=line_snapshots,
        delivery_schedules=procurement["delivery_schedules"],
        hidden_supplier_archetypes=hidden_supplier_archetypes,
    )
    inventory = generate_inventory_snapshots(
        config,
        random_context.stream("inventory"),
        source_load_id=source_load_by_type["inventory_snapshots"],
        products=master["products"],
        sites=organisation["sites"],
        policies=master["product_site_inventory_policies"],
        line_snapshots=line_snapshots,
    )
    demand = generate_demand_requirements(
        config,
        random_context.stream("demand"),
        source_load_id=source_load_by_type["demand_requirements"],
        product_versions=master["product_versions"],
        sites=organisation["sites"],
        line_snapshots=line_snapshots,
    )
    supplier_performance = generate_supplier_performance(
        config,
        random_context.stream("supplier_performance"),
        suppliers=master["suppliers"],
        sites=organisation["sites"],
        hidden_supplier_archetypes=hidden_supplier_archetypes,
        line_snapshots=line_snapshots,
        receipt_transactions=receipts["receipt_transactions"],
    )
    outcomes = generate_outcomes(
        config,
        random_context.stream("outcomes"),
        line_snapshots=line_snapshots,
        hidden_supplier_archetypes=hidden_supplier_archetypes,
    )

    datasets: DatasetMap = {
        "source_systems": source_systems,
        "pipeline_runs": pipeline_runs,
        "source_loads": source_loads,
        **organisation,
        **master,
        **procurement,
        **receipts,
        "inventory_snapshots": inventory,
        "demand_requirements": demand,
        "supplier_performance_snapshots": supplier_performance,
        "scenario_registry": scenario_registry,
        "scenario_assignments": scenario_assignments,
        "synthetic_outcome_observations": outcomes,
    }
    _update_source_load_counts(datasets)
    return GeneratedDatasetBundle(
        datasets=datasets,
        config_hash=configuration_hash(config),
        generator_version=config.generator_version,
        seed=config.seed,
        as_of_timestamp=config.as_of_timestamp,
        scenario_types=MANDATORY_SCENARIO_TYPES,
    )


def _prune_inventory_signal_conflicts(
    scenario_registry: list[Record],
    scenario_assignments: list[Record],
    procurement: DatasetMap,
    line_snapshots: list[LineSnapshot],
) -> tuple[list[Record], list[Record], list[LineSnapshot]]:
    """Remove incompatible missing-inventory scenarios at product-site grain."""

    lines_by_product_site: dict[tuple[str, str], list[LineSnapshot]] = {}
    for line in line_snapshots:
        lines_by_product_site.setdefault((line.product_id, line.site_id), []).append(line)

    scenario_ids_to_remove: set[str] = set()
    current_inventory_types = {
        "false_positive_source_data_correction",
        "inventory_reallocation_opportunity",
    }
    for lines in lines_by_product_site.values():
        scenario_types = {scenario_type for line in lines for scenario_type in line.scenario_types}
        has_missing_inventory = "missing_inventory_signal" in scenario_types
        has_current_inventory_scenario = bool(scenario_types & current_inventory_types)
        if not has_missing_inventory or not has_current_inventory_scenario:
            continue
        for line in lines:
            scenario_ids_to_remove.update(
                scenario_id
                for scenario_id, scenario_type in zip(line.scenario_ids, line.scenario_types, strict=True)
                if scenario_type == "missing_inventory_signal"
            )

    if not scenario_ids_to_remove:
        return scenario_registry, scenario_assignments, line_snapshots

    pruned_registry = [
        row for row in scenario_registry if str(row["scenario_id"]) not in scenario_ids_to_remove
    ]
    pruned_assignments = [
        row for row in scenario_assignments if str(row["scenario_id"]) not in scenario_ids_to_remove
    ]
    pruned_snapshots = [
        replace(
            line,
            scenario_ids=tuple(
                scenario_id
                for scenario_id in line.scenario_ids
                if scenario_id not in scenario_ids_to_remove
            ),
            scenario_types=tuple(
                scenario_type
                for scenario_id, scenario_type in zip(line.scenario_ids, line.scenario_types, strict=True)
                if scenario_id not in scenario_ids_to_remove
            ),
        )
        for line in line_snapshots
    ]
    for dataset_name in ("purchase_order_line_versions", "delivery_schedules"):
        for row in procurement[dataset_name]:
            _remove_scenario_ids_from_row(row, scenario_ids_to_remove)
    return pruned_registry, pruned_assignments, pruned_snapshots


def _remove_scenario_ids_from_row(row: Record, scenario_ids_to_remove: set[str]) -> None:
    scenario_ids = str(row.get("scenario_ids", "")).split(";")
    scenario_types = str(row.get("scenario_types", "")).split(";")
    remaining = [
        (scenario_id, scenario_type)
        for scenario_id, scenario_type in zip(scenario_ids, scenario_types, strict=True)
        if scenario_id and scenario_id not in scenario_ids_to_remove
    ]
    row["scenario_ids"] = ";".join(scenario_id for scenario_id, _ in remaining)
    row["scenario_types"] = ";".join(scenario_type for _, scenario_type in remaining)


def _update_source_load_counts(datasets: DatasetMap) -> None:
    row_count_by_type = {
        "purchase_orders": sum(
            len(datasets[name])
            for name in (
                "purchase_orders",
                "purchase_order_versions",
                "purchase_order_lines",
                "purchase_order_line_aliases",
                "purchase_order_line_versions",
                "delivery_schedules",
            )
        ),
        "receipts": sum(
            len(datasets[name])
            for name in (
                "supplier_commitment_observations",
                "receipt_transactions",
                "receipt_allocations",
            )
        ),
        "inventory_snapshots": len(datasets["inventory_snapshots"]),
        "demand_requirements": len(datasets["demand_requirements"]),
        "supplier_performance": len(datasets["supplier_performance_snapshots"]),
        "master_data": sum(
            len(datasets[name])
            for name in (
                "sites",
                "suppliers",
                "supplier_versions",
                "products",
                "product_versions",
                "uom_conversions",
                "product_site_inventory_policies",
                "users",
                "ownership_mappings",
                "calendar_versions",
                "rule_versions",
            )
        ),
    }
    for row in datasets["source_loads"]:
        row["row_count"] = row_count_by_type[str(row["dataset_type"])]


def _generate_control_records(
    config: SyntheticGeneratorConfig,
) -> tuple[list[Record], list[Record], list[Record]]:
    source_system: Record = {
        "id": stable_id(config, "source_system", "SYNTHETIC_ERP"),
        "source_code": "SYNTHETIC_ERP",
        "display_name": "Synthetic ERP Extracts",
        "source_type": "synthetic_source",
        "is_active": "true",
    }
    pipeline_run: Record = {
        "id": stable_id(config, "pipeline_run", f"synthetic:{config.seed}:{config.as_of_date.isoformat()}"),
        "run_reference": f"SYN-GEN-{config.generator_version}-{config.seed}-{config.as_of_date.isoformat()}",
        "run_type": "synthetic_generation",
        "trigger_type": "manual",
        "status": "success",
        "started_at": config.as_of_timestamp,
        "finished_at": config.as_of_timestamp,
        "release_version": config.generator_version,
        "configuration_hash": configuration_hash(config),
        "is_publication_eligible": "false",
    }
    dataset_types = (
        "purchase_orders",
        "receipts",
        "inventory_snapshots",
        "demand_requirements",
        "supplier_performance",
        "master_data",
    )
    source_loads = [
        {
            "id": stable_id(config, "source_load", dataset_type),
            "pipeline_run_id": pipeline_run["id"],
            "source_system_id": source_system["id"],
            "dataset_type": dataset_type,
            "object_ref": f"synthetic://{dataset_type}/{config.seed}",
            "content_hash": "computed-at-export",
            "schema_version": "synthetic-source-v1",
            "extracted_at": config.as_of_timestamp,
            "received_at": config.as_of_timestamp,
            "row_count": 0,
        }
        for dataset_type in dataset_types
    ]
    return [source_system], [pipeline_run], source_loads
