"""Determinism tests for the synthetic generator."""

from pathlib import Path

from scecs.synthetic.config import SyntheticGeneratorConfig, ci_config
from scecs.synthetic.export import export_bundle
from scecs.synthetic.generator import generate_dataset_bundle
from scecs.synthetic.manifest import file_hash


def _export_hashes(config: SyntheticGeneratorConfig, output_path: Path) -> dict[str, str]:
    configured = config.with_output_path(output_path)
    bundle = generate_dataset_bundle(configured)
    export_bundle(bundle, output_path, configured)
    return {path.name: file_hash(path) for path in sorted(output_path.glob("*.csv"))}


def test_same_seed_configuration_and_as_of_date_produce_identical_hashes(tmp_path: Path) -> None:
    """A repeated generation with the same inputs should be byte-identical."""

    config = ci_config()

    first = _export_hashes(config, tmp_path / "first")
    second = _export_hashes(config, tmp_path / "second")

    assert first == second


def test_different_seed_changes_generated_records(tmp_path: Path) -> None:
    """Changing only the seed should materially change records."""

    config = ci_config()
    changed_seed = SyntheticGeneratorConfig(
        seed=config.seed + 1,
        as_of_date=config.as_of_date,
        history_start=config.history_start,
        history_end=config.history_end,
        site_count=config.site_count,
        supplier_count=config.supplier_count,
        product_count=config.product_count,
        po_line_count=config.po_line_count,
        target_open_line_count=config.target_open_line_count,
        output_path=config.output_path,
        generator_version=config.generator_version,
        reporting_currency=config.reporting_currency,
        timezone_name=config.timezone_name,
        base_uom=config.base_uom,
        purchase_uoms=config.purchase_uoms,
        scenario_rates=config.scenario_rates,
    )

    first = _export_hashes(config, tmp_path / "first")
    second = _export_hashes(changed_seed, tmp_path / "second")

    assert first["purchase_order_line_versions.csv"] != second["purchase_order_line_versions.csv"]
