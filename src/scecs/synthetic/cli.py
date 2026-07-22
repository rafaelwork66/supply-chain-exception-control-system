"""Command-line interface for deterministic synthetic data generation."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import cast

from scecs.synthetic.config import ProfileName, SyntheticGeneratorConfig, get_profile_config
from scecs.synthetic.export import export_bundle
from scecs.synthetic.generator import generate_dataset_bundle
from scecs.synthetic.summaries import render_markdown_summary
from scecs.synthetic.validation import load_exported_datasets, validate_dataset_bundle, write_quality_summary


def main(argv: list[str] | None = None) -> int:
    """Run the synthetic-data CLI."""

    parser = argparse.ArgumentParser(prog="python -m scecs.synthetic.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="Generate synthetic CSV source datasets.")
    _add_common_profile_args(generate_parser)

    validate_parser = subparsers.add_parser("validate", help="Validate an exported synthetic dataset folder.")
    _add_common_profile_args(validate_parser)

    summarise_parser = subparsers.add_parser("summarise", help="Render distribution and quality summaries.")
    _add_common_profile_args(summarise_parser)
    summarise_parser.add_argument("--write-doc", type=Path, default=None)

    args = parser.parse_args(argv)
    config = _config_from_args(args)

    if args.command == "generate":
        started = time.perf_counter()
        bundle = generate_dataset_bundle(config)
        export_bundle(bundle, config.output_path, config)
        duration = time.perf_counter() - started
        performance = {
            "profile": args.profile,
            "duration_seconds": round(duration, 4),
            "output_path": str(config.output_path),
            "po_line_count": config.po_line_count,
            "target_open_line_count": config.target_open_line_count,
        }
        (config.output_path / "performance_summary.json").write_text(
            json.dumps(performance, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(performance, sort_keys=True))
        return 0

    if args.command == "validate":
        started = time.perf_counter()
        datasets = load_exported_datasets(config.output_path)
        result = validate_dataset_bundle(datasets, config)
        write_quality_summary(config.output_path / "quality_summary.json", result)
        duration = time.perf_counter() - started
        print(json.dumps({"passed": result.passed, "errors": result.errors, "duration_seconds": round(duration, 4)}))
        return 0 if result.passed else 1

    if args.command == "summarise":
        quality_path = config.output_path / "quality_summary.json"
        if not quality_path.exists():
            datasets = load_exported_datasets(config.output_path)
            result = validate_dataset_bundle(datasets, config)
            write_quality_summary(quality_path, result)
        rendered = render_markdown_summary(quality_path)
        if args.write_doc is not None:
            args.write_doc.parent.mkdir(parents=True, exist_ok=True)
            args.write_doc.write_text(rendered, encoding="utf-8")
        print(rendered)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _add_common_profile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", choices=["ci", "portfolio"], default="ci")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=None)


def _config_from_args(args: argparse.Namespace) -> SyntheticGeneratorConfig:
    profile = str(args.profile)
    config = get_profile_config(cast(ProfileName, profile))
    if args.seed is not None:
        config = SyntheticGeneratorConfig(
            seed=int(args.seed),
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
    if args.output is not None:
        config = config.with_output_path(Path(args.output))
    return config


if __name__ == "__main__":
    raise SystemExit(main())
