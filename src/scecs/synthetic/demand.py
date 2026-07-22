"""Dated demand requirement generation for synthetic source datasets."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import add_days, date_iso, qty, stable_id
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.types import Record


def generate_demand_requirements(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    source_load_id: str,
    product_versions: list[Record],
    sites: list[Record],
) -> list[Record]:
    """Generate near-term product-site demand requirements with seasonality and shocks."""

    rows: list[Record] = []
    for product_version in product_versions:
        xyz = str(product_version["xyz_class"])
        category = str(product_version["category"])
        for site in sites:
            for bucket in range(1, 5):
                requirement_date = add_days(config.as_of_date, bucket * 7)
                base = {"X": 140.0, "Y": 90.0, "Z": 35.0}[xyz]
                seasonality = 1.0
                if requirement_date.month in {10, 11, 12}:
                    seasonality = 1.18
                elif requirement_date.month in {1, 2}:
                    seasonality = 0.92
                intermittency = 0.0 if xyz == "Z" and rng.random() < 0.35 else 1.0
                shock = 1.8 if rng.random() < config.scenario_rates.demand_shock_rate else 1.0
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
                    }
                )
    return rows
