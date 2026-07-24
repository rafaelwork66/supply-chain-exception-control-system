"""Command-line interface for governed synthetic-source ingestion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scecs.ingestion.mappings import mapping_report
from scecs.ingestion.service import get_reconciliation, get_status, inspect_bundle, load_bundle, validate_bundle


def main() -> None:
    """Run the ingestion CLI."""

    parser = argparse.ArgumentParser(prog="python -m scecs.ingestion.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "validate", "load"):
        command = subparsers.add_parser(name)
        command.add_argument("--input", required=True, type=Path)
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--run-reference", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--run-reference", required=True)
    subparsers.add_parser("mapping")
    args = parser.parse_args()

    if args.command == "inspect":
        inspection_result = inspect_bundle(args.input)
        _print_json(
            {
                "passed": inspection_result.passed,
                "manifest_hash": (
                    inspection_result.manifest.manifest_hash if inspection_result.manifest else None
                ),
                "rejections": [_rejection(row) for row in inspection_result.rejections],
            }
        )
    elif args.command == "validate":
        validation_result = validate_bundle(args.input)
        _print_json(
            {
                "passed": validation_result.passed,
                "datasets": {
                    name: len(rows) for name, rows in validation_result.records_by_dataset.items()
                },
                "rejections": [_rejection(row) for row in validation_result.rejections],
            }
        )
    elif args.command == "load":
        load_result = load_bundle(args.input)
        _print_json(
            {
                "passed": load_result.passed,
                "run_reference": load_result.run_reference,
                "publication_reference": load_result.publication_reference,
                "rejections": [_rejection(row) for row in load_result.rejections],
                "reconciliation": [row.__dict__ for row in load_result.reconciliations],
            }
        )
    elif args.command == "reconcile":
        _print_json(get_reconciliation(args.run_reference))
    elif args.command == "status":
        _print_json(get_status(args.run_reference))
    elif args.command == "mapping":
        _print_json(mapping_report())


def _rejection(row: object) -> dict[str, object]:
    return row.__dict__


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
