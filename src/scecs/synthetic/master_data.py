"""Synthetic supplier, product and item-site policy generation."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import qty, stable_id, timestamp_for, weighted_choice
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.types import DatasetMap, Record


def generate_master_data(
    config: SyntheticGeneratorConfig,
    rng: Random,
    sites: list[Record],
) -> tuple[DatasetMap, dict[str, str]]:
    """Generate supplier and product master data plus hidden supplier archetypes."""

    active_from = timestamp_for(config.history_start)
    suppliers: list[Record] = []
    supplier_versions: list[Record] = []
    hidden_supplier_archetypes: dict[str, str] = {}
    archetypes = [("stable", 0.55), ("average", 0.30), ("volatile", 0.10), ("fragile", 0.05)]
    categories = ["local", "interstate", "import"]
    for index in range(1, config.supplier_count + 1):
        code = f"SYN-SUP-{index:04d}"
        supplier_id = stable_id(config, "supplier", code)
        supplier_category = categories[(index + rng.randrange(3)) % len(categories)]
        archetype = weighted_choice(rng, archetypes)
        hidden_supplier_archetypes[supplier_id] = archetype
        suppliers.append({"id": supplier_id, "supplier_code": code, "synthetic_data_flag": "true"})
        supplier_versions.append(
            {
                "id": stable_id(config, "supplier_version", code),
                "supplier_id": supplier_id,
                "display_name": f"Synthetic Supplier {index:04d}",
                "supplier_category": supplier_category,
                "effective_from": active_from,
                "effective_to": "",
                "synthetic_data_flag": "true",
            }
        )

    product_categories = [
        ("resale_finished_goods", 0.45),
        ("components", 0.35),
        ("mro_consumables", 0.12),
        ("packaging", 0.08),
    ]
    abc_classes = [("A", 0.20), ("B", 0.30), ("C", 0.50)]
    xyz_classes = [("X", 0.45), ("Y", 0.35), ("Z", 0.20)]
    criticalities = [("standard", 0.83), ("service_critical", 0.12), ("production_critical", 0.05)]

    products: list[Record] = []
    product_versions: list[Record] = []
    uom_conversions: list[Record] = []
    policies: list[Record] = []
    for index in range(1, config.product_count + 1):
        sku = f"SYN-SKU-{index:05d}"
        product_id = stable_id(config, "product", sku)
        category = weighted_choice(rng, product_categories)
        abc = weighted_choice(rng, abc_classes)
        xyz = weighted_choice(rng, xyz_classes)
        products.append({"id": product_id, "sku": sku, "synthetic_data_flag": "true"})
        product_versions.append(
            {
                "id": stable_id(config, "product_version", sku),
                "product_id": product_id,
                "description": f"Synthetic {category.replace('_', ' ')} item {index:05d}",
                "category": category,
                "base_uom": config.base_uom,
                "handling_precision": 4,
                "abc_class": abc,
                "xyz_class": xyz,
                "effective_from": active_from,
                "effective_to": "",
                "synthetic_data_flag": "true",
            }
        )
        for uom in config.purchase_uoms:
            factor = 1 if uom == "EA" else rng.choice([6, 12, 24, 48]) if uom == "CASE" else rng.choice([120, 240, 480])
            uom_conversions.append(
                {
                    "id": stable_id(config, "uom_conversion", f"{sku}:{uom}:EA"),
                    "product_id": product_id,
                    "from_uom": uom,
                    "to_uom": config.base_uom,
                    "conversion_factor": factor,
                    "effective_from": active_from,
                    "effective_to": "",
                }
            )
        for site in sites:
            criticality = weighted_choice(rng, criticalities)
            safety = {"A": 220, "B": 120, "C": 60}[abc] * (1.8 if criticality != "standard" else 1.0)
            safety *= 1.2 if xyz == "Z" else 1.0
            policy_key = f"{sku}:{site['site_code']}"
            policies.append(
                {
                    "id": stable_id(config, "inventory_policy", policy_key),
                    "product_id": product_id,
                    "site_id": site["id"],
                    "safety_stock_quantity": qty(safety + rng.randrange(0, 60)),
                    "policy_source": "synthetic_policy_v1",
                    "substitution_group": f"SUB-{(index - 1) // 10:04d}",
                    "criticality": criticality,
                    "effective_from": active_from,
                    "effective_to": "",
                }
            )

    return (
        {
            "suppliers": suppliers,
            "supplier_versions": supplier_versions,
            "products": products,
            "product_versions": product_versions,
            "uom_conversions": uom_conversions,
            "product_site_inventory_policies": policies,
        },
        hidden_supplier_archetypes,
    )
