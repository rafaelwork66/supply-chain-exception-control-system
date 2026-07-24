"""CSV readers for verified source bundles."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from scecs.ingestion.contracts import SourceRecord


def raw_row_fingerprint(row: dict[str, str]) -> str:
    """Return a stable row fingerprint."""

    payload = json.dumps(row, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_csv_rows(bundle_path: Path, dataset_name: str, file_name: str) -> list[tuple[int, dict[str, str], str]]:
    """Read raw CSV rows with source row numbers and fingerprints."""

    path = bundle_path / file_name
    records: list[tuple[int, dict[str, str], str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            raw = {str(key): str(value) for key, value in row.items()}
            records.append((row_number, raw, raw_row_fingerprint(raw)))
    return records


def natural_key_for(dataset_name: str, values: dict[str, object]) -> str:
    """Return a stable natural key representation for rejection and reconciliation."""

    for field_name in (
        "source_code",
        "site_code",
        "supplier_code",
        "sku",
        "user_code",
        "canonical_line_key",
        "po_number",
        "source_commitment_ref",
        "receipt_document",
        "source_requirement_ref",
        "calendar_code",
        "rule_code",
    ):
        value = values.get(field_name)
        if value is not None:
            return f"{field_name}={value}"
    return f"{dataset_name}.id={values.get('id')}"


def make_source_record(dataset_name: str, row_number: int, values: dict[str, object], fingerprint: str) -> SourceRecord:
    """Build the typed source-record boundary object."""

    return SourceRecord(
        dataset_name=dataset_name,
        row_number=row_number,
        values=values,
        natural_key=natural_key_for(dataset_name, values),
        raw_fingerprint=fingerprint,
    )
