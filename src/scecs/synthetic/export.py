"""CSV export orchestration for synthetic datasets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from scecs.synthetic.config import SyntheticGeneratorConfig
from scecs.synthetic.manifest import build_manifest, stable_hash, write_csv
from scecs.synthetic.types import GeneratedDatasetBundle
from scecs.synthetic.validation import validate_dataset_bundle, write_quality_summary


def export_bundle(bundle: GeneratedDatasetBundle, output_path: Path, config: SyntheticGeneratorConfig) -> None:
    """Export generated datasets, manifest and quality summary."""

    if output_path.exists():
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    _populate_source_load_hashes(bundle)
    for dataset_name in sorted(bundle.datasets):
        write_csv(output_path / f"{dataset_name}.csv", bundle.datasets[dataset_name])

    manifest_rows = build_manifest(
        bundle.datasets,
        output_path,
        schema_version="synthetic-source-v1",
        generator_version=bundle.generator_version,
        seed=bundle.seed,
        as_of_timestamp=bundle.as_of_timestamp,
        generation_timestamp=bundle.as_of_timestamp,
        configuration_hash=bundle.config_hash,
    )
    write_csv(output_path / "manifest.csv", manifest_rows)
    validation = validate_dataset_bundle(bundle.datasets, config)
    write_quality_summary(output_path / "quality_summary.json", validation)
    (output_path / "distribution_summary.json").write_text(
        json.dumps(validation.summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _populate_source_load_hashes(bundle: GeneratedDatasetBundle) -> None:
    dataset_groups = {
        "purchase_orders": (
            "purchase_orders",
            "purchase_order_versions",
            "purchase_order_lines",
            "purchase_order_line_aliases",
            "purchase_order_line_versions",
            "delivery_schedules",
        ),
        "receipts": (
            "supplier_commitment_observations",
            "receipt_transactions",
            "receipt_allocations",
        ),
        "inventory_snapshots": ("inventory_snapshots",),
        "demand_requirements": ("demand_requirements",),
        "supplier_performance": ("supplier_performance_snapshots",),
        "master_data": (
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
        ),
    }
    for row in bundle.datasets["source_loads"]:
        dataset_type = str(row["dataset_type"])
        grouped_rows = {name: bundle.datasets[name] for name in dataset_groups[dataset_type]}
        row["content_hash"] = stable_hash(grouped_rows)
