"""Independent synthetic outcome generation separated from risk scoring."""

from __future__ import annotations

from random import Random

from scecs.synthetic._util import add_days, date_iso, parse_date, qty, stable_id
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.purchase_orders import LineSnapshot
from scecs.synthetic.types import Record


def generate_outcomes(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    line_snapshots: list[LineSnapshot],
    hidden_supplier_archetypes: dict[str, str],
) -> list[Record]:
    """Generate hidden outcome labels without reading risk scores or lifecycle state."""

    rows: list[Record] = []
    lateness_probability = {"stable": 0.08, "average": 0.14, "volatile": 0.23, "fragile": 0.35}
    for line in line_snapshots:
        archetype = hidden_supplier_archetypes[line.supplier_id]
        scenarios = set(line.scenario_types)
        probability = lateness_probability[archetype]
        probability += 0.18 if "supplier_deterioration" in scenarios else 0.0
        probability += 0.12 if "supplier_commitment_breach" in scenarios else 0.0
        probability += 0.09 if parse_date(line.need_date).month in {10, 11, 12} else 0.0
        material_late = rng.random() < min(probability, 0.82)
        stockout_probability = 0.04
        stockout_probability += 0.17 if "demand_shock" in scenarios else 0.0
        stockout_probability += 0.10 if "overdue_critical_order" in scenarios else 0.0
        attributed_stockout = rng.random() < min(stockout_probability, 0.55)
        adverse = material_late or attributed_stockout
        observable_signal = rng.random() < (0.72 if adverse else 0.18)
        if "missing_supplier_signal" in scenarios or "missing_inventory_signal" in scenarios:
            observable_signal = False
        impact_level = "none"
        if adverse:
            impact_level = rng.choice(["low", "moderate", "severe" if attributed_stockout else "moderate"])
        onset_base = parse_date(line.need_date)
        onset = add_days(onset_base, rng.randint(-2, 5)) if adverse else None
        residual = line.base_quantity * rng.uniform(0.05, 0.55) if adverse else 0.0
        rows.append(
            {
                "id": stable_id(config, "synthetic_outcome", line.canonical_line_key),
                "po_line_id": line.po_line_id,
                "canonical_line_key": line.canonical_line_key,
                "site_id": line.site_id,
                "outcome_window_start": line.order_date,
                "outcome_window_end": date_iso(add_days(parse_date(line.need_date), 30)),
                "generator_version": config.generator_version,
                "seed_reference": f"{config.generator_version}:{config.seed}:outcome",
                "material_late": "true" if material_late else "false",
                "attributed_stockout": "true" if attributed_stockout else "false",
                "adverse_baseline": "true" if adverse else "false",
                "adverse_realised": "true" if adverse and rng.random() > 0.18 else "false",
                "operational_impact": impact_level,
                "residual_exposure_quantity": qty(residual),
                "urgent_intervention_required": "true" if impact_level in {"moderate", "severe"} else "false",
                "disruption_severity": impact_level,
                "outcome_onset": date_iso(onset) if onset is not None else "",
                "observable_source_signal": "true" if observable_signal else "false",
                "opportunity_class": _opportunity_class(adverse=adverse, observable_signal=observable_signal),
                "scenario_ids": ";".join(line.scenario_types),
            }
        )
    return rows


def _opportunity_class(*, adverse: bool, observable_signal: bool) -> str:
    if adverse and observable_signal:
        return "true_positive_opportunity"
    if not adverse and observable_signal:
        return "false_positive_opportunity"
    if adverse and not observable_signal:
        return "false_negative_opportunity"
    return "true_negative_opportunity"
