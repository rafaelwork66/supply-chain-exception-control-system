"""Purchase-order history generation for synthetic source datasets."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from scecs.synthetic._util import add_days, date_iso, money, qty, stable_id, timestamp_for
from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.types import DatasetMap, Record


@dataclass(frozen=True)
class LineSnapshot:
    """Final synthetic PO-line state used by downstream generators."""

    po_line_id: str
    canonical_line_key: str
    purchase_order_id: str
    po_number: str
    supplier_id: str
    product_id: str
    site_id: str
    order_date: str
    need_date: str
    expected_date: str
    line_status: str
    base_quantity: float
    ordered_quantity: float
    order_uom: str
    unit_price: float
    scenario_types: tuple[str, ...]
    schedule_ids: tuple[str, ...]


def _conversion_factor(product_id: str, order_uom: str, uom_conversions: list[Record]) -> int:
    for conversion in uom_conversions:
        if conversion["product_id"] == product_id and conversion["from_uom"] == order_uom:
            return int(str(conversion["conversion_factor"]))
    raise ValueError(f"Missing UOM conversion for {product_id} {order_uom}")


def _schedule_quantities(base_quantity: float, schedule_count: int) -> list[float]:
    if schedule_count == 1:
        return [base_quantity]
    remaining = base_quantity
    quantities: list[float] = []
    for index in range(schedule_count - 1):
        share = round(base_quantity / schedule_count, 4)
        quantities.append(share)
        remaining -= share
        if index == schedule_count - 2:
            quantities.append(round(remaining, 4))
    return quantities


def generate_purchase_orders(
    config: SyntheticGeneratorConfig,
    rng: Random,
    *,
    source_system_id: str,
    source_load_id: str,
    suppliers: list[Record],
    products: list[Record],
    sites: list[Record],
    uom_conversions: list[Record],
    scenario_map: dict[str, list[str]],
) -> tuple[DatasetMap, list[LineSnapshot]]:
    """Generate PO headers, line versions, aliases and delivery schedules."""

    purchase_orders: list[Record] = []
    purchase_order_versions: list[Record] = []
    purchase_order_lines: list[Record] = []
    purchase_order_line_aliases: list[Record] = []
    purchase_order_line_versions: list[Record] = []
    delivery_schedules: list[Record] = []
    line_snapshots: list[LineSnapshot] = []
    versioned_purchase_orders: set[str] = set()

    open_start = config.po_line_count - config.target_open_line_count + 1
    current_po_number = ""
    current_po_id = ""
    lines_in_current_po = 0
    po_sequence = 0
    days_span = max((config.history_end - config.history_start).days, 1)

    for line_number in range(1, config.po_line_count + 1):
        if lines_in_current_po == 0:
            po_sequence += 1
            current_po_number = f"PO-{po_sequence:07d}"
            current_po_id = stable_id(config, "purchase_order", current_po_number)
            purchase_orders.append(
                {
                    "id": current_po_id,
                    "source_system_id": source_system_id,
                    "po_number": current_po_number,
                    "synthetic_data_flag": "true",
                }
            )
            lines_in_current_po = max(1, min(6, int(rng.expovariate(1 / 2.2)) + 1))

        canonical_key = f"POL-{line_number:08d}"
        po_line_id = stable_id(config, "purchase_order_line", canonical_key)
        supplier = suppliers[(line_number * 37 + rng.randrange(len(suppliers))) % len(suppliers)]
        product = products[(line_number * 13 + rng.randrange(len(products))) % len(products)]
        site = sites[(line_number + rng.randrange(len(sites))) % len(sites)]
        scenarios = tuple(sorted(scenario_map.get(canonical_key, [])))

        is_active_snapshot = line_number >= open_start
        if is_active_snapshot:
            status = "on_hold" if rng.random() < 0.06 else "open"
            order_date = add_days(config.as_of_date, -rng.randint(1, 65))
        else:
            status = "cancelled" if rng.random() < 0.02 else "closed"
            order_date = add_days(config.history_start, rng.randrange(max(days_span - 70, 1)))
        if "overdue_critical_order" in scenarios:
            status = "open"
            order_date = add_days(config.as_of_date, -55)

        lead_time = rng.randint(4, 70)
        need_date = add_days(order_date, lead_time + rng.randint(-3, 10))
        expected_date = add_days(order_date, lead_time + rng.randint(-5, 18))
        if is_active_snapshot:
            need_date = min(max(need_date, add_days(config.as_of_date, -10)), add_days(config.as_of_date, 35))
            expected_date = min(max(expected_date, add_days(config.as_of_date, -8)), add_days(config.as_of_date, 45))
        if "overdue_critical_order" in scenarios:
            need_date = add_days(config.as_of_date, -4)
            expected_date = add_days(config.as_of_date, 7)

        order_uom = rng.choice(list(config.purchase_uoms))
        factor = _conversion_factor(str(product["id"]), order_uom, uom_conversions)
        ordered_quantity = rng.randint(4, 220)
        base_quantity = float(ordered_quantity * factor)
        unit_price = round(rng.uniform(2.5, 480.0), 2)
        line_value = base_quantity * unit_price
        amendment_count = 2 if rng.random() < 0.08 else 1

        if current_po_id not in versioned_purchase_orders:
            purchase_order_versions.append(
                {
                    "id": stable_id(config, "purchase_order_version", f"{current_po_number}:1"),
                    "purchase_order_id": current_po_id,
                    "source_load_id": source_load_id,
                    "supplier_id": supplier["id"],
                    "amendment_version": 1,
                    "buyer_group": f"BG-{(po_sequence % 8) + 1:02d}",
                    "currency_code": config.reporting_currency,
                    "order_date": date_iso(order_date),
                    "order_status": "open" if is_active_snapshot else status,
                    "effective_at": timestamp_for(order_date),
                }
            )
            versioned_purchase_orders.add(current_po_id)

        purchase_order_lines.append(
            {
                "id": po_line_id,
                "purchase_order_id": current_po_id,
                "canonical_line_key": canonical_key,
                "synthetic_data_flag": "true",
            }
        )
        purchase_order_line_aliases.append(
            {
                "id": stable_id(config, "purchase_order_line_alias", canonical_key),
                "po_line_id": po_line_id,
                "source_system_id": source_system_id,
                "source_po_number": current_po_number,
                "source_line_number": str(line_number),
                "valid_from": timestamp_for(order_date),
                "valid_to": "",
                "correction_reason": "",
            }
        )
        for amendment in range(1, amendment_count + 1):
            amended_need = add_days(need_date, amendment - 1)
            amended_quantity = base_quantity + (factor if amendment > 1 and rng.random() < 0.5 else 0)
            purchase_order_line_versions.append(
                {
                    "id": stable_id(config, "purchase_order_line_version", f"{canonical_key}:{amendment}"),
                    "po_line_id": po_line_id,
                    "source_load_id": source_load_id,
                    "product_id": product["id"],
                    "site_id": site["id"],
                    "amendment_version": amendment,
                    "ordered_quantity": qty(ordered_quantity),
                    "order_uom": order_uom,
                    "base_quantity": qty(amended_quantity),
                    "need_date": date_iso(amended_need),
                    "requested_date": date_iso(add_days(amended_need, -rng.randint(0, 5))),
                    "line_status": status,
                    "effective_at": timestamp_for(add_days(order_date, amendment - 1)),
                    "line_value_aud": money(line_value),
                    "scenario_ids": ";".join(scenarios),
                }
            )
            base_quantity = amended_quantity

        schedule_count = rng.randint(2, 4) if "split_schedule" in scenarios else 1
        quantities = _schedule_quantities(base_quantity, schedule_count)
        schedule_ids: list[str] = []
        for schedule_number, scheduled_quantity in enumerate(quantities, start=1):
            schedule_key = f"{canonical_key}-SCH-{schedule_number}"
            schedule_id = stable_id(config, "delivery_schedule", schedule_key)
            schedule_ids.append(schedule_id)
            schedule_date = add_days(expected_date, (schedule_number - 1) * rng.randint(2, 8))
            delivery_schedules.append(
                {
                    "id": schedule_id,
                    "po_line_id": po_line_id,
                    "source_schedule_key": schedule_key,
                    "schedule_version": 1,
                    "scheduled_quantity": qty(scheduled_quantity),
                    "requested_date": date_iso(add_days(schedule_date, -rng.randint(0, 3))),
                    "confirmed_date": date_iso(schedule_date) if rng.random() > 0.07 else "",
                    "expected_date": date_iso(schedule_date),
                    "schedule_status": status,
                    "scenario_ids": ";".join(scenarios),
                }
            )

        line_snapshots.append(
            LineSnapshot(
                po_line_id=po_line_id,
                canonical_line_key=canonical_key,
                purchase_order_id=current_po_id,
                po_number=current_po_number,
                supplier_id=str(supplier["id"]),
                product_id=str(product["id"]),
                site_id=str(site["id"]),
                order_date=date_iso(order_date),
                need_date=date_iso(need_date),
                expected_date=date_iso(expected_date),
                line_status=status,
                base_quantity=base_quantity,
                ordered_quantity=float(ordered_quantity),
                order_uom=order_uom,
                unit_price=unit_price,
                scenario_types=scenarios,
                schedule_ids=tuple(schedule_ids),
            )
        )
        lines_in_current_po -= 1

    return (
        {
            "purchase_orders": purchase_orders,
            "purchase_order_versions": purchase_order_versions,
            "purchase_order_lines": purchase_order_lines,
            "purchase_order_line_aliases": purchase_order_line_aliases,
            "purchase_order_line_versions": purchase_order_line_versions,
            "delivery_schedules": delivery_schedules,
        },
        line_snapshots,
    )
