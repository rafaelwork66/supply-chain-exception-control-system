"""Internal helpers for deterministic synthetic record creation."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from random import Random

from scecs.synthetic.config import SyntheticGeneratorConfig

NAMESPACE = uuid.UUID("f4f04b4a-4d3e-46b2-b18f-5cb2683d3ef9")


def stable_id(config: SyntheticGeneratorConfig, entity: str, key: str) -> str:
    """Return a stable synthetic UUID for an entity/key pair."""

    return str(uuid.uuid5(NAMESPACE, f"{config.generator_version}:{config.seed}:{entity}:{key}"))


def money(value: float | Decimal) -> str:
    """Format money with two decimal places."""

    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def qty(value: float | Decimal) -> str:
    """Format quantities with four decimal places."""

    return str(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def date_iso(value: date) -> str:
    """Format a date as ISO text."""

    return value.isoformat()


def timestamp_for(day: date, hour: int = 9, minute: int = 0) -> str:
    """Return a deterministic Australia/Melbourne timestamp string."""

    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00+10:00"


def parse_date(value: object) -> date:
    """Parse an ISO date value."""

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def weighted_choice(rng: Random, weighted_values: list[tuple[str, float]]) -> str:
    """Choose a value from explicit weights."""

    total = sum(weight for _, weight in weighted_values)
    point = rng.random() * total
    running = 0.0
    for value, weight in weighted_values:
        running += weight
        if point <= running:
            return value
    return weighted_values[-1][0]


def days_between(start: date, end: date) -> int:
    """Return inclusive calendar-day distance."""

    return (end - start).days


def add_days(day: date, days: int) -> date:
    """Add calendar days to a date."""

    return day + timedelta(days=days)
