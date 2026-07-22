"""Typed configuration for deterministic synthetic data generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal

GENERATOR_VERSION = "1.0.0"
ProfileName = Literal["ci", "portfolio"]


@dataclass(frozen=True)
class ScenarioRates:
    """Scenario-injection rates and controls."""

    split_schedule_rate: float = 0.21
    partial_receipt_rate: float = 0.20
    receipt_correction_rate: float = 0.008
    receipt_reversal_rate: float = 0.004
    missing_supplier_signal_rate: float = 0.06
    missing_inventory_signal_rate: float = 0.04
    demand_shock_rate: float = 0.04
    supplier_deterioration_rate: float = 0.03


@dataclass(frozen=True)
class SyntheticGeneratorConfig:
    """Complete deterministic generator configuration."""

    seed: int = 20260720
    as_of_date: date = date(2026, 6, 30)
    history_start: date = date(2024, 7, 1)
    history_end: date = date(2026, 6, 30)
    site_count: int = 2
    supplier_count: int = 120
    product_count: int = 1_000
    po_line_count: int = 62_000
    target_open_line_count: int = 1_500
    output_path: Path = Path("data/generated/portfolio_baseline")
    generator_version: str = GENERATOR_VERSION
    reporting_currency: str = "AUD"
    timezone_name: str = "Australia/Melbourne"
    base_uom: str = "EA"
    purchase_uoms: tuple[str, ...] = ("EA", "CASE", "PALLET")
    scenario_rates: ScenarioRates = ScenarioRates()

    @property
    def as_of_timestamp(self) -> str:
        """Return a deterministic generation timestamp for reproducible outputs."""

        return f"{self.as_of_date.isoformat()}T18:00:00+10:00"

    def with_output_path(self, output_path: str | Path) -> SyntheticGeneratorConfig:
        """Return a copy with a different output path."""

        return SyntheticGeneratorConfig(
            seed=self.seed,
            as_of_date=self.as_of_date,
            history_start=self.history_start,
            history_end=self.history_end,
            site_count=self.site_count,
            supplier_count=self.supplier_count,
            product_count=self.product_count,
            po_line_count=self.po_line_count,
            target_open_line_count=self.target_open_line_count,
            output_path=Path(output_path),
            generator_version=self.generator_version,
            reporting_currency=self.reporting_currency,
            timezone_name=self.timezone_name,
            base_uom=self.base_uom,
            purchase_uoms=self.purchase_uoms,
            scenario_rates=self.scenario_rates,
        )


def default_portfolio_config() -> SyntheticGeneratorConfig:
    """Return the governed full portfolio baseline configuration."""

    return SyntheticGeneratorConfig()


def ci_config() -> SyntheticGeneratorConfig:
    """Return a small deterministic profile suitable for local tests and CI."""

    return SyntheticGeneratorConfig(
        seed=20260720,
        site_count=2,
        supplier_count=12,
        product_count=40,
        po_line_count=260,
        target_open_line_count=30,
        output_path=Path("data/sample/synthetic_ci"),
    )


def get_profile_config(profile: ProfileName) -> SyntheticGeneratorConfig:
    """Load a named generator profile."""

    if profile == "ci":
        return ci_config()
    if profile == "portfolio":
        return default_portfolio_config()
    raise ValueError(f"Unknown synthetic generator profile: {profile}")


def configuration_hash(config: SyntheticGeneratorConfig) -> str:
    """Return a stable hash of the deterministic configuration."""

    payload = asdict(config)
    payload.pop("output_path", None)
    payload["as_of_date"] = config.as_of_date.isoformat()
    payload["history_start"] = config.history_start.isoformat()
    payload["history_end"] = config.history_end.isoformat()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
