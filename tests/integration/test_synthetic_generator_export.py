"""Integration-style tests for exported synthetic datasets."""

from pathlib import Path

import pytest

from scecs.synthetic.config import ci_config
from scecs.synthetic.export import export_bundle
from scecs.synthetic.generator import generate_dataset_bundle
from scecs.synthetic.validation import load_exported_datasets, validate_dataset_bundle


@pytest.mark.integration
def test_ci_profile_generation_export_and_validation(tmp_path: Path) -> None:
    """The CI-sized profile should export files that validate when reloaded."""

    config = ci_config().with_output_path(tmp_path / "synthetic_ci")
    bundle = generate_dataset_bundle(config)

    export_bundle(bundle, config.output_path, config)
    reloaded = load_exported_datasets(config.output_path)
    result = validate_dataset_bundle(reloaded, config)

    assert result.passed, result.errors
    assert (config.output_path / "manifest.csv").exists()
    assert (config.output_path / "quality_summary.json").exists()
    assert (config.output_path / "distribution_summary.json").exists()
