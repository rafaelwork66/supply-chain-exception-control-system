"""Dated demand requirement generation for synthetic source datasets."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import add_days, date_iso, qty, stable_id
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.purchase_orders import LineSnapshot
from scecs.synthetic.types import Record


def generate_demand_requirements(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    source_load_id: str,
    product_versions: list[Record],
    sites: list[Record],
    line_snapshots: list[LineSnapshot],
) -> list[Record]:
    """Generate near-term product-site demand requirements with seasonality and shocks."""

    rows: list[Record] = []
    scenario_by_product_site = _scenario_by_product_site(line_snapshots, "demand_shock")
    for product_version in product_versions:
        xyz = str(product_version["xyz_class"])
        category = str(product_version["category"])
        for site in sites:
            scenario_group = scenario_by_product_site.get((str(product_version["product_id"]), str(site["id"])))
            for bucket in range(1, 5):
                requirement_date = add_days(config.as_of_date, bucket * 7)
                base = {"X": 140.0, "Y": 90.0, "Z": 35.0}[xyz]
                seasonality = 1.0
                if requirement_date.month in {10, 11, 12}:
                    seasonality = 1.18
                elif requirement_date.month in {1, 2}:
                    seasonality = 0.92
                intermittency = 0.0 if xyz == "Z" and rng.random() < 0.35 else 1.0
                shock = 1.0
                if scenario_group is not None and bucket == 1:
                    shock = 2.4
                    intermittency = 1.0
                elif rng.random() < config.scenario_rates.demand_shock_rate:
                    shock = 1.8
                demand = max(0.0, base * seasonality * intermittency * shock * rng.uniform(0.65, 1.35))
                ref = f"DEM-{product_version['product_id']}-{site['site_code']}-{bucket}"
                rows.append(
                    {
                        "id": stable_id(config, "demand_requirement", ref),
                        "source_load_id": source_load_id,
                        "product_id": product_version["product_id"],
                        "site_id": site["id"],
                        "source_requirement_ref": ref,
                        "requirement_version": 1,
                        "requirement_type": "forecast" if bucket > 1 else "firm",
                        "required_date": date_iso(requirement_date),
                        "required_quantity": qty(demand),
                        "corrects_requirement_id": "",
                        "demand_class": xyz,
                        "product_category": category,
                        "demand_shock_flag": "true" if shock > 1.0 else "false",
                        "scenario_ids": ";".join(scenario_group[0]) if scenario_group is not None else "",
                        "scenario_types": ";".join(scenario_group[1]) if scenario_group is not None else "",
                    }
                )
    return rows


def _scenario_by_product_site(
    line_snapshots: list[LineSnapshot],
    scenario_type: str,
) -> dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]]:
    grouped: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    for line in line_snapshots:
        ids = [
            scenario_id
            for scenario_id, current_type in zip(line.scenario_ids, line.scenario_types, strict=True)
            if current_type == scenario_type
        ]
        if not ids:
            continue
        key = (line.product_id, line.site_id)
        scenario_ids, scenario_types = grouped.setdefault(key, ([], []))
        scenario_ids.extend(ids)
        scenario_types.append(scenario_type)
    return {
        key: (tuple(scenario_ids), tuple(dict.fromkeys(scenario_types)))
        for key, (scenario_ids, scenario_types) in grouped.items()
    }
