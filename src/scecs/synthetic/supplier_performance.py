"""Supplier performance observation generation."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import add_days, date_iso, stable_id
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.types import Record


def generate_supplier_performance(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    suppliers: list[Record],
    sites: list[Record],
    hidden_supplier_archetypes: dict[str, str],
) -> list[Record]:
    """Generate trailing supplier performance snapshots from hidden behaviour."""

    rows: list[Record] = []
    archetype_otif = {"stable": 0.94, "average": 0.87, "volatile": 0.79, "fragile": 0.68}
    for supplier in suppliers:
        archetype = hidden_supplier_archetypes[str(supplier["id"])]
        for site in sites:
            denominator = rng.randint(6, 120)
            baseline = archetype_otif[archetype] + rng.uniform(-0.07, 0.06)
            numerator = max(0, min(denominator, int(round(denominator * baseline))))
            key = f"{supplier['supplier_code']}:{site['site_code']}"
            rows.append(
                {
                    "id": stable_id(config, "supplier_performance", key),
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
