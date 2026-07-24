"""Configuration constants for governed ingestion."""

from __future__ import annotations

EXPECTED_GENERATOR_VERSION = "1.0.0"
EXPECTED_SCHEMA_VERSION = "synthetic-source-v1"

REQUIRED_CONTROL_FILES = frozenset(
    {
        "manifest.csv",
        "quality_summary.json",
        "distribution_summary.json",
    }
)

OPERATIONAL_DATASETS: tuple[str, ...] = (
    "source_systems",
    "source_loads",
    "sites",
    "suppliers",
    "supplier_versions",
    "products",
    "product_versions",
    "uom_conversions",
    "product_site_inventory_policies",
    "users",
    "ownership_mappings",
    "calendar_versions",
    "rule_versions",
    "purchase_orders",
    "purchase_order_versions",
    "purchase_order_lines",
    "purchase_order_line_aliases",
    "purchase_order_line_versions",
    "delivery_schedules",
    "supplier_commitment_observations",
    "receipt_transactions",
    "receipt_allocations",
    "inventory_snapshots",
    "demand_requirements",
    "supplier_performance_snapshots",
)

EVALUATION_ONLY_DATASETS = frozenset(
    {
        "future_receipt_outcomes",
        "synthetic_outcome_observations",
    }
)

NON_OPERATIONAL_EVIDENCE_DATASETS = frozenset(
    {
        "pipeline_runs",
        "scenario_registry",
        "scenario_assignments",
    }
)

ALLOWED_DATASETS = frozenset(OPERATIONAL_DATASETS) | EVALUATION_ONLY_DATASETS | NON_OPERATIONAL_EVIDENCE_DATASETS

LOAD_ORDER: tuple[str, ...] = OPERATIONAL_DATASETS
