"""Inventory snapshot generation for synthetic source datasets."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import qty, stable_id
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.types import Record


def generate_inventory_snapshots(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    source_load_id: str,
    products: list[Record],
    sites: list[Record],
    policies: list[Record],
) -> list[Record]:
    """Generate product-site inventory observations at the operational snapshot."""

    policy_by_key = {(policy["product_id"], policy["site_id"]): policy for policy in policies}
    rows: list[Record] = []
    for product in products:
        for site in sites:
            key = (product["id"], site["id"])
            policy = policy_by_key[key]
            safety = float(str(policy["safety_stock_quantity"]))
            shock = 0.55 if rng.random() < config.scenario_rates.missing_inventory_signal_rate else 1.0
            on_hand = max(0.0, safety * rng.uniform(0.4, 3.2) * shock)
            allocated = max(0.0, on_hand * rng.uniform(0.05, 0.55))
            available = max(0.0, on_hand - allocated)
            rows.append(
                {
                    "id": stable_id(config, "inventory_snapshot", f"{product['id']}:{site['id']}"),
                    "source_load_id": source_load_id,
                    "product_id": product["id"],
                    "site_id": site["id"],
                    "snapshot_at": config.as_of_timestamp,
                    "snapshot_version": 1,
                    "on_hand_quantity": qty(on_hand),
                    "allocated_quantity": qty(allocated),
                    "available_quantity": qty(available),
                    "in_transit_quantity": qty(safety * rng.uniform(0.0, 1.4)),
                    "corrects_snapshot_id": "",
                    "missing_signal_flag": "true" if shock < 1.0 else "false",
                }
            )
    return rows
