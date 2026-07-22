"""Supplier performance observation generation."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import add_days, date_iso, stable_id
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.purchase_orders import LineSnapshot
from scecs.synthetic.types import Record


def generate_supplier_performance(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    suppliers: list[Record],
    sites: list[Record],
    hidden_supplier_archetypes: dict[str, str],
    line_snapshots: list[LineSnapshot],
    receipt_transactions: list[Record],
) -> list[Record]:
    """Generate trailing supplier performance snapshots from hidden behaviour."""

    rows: list[Record] = []
    line_by_id = {line.po_line_id: line for line in line_snapshots}
    history: dict[tuple[str, str], list[bool]] = {}
    for receipt in receipt_transactions:
        if receipt["transaction_type"] != "receipt":
            continue
        line = line_by_id[str(receipt["po_line_id"])]
        supplier_site_key = (line.supplier_id, line.site_id)
        history.setdefault(supplier_site_key, []).append(str(receipt["late_receipt_flag"]) != "true")
    archetype_prior = {"stable": 0.94, "average": 0.87, "volatile": 0.78, "fragile": 0.66}
    for supplier in suppliers:
        archetype = hidden_supplier_archetypes[str(supplier["id"])]
        for site in sites:
            observed = history.get((str(supplier["id"]), str(site["id"])), [])
            denominator = len(observed)
            if denominator == 0:
                denominator = rng.randint(6, 18)
                observed_rate = archetype_prior[archetype] + rng.uniform(-0.10, 0.08)
            else:
                observed_rate = sum(1 for ok in observed if ok) / denominator
            blended_rate = (observed_rate * min(denominator, 80) + archetype_prior[archetype] * 10) / (
                min(denominator, 80) + 10
            )
            noisy_rate = max(0.0, min(1.0, blended_rate + rng.uniform(-0.02, 0.02)))
            numerator = max(0, min(denominator, int(round(denominator * noisy_rate))))
            performance_key = f"{supplier['supplier_code']}:{site['site_code']}"
            rows.append(
                {
                    "id": stable_id(config, "supplier_performance", performance_key),
                    "supplier_id": supplier["id"],
                    "site_id": site["id"],
                    "definition_version": "OTIF_SYNTHETIC_V1",
                    "window_start": date_iso(add_days(config.as_of_date, -365)),
                    "window_end": date_iso(config.as_of_date),
                    "as_of_date": date_iso(config.as_of_date),
                    "numerator_count": numerator,
                    "denominator_count": denominator,
                    "otif_rate": f"{(numerator / denominator if denominator else 0):.4f}",
                    "sample_sufficient": "true" if denominator >= 20 else "false",
                }
            )
    return rows
