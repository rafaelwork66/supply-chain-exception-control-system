"""Unit tests for governed ingestion validation."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from scecs.ingestion.service import inspect_bundle, validate_bundle

FIXTURE = Path("data/sample/synthetic_ci")


def copy_fixture(tmp_path: Path) -> Path:
    """Copy the committed CI fixture to a temporary bundle path."""

    target = tmp_path / "bundle"
    shutil.copytree(FIXTURE, target)
    return target


def rewrite_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    """Rewrite a CSV file with deterministic headers."""

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read a CSV file and return rows plus field names."""

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def test_valid_bundle_inspection_and_validation_succeed() -> None:
    """The committed CI bundle should pass manifest inspection and operational validation."""

    inspection = inspect_bundle(FIXTURE)
    validation = validate_bundle(FIXTURE)

    assert inspection.passed
    assert validation.passed
    assert validation.records_by_dataset["purchase_order_lines"]


def test_missing_required_file_fails(tmp_path: Path) -> None:
    """Removing an operational file should block the bundle."""

    bundle = copy_fixture(tmp_path)
    (bundle / "suppliers.csv").unlink()

    inspection = inspect_bundle(bundle)

    assert not inspection.passed
    assert {row.code for row in inspection.rejections} >= {"MISSING_DATASET_FILE"}


def test_modified_file_hash_fails(tmp_path: Path) -> None:
    """Changing a CSV without updating the manifest should be detected."""

    bundle = copy_fixture(tmp_path)
    path = bundle / "suppliers.csv"
    rows, fieldnames = read_csv(path)
    rows[0]["supplier_code"] = "SUP-TAMPERED"
    rewrite_csv(path, rows, fieldnames)

    inspection = inspect_bundle(bundle)

    assert not inspection.passed
    assert {row.code for row in inspection.rejections} >= {"FILE_HASH_MISMATCH"}


def test_manifest_row_count_mismatch_fails(tmp_path: Path) -> None:
    """A wrong manifest row count should block the bundle."""

    bundle = copy_fixture(tmp_path)
    path = bundle / "manifest.csv"
    rows, fieldnames = read_csv(path)
    for row in rows:
        if row["dataset_name"] == "sites":
            row["row_count"] = "999"
    rewrite_csv(path, rows, fieldnames)

    inspection = inspect_bundle(bundle)

    assert not inspection.passed
    assert {row.code for row in inspection.rejections} >= {"ROW_COUNT_MISMATCH"}


def test_invalid_uuid_is_rejected(tmp_path: Path) -> None:
    """Bad UUID source values should be record-rejectable."""

    bundle = copy_fixture(tmp_path)
    path = bundle / "products.csv"
    rows, fieldnames = read_csv(path)
    rows[0]["id"] = "not-a-uuid"
    rewrite_csv(path, rows, fieldnames)
    _sync_manifest_for_test(bundle, "products")

    validation = validate_bundle(bundle)

    assert not validation.passed
    assert {row.code for row in validation.rejections} >= {"INVALID_FIELD_VALUE"}


def test_invalid_timestamp_is_rejected(tmp_path: Path) -> None:
    """Naive timestamps should be rejected because source times must be timezone-aware."""

    bundle = copy_fixture(tmp_path)
    path = bundle / "source_loads.csv"
    rows, fieldnames = read_csv(path)
    rows[0]["extracted_at"] = "2026-06-30T18:00:00"
    rewrite_csv(path, rows, fieldnames)
    _sync_manifest_for_test(bundle, "source_loads")

    validation = validate_bundle(bundle)

    assert not validation.passed
    assert {row.code for row in validation.rejections} >= {"INVALID_FIELD_VALUE"}


def test_post_as_of_operational_receipt_fails(tmp_path: Path) -> None:
    """Operational receipt observations after the as-of timestamp should block validation."""

    bundle = copy_fixture(tmp_path)
    path = bundle / "receipt_transactions.csv"
    rows, fieldnames = read_csv(path)
    rows[0]["posted_at"] = "2026-07-01T09:00:00+10:00"
    rewrite_csv(path, rows, fieldnames)
    _sync_manifest_for_test(bundle, "receipt_transactions")

    validation = validate_bundle(bundle)

    assert not validation.passed
    assert {row.code for row in validation.rejections} >= {"POST_AS_OF_OPERATIONAL_TIMESTAMP"}


def test_future_planned_date_remains_allowed(tmp_path: Path) -> None:
    """Future business dates are allowed when the source observation is visible by as-of."""

    bundle = copy_fixture(tmp_path)
    path = bundle / "purchase_order_line_versions.csv"
    rows, fieldnames = read_csv(path)
    rows[0]["need_date"] = "2026-08-15"
    rewrite_csv(path, rows, fieldnames)
    _sync_manifest_for_test(bundle, "purchase_order_line_versions")

    validation = validate_bundle(bundle)

    assert validation.passed


def test_line_value_mismatch_fails(tmp_path: Path) -> None:
    """Purchase-order line value should reconcile to base quantity times unit price."""

    bundle = copy_fixture(tmp_path)
    path = bundle / "purchase_order_line_versions.csv"
    rows, fieldnames = read_csv(path)
    rows[0]["line_value_aud"] = "0.01"
    rewrite_csv(path, rows, fieldnames)
    _sync_manifest_for_test(bundle, "purchase_order_line_versions")

    validation = validate_bundle(bundle)

    assert not validation.passed
    assert {row.code for row in validation.rejections} >= {"LINE_VALUE_MISMATCH"}


def test_evaluation_only_files_are_not_operationally_loaded() -> None:
    """Default validation reports evaluation-only files as skipped warnings."""

    validation = validate_bundle(FIXTURE)
    skipped = {row.dataset_name for row in validation.rejections if row.code == "NON_OPERATIONAL_FILE_SKIPPED"}

    assert {"future_receipt_outcomes", "synthetic_outcome_observations"} <= skipped


def _sync_manifest_for_test(bundle: Path, dataset_name: str) -> None:
    """Update a copied fixture manifest after intentional data mutation."""

    from scecs.synthetic.manifest import file_hash

    manifest_path = bundle / "manifest.csv"
    rows, fieldnames = read_csv(manifest_path)
    data_path = bundle / f"{dataset_name}.csv"
    row_count = len(read_csv(data_path)[0])
    for row in rows:
        if row["dataset_name"] == dataset_name:
            row["file_hash"] = file_hash(data_path)
            row["row_count"] = str(row_count)
    rewrite_csv(manifest_path, rows, fieldnames)

