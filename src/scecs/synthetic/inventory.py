"""Inventory snapshot generation for synthetic source datasets."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import add_days, qty, stable_id, timestamp_for
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.purchase_orders import LineSnapshot
from scecs.synthetic.types import Record


def generate_inventory_snapshots(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    source_load_id: str,
    products: list[Record],
    sites: list[Record],
    policies: list[Record],
    line_snapshots: list[LineSnapshot],
) -> list[Record]:
    """Generate product-site inventory observations at the operational snapshot."""

    policy_by_key = {(policy["product_id"], policy["site_id"]): policy for policy in policies}
    scenario_by_product_site = _scenario_by_product_site(line_snapshots)
    reallocation_lines = [
        line for line in line_snapshots if "inventory_reallocation_opportunity" in line.scenario_types
    ]
    reallocation_surplus: dict[tuple[str, str], tuple[str, ...]] = {}
    for line in reallocation_lines:
        other_sites = [site for site in sites if str(site["id"]) != line.site_id]
        if other_sites:
            reallocation_surplus[(line.product_id, str(other_sites[0]["id"]))] = _scenario_ids_for(
                line,
                "inventory_reallocation_opportunity",
            )
    rows: list[Record] = []
    for product in products:
        for site in sites:
            key = (product["id"], site["id"])
            policy = policy_by_key[key]
            safety = float(str(policy["safety_stock_quantity"]))
            scenario_group = scenario_by_product_site.get((str(product["id"]), str(site["id"])), {})
            missing_ids = scenario_group.get("missing_inventory_signal", ())
            reallocation_ids = scenario_group.get("inventory_reallocation_opportunity", ())
            false_positive_ids = scenario_group.get("false_positive_source_data_correction", ())
            snapshot_version = 1
            if missing_ids:
                rows.append(
                    _snapshot_row(
                        config,
                        source_load_id=source_load_id,
                        product_id=str(product["id"]),
                        site_id=str(site["id"]),
                        snapshot_version=snapshot_version,
                        on_hand=max(safety, 1.0),
                        allocated=0.0,
                        in_transit=safety * 0.2,
                        corrects_snapshot_id="",
                        missing_signal=True,
                        scenario_ids=missing_ids,
                        scenario_types=("missing_inventory_signal",),
                        snapshot_at=timestamp_for(add_days(config.as_of_date, -2), 18),
                    )
                )
                snapshot_version += 1
                if not reallocation_ids and not false_positive_ids:
                    continue
            shock = 0.55 if rng.random() < config.scenario_rates.missing_inventory_signal_rate else 1.0
            on_hand = max(0.0, safety * rng.uniform(0.4, 3.2) * shock)
            allocated = max(0.0, on_hand * rng.uniform(0.05, 0.55))
            current_scenario_ids: tuple[str, ...] = ()
            current_scenario_types: tuple[str, ...] = ()
            if reallocation_ids:
                on_hand = safety * 0.25
                allocated = on_hand
                current_scenario_ids = reallocation_ids
                current_scenario_types = ("inventory_reallocation_opportunity",)
            surplus_ids = reallocation_surplus.get((str(product["id"]), str(site["id"])))
            if surplus_ids is not None:
                current_scenario_ids = surplus_ids
                current_scenario_types = ("inventory_reallocation_opportunity",)
                on_hand = safety * 4.5
                allocated = safety * 0.25
            if false_positive_ids:
                initial = _snapshot_row(
                    config,
                    source_load_id=source_load_id,
                    product_id=str(product["id"]),
                    site_id=str(site["id"]),
                    snapshot_version=snapshot_version,
                    on_hand=safety * 0.1,
                    allocated=safety * 0.1,
                    in_transit=0.0,
                    corrects_snapshot_id="",
                    missing_signal=False,
                    scenario_ids=false_positive_ids,
                    scenario_types=("false_positive_source_data_correction",),
                    snapshot_at=config.as_of_timestamp,
                )
                rows.append(initial)
                snapshot_version += 1
                rows.append(
                    _snapshot_row(
                        config,
                        source_load_id=source_load_id,
                        product_id=str(product["id"]),
                        site_id=str(site["id"]),
                        snapshot_version=snapshot_version,
                        on_hand=safety * 4.0,
                        allocated=safety * 0.1,
                        in_transit=safety,
                        corrects_snapshot_id=str(initial["id"]),
                        missing_signal=False,
                        scenario_ids=false_positive_ids,
                        scenario_types=("false_positive_source_data_correction",),
                        snapshot_at=config.as_of_timestamp,
                    )
                )
                continue
            rows.append(
                _snapshot_row(
                    config,
                    source_load_id=source_load_id,
                    product_id=str(product["id"]),
                    site_id=str(site["id"]),
                    snapshot_version=snapshot_version,
                    on_hand=on_hand,
                    allocated=allocated,
                    in_transit=safety * rng.uniform(0.0, 1.4),
                    corrects_snapshot_id="",
                    missing_signal=shock < 1.0,
                    scenario_ids=current_scenario_ids,
                    scenario_types=current_scenario_types,
                    snapshot_at=config.as_of_timestamp,
                )
            )
    return rows


def _snapshot_row(
    config: SyntheticGeneratorConfig,
    *,
    source_load_id: str,
    product_id: str,
    site_id: str,
    snapshot_version: int,
    on_hand: float,
    allocated: float,
    in_transit: float,
    corrects_snapshot_id: str,
    missing_signal: bool,
    scenario_ids: tuple[str, ...],
    scenario_types: tuple[str, ...],
    snapshot_at: str,
) -> Record:
    available = max(0.0, on_hand - allocated)
    key = f"{product_id}:{site_id}:{snapshot_version}"
    return {
        "id": stable_id(config, "inventory_snapshot", key),
        "source_load_id": source_load_id,
        "product_id": product_id,
        "site_id": site_id,
        "snapshot_at": snapshot_at,
        "snapshot_version": snapshot_version,
        "on_hand_quantity": qty(on_hand),
        "allocated_quantity": qty(allocated),
        "available_quantity": qty(available),
        "in_transit_quantity": qty(in_transit),
        "corrects_snapshot_id": corrects_snapshot_id,
        "missing_signal_flag": "true" if missing_signal else "false",
        "scenario_ids": ";".join(scenario_ids),
        "scenario_types": ";".join(scenario_types),
    }


def _scenario_by_product_site(line_snapshots: list[LineSnapshot]) -> dict[tuple[str, str], dict[str, tuple[str, ...]]]:
    scenario_types = {
        "missing_inventory_signal",
        "inventory_reallocation_opportunity",
        "false_positive_source_data_correction",
    }
    grouped: dict[tuple[str, str], dict[str, list[str]]] = {}
    for line in line_snapshots:
        key = (line.product_id, line.site_id)
        for scenario_type in scenario_types:
            ids = _scenario_ids_for(line, scenario_type)
            if ids:
                grouped.setdefault(key, {}).setdefault(scenario_type, []).extend(ids)
    return {
        key: {scenario_type: tuple(ids) for scenario_type, ids in values.items()}
        for key, values in grouped.items()
    }


def _scenario_ids_for(line: LineSnapshot, scenario_type: str) -> tuple[str, ...]:
    return tuple(
        scenario_id
        for scenario_id, current_type in zip(line.scenario_ids, line.scenario_types, strict=True)
        if current_type == scenario_type
    )
