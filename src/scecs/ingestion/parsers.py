"""Record parsers for operational source contracts."""

from __future__ import annotations

from scecs.ingestion.contracts import (
    DatasetContract,
    Rejection,
    RejectionClass,
    SourceRecord,
    parse_value,
    validate_allowed_value,
)
from scecs.ingestion.readers import make_source_record


def parse_dataset_rows(
    contract: DatasetContract,
    raw_rows: list[tuple[int, dict[str, str], str]],
) -> tuple[list[SourceRecord], list[Rejection]]:
    """Parse raw rows into typed source records."""

    records: list[SourceRecord] = []
    rejections: list[Rejection] = []
    for row_number, raw, fingerprint in raw_rows:
        missing = sorted(column for column in contract.required_columns if column not in raw)
        extra = sorted(column for column in raw if column not in contract.allowed_columns)
        if missing:
            rejections.append(
                Rejection(
                    contract.dataset_name,
                    row_number,
                    "MISSING_REQUIRED_COLUMN",
                    ", ".join(missing),
                    RejectionClass.DATASET_BLOCKING,
                )
            )
            continue
        if extra:
            rejections.append(
                Rejection(
                    contract.dataset_name,
                    row_number,
                    "UNDECLARED_COLUMN",
                    ", ".join(extra),
                    RejectionClass.DATASET_BLOCKING,
                )
            )
            continue

        parsed: dict[str, object] = {}
        for field_name, raw_value in raw.items():
            if field_name not in contract.required_columns:
                continue
            try:
                value = parse_value(field_name, raw_value)
                validate_allowed_value(field_name, value)
            except (TypeError, ValueError) as exc:
                rejections.append(
                    Rejection(
                        contract.dataset_name,
                        row_number,
                        "INVALID_FIELD_VALUE",
                        str(exc),
                        RejectionClass.RECORD_REJECTABLE,
                        field_name,
                        raw_value,
                    )
                )
                value = None
            parsed[field_name] = value
        if not any(
            rejection.row_number == row_number and rejection.classification is RejectionClass.RECORD_REJECTABLE
            for rejection in rejections
        ):
            records.append(make_source_record(contract.dataset_name, row_number, parsed, fingerprint))
    return records, rejections
