"""Manifest and hashing helpers for generated synthetic datasets."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from scecs.synthetic.types import DatasetMap


def stable_json(data: object) -> str:
    """Serialise JSON deterministically."""

    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(data: object) -> str:
    """Return a SHA-256 hash for deterministic JSON-compatible data."""

    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    """Return the SHA-256 hash of a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_schema(rows: list[dict[str, object]]) -> list[str]:
    """Return a deterministic schema for a dataset."""

    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    return fields


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """Write rows to CSV with deterministic newline and field ordering."""

    fieldnames = dataset_schema(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_manifest(
    datasets: DatasetMap,
    output_path: Path,
    *,
    schema_version: str,
    generator_version: str,
    seed: int,
    as_of_timestamp: str,
    generation_timestamp: str,
    configuration_hash: str,
) -> list[dict[str, Any]]:
    """Create manifest records for all exported datasets."""

    records: list[dict[str, Any]] = []
    for name in sorted(datasets):
        file_path = output_path / f"{name}.csv"
        records.append(
            {
                "dataset_name": name,
                "schema_version": schema_version,
                "row_count": len(datasets[name]),
                "file_name": file_path.name,
                "file_hash": file_hash(file_path),
                "generator_version": generator_version,
                "seed": seed,
                "as_of_timestamp": as_of_timestamp,
                "generation_timestamp": generation_timestamp,
                "configuration_hash": configuration_hash,
            }
        )
    return records
