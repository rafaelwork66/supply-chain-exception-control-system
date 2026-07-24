"""Bundle discovery and manifest verification."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

from scecs.ingestion.config import (
    ALLOWED_DATASETS,
    EVALUATION_ONLY_DATASETS,
    EXPECTED_GENERATOR_VERSION,
    EXPECTED_SCHEMA_VERSION,
    REQUIRED_CONTROL_FILES,
)
from scecs.ingestion.contracts import Rejection, RejectionClass


@dataclass(frozen=True)
class ManifestRow:
    """One verified manifest record."""

    dataset_name: str
    schema_version: str
    row_count: int
    file_name: str
    file_hash: str
    generator_version: str
    seed: int
    as_of_timestamp: str
    generation_timestamp: str
    configuration_hash: str


@dataclass(frozen=True)
class BundleManifest:
    """Verified manifest and bundle metadata."""

    input_path: Path
    rows: dict[str, ManifestRow]
    manifest_hash: str
    configuration_hash: str
    generator_version: str
    schema_version: str
    as_of_timestamp: str
    evaluation_only_datasets: frozenset[str]


def file_hash(path: Path) -> str:
    """Return a SHA-256 hash for a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_bundle(input_path: Path) -> tuple[BundleManifest | None, list[Rejection]]:
    """Verify control files, manifest hashes, row counts, and declared files."""

    bundle_path = input_path.resolve()
    rejections: list[Rejection] = []
    if not bundle_path.exists() or not bundle_path.is_dir():
        return None, [
            Rejection(
                "bundle",
                None,
                "BUNDLE_NOT_FOUND",
                f"Input bundle does not exist or is not a directory: {input_path}",
                RejectionClass.BUNDLE_BLOCKING,
            )
        ]

    for required_file in REQUIRED_CONTROL_FILES:
        if not (bundle_path / required_file).is_file():
            rejections.append(
                Rejection("bundle", None, "MISSING_CONTROL_FILE", required_file, RejectionClass.BUNDLE_BLOCKING)
            )

    manifest_path = bundle_path / "manifest.csv"
    if not manifest_path.is_file():
        return None, rejections

    rows = _read_manifest(manifest_path, rejections)
    declared_files = {row.file_name for row in rows.values()}
    for csv_path in bundle_path.glob("*.csv"):
        if csv_path.name == "manifest.csv":
            continue
        if csv_path.name not in declared_files:
            dataset_name = csv_path.stem
            classification = (
                RejectionClass.WARNING_ONLY
                if dataset_name in EVALUATION_ONLY_DATASETS
                else RejectionClass.BUNDLE_BLOCKING
            )
            rejections.append(Rejection(dataset_name, None, "UNDECLARED_FILE", csv_path.name, classification))

    for row in rows.values():
        if row.dataset_name not in ALLOWED_DATASETS:
            rejections.append(
                Rejection(
                    row.dataset_name, None, "UNAPPROVED_DATASET", row.dataset_name, RejectionClass.BUNDLE_BLOCKING
                )
            )
        if row.generator_version != EXPECTED_GENERATOR_VERSION:
            rejections.append(
                Rejection(
                    row.dataset_name,
                    None,
                    "GENERATOR_VERSION_MISMATCH",
                    row.generator_version,
                    RejectionClass.BUNDLE_BLOCKING,
                )
            )
        if row.schema_version != EXPECTED_SCHEMA_VERSION:
            rejections.append(
                Rejection(
                    row.dataset_name,
                    None,
                    "SCHEMA_VERSION_MISMATCH",
                    row.schema_version,
                    RejectionClass.BUNDLE_BLOCKING,
                )
            )
        data_path = (bundle_path / row.file_name).resolve()
        if bundle_path not in data_path.parents:
            rejections.append(
                Rejection(row.dataset_name, None, "PATH_TRAVERSAL", row.file_name, RejectionClass.BUNDLE_BLOCKING)
            )
            continue
        if not data_path.is_file():
            rejections.append(
                Rejection(row.dataset_name, None, "MISSING_DATASET_FILE", row.file_name, RejectionClass.BUNDLE_BLOCKING)
            )
            continue
        actual_hash = file_hash(data_path)
        if actual_hash != row.file_hash:
            rejections.append(
                Rejection(row.dataset_name, None, "FILE_HASH_MISMATCH", row.file_name, RejectionClass.BUNDLE_BLOCKING)
            )
        actual_count = _count_data_rows(data_path)
        if actual_count != row.row_count:
            rejections.append(
                Rejection(
                    row.dataset_name,
                    None,
                    "ROW_COUNT_MISMATCH",
                    f"{actual_count} != {row.row_count}",
                    RejectionClass.BUNDLE_BLOCKING,
                )
            )

    if not rows:
        return None, rejections

    first = next(iter(rows.values()))
    hashes = {row.configuration_hash for row in rows.values()}
    generator_versions = {row.generator_version for row in rows.values()}
    schema_versions = {row.schema_version for row in rows.values()}
    as_of_values = {row.as_of_timestamp for row in rows.values()}
    if len(hashes) != 1 or len(generator_versions) != 1 or len(schema_versions) != 1 or len(as_of_values) != 1:
        rejections.append(
            Rejection(
                "manifest",
                None,
                "INCONSISTENT_MANIFEST_METADATA",
                "Manifest metadata varies across datasets.",
                RejectionClass.BUNDLE_BLOCKING,
            )
        )

    manifest = BundleManifest(
        input_path=bundle_path,
        rows=rows,
        manifest_hash=file_hash(manifest_path),
        configuration_hash=first.configuration_hash,
        generator_version=first.generator_version,
        schema_version=first.schema_version,
        as_of_timestamp=first.as_of_timestamp,
        evaluation_only_datasets=frozenset(rows) & EVALUATION_ONLY_DATASETS,
    )
    return manifest, rejections


def _read_manifest(path: Path, rejections: list[Rejection]) -> dict[str, ManifestRow]:
    rows: dict[str, ManifestRow] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            try:
                manifest_row = ManifestRow(
                    dataset_name=str(row["dataset_name"]),
                    schema_version=str(row["schema_version"]),
                    row_count=int(str(row["row_count"])),
                    file_name=str(row["file_name"]),
                    file_hash=str(row["file_hash"]),
                    generator_version=str(row["generator_version"]),
                    seed=int(str(row["seed"])),
                    as_of_timestamp=str(row["as_of_timestamp"]),
                    generation_timestamp=str(row["generation_timestamp"]),
                    configuration_hash=str(row["configuration_hash"]),
                )
            except (KeyError, ValueError) as exc:
                rejections.append(
                    Rejection("manifest", row_number, "INVALID_MANIFEST_ROW", str(exc), RejectionClass.BUNDLE_BLOCKING)
                )
                continue
            rows[manifest_row.dataset_name] = manifest_row
    return rows


def _count_data_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)
