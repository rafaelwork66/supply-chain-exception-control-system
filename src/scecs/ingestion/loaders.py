"""PostgreSQL loading helpers for governed ingestion."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from scecs.ingestion.contracts import Rejection, RejectionClass, SourceRecord
from scecs.ingestion.manifest import BundleManifest
from scecs.ingestion.mappings import TableMapping, build_table_mappings
from scecs.ingestion.rejected_records import safe_value_hash
from scecs.models import Base
from scecs.models.source_control import PipelineRun, RejectedRecord

DEFAULT_BATCH_SIZE = 1000


@dataclass(frozen=True)
class DatasetLoadResult:
    """Load counts for one dataset."""

    dataset_name: str
    source_rows: int
    inserted_rows: int
    existing_rows: int
    conflicting_rows: int
    rejected_rows: int
    rejections: list[Rejection]


def create_ingestion_run(session: Session, manifest: BundleManifest, *, status: str = "running") -> PipelineRun:
    """Create the actual ingestion pipeline run for this attempt."""

    started_at = datetime.now(UTC)
    run = PipelineRun(
        run_reference=f"ING-{started_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        run_type="ingestion",
        trigger_type="manual",
        status=status,
        started_at=started_at,
        finished_at=None if status == "running" else started_at,
        release_version=manifest.generator_version,
        configuration_hash=manifest.configuration_hash,
        is_publication_eligible=False,
        bundle_reference=str(manifest.input_path),
        manifest_hash=manifest.manifest_hash,
        bundle_fingerprint=manifest.bundle_fingerprint,
        upstream_generator_version=manifest.generator_version,
        source_row_count=manifest.operational_row_count,
        accepted_row_count=0,
        rejected_row_count=0,
    )
    session.add(run)
    session.flush()
    return run


def load_operational_records(
    session: Session,
    records_by_dataset: dict[str, list[SourceRecord]],
    run: PipelineRun,
    manifest: BundleManifest,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[DatasetLoadResult]:
    """Load operational records in dependency order with conflict-aware batches."""

    mappings = build_table_mappings()
    results: list[DatasetLoadResult] = []
    source_load_id_map: dict[uuid.UUID, uuid.UUID] = {}
    for dataset_name, mapping in mappings.items():
        records = records_by_dataset.get(dataset_name, [])
        if dataset_name == "source_loads":
            result = _load_source_loads(session, mapping, records, run, manifest, source_load_id_map, batch_size)
            results.append(result)
            continue
        load_records = [_remap_source_load_reference(record, source_load_id_map) for record in records]
        inserted, existing, rejections = _load_dataset(session, mapping, load_records, batch_size)
        results.append(
            DatasetLoadResult(
                dataset_name=dataset_name,
                source_rows=len(records),
                inserted_rows=inserted,
                existing_rows=existing,
                conflicting_rows=len(rejections),
                rejected_rows=0,
                rejections=rejections,
            )
        )
    return results


def persist_rejections(
    session: Session,
    rejections: list[Rejection],
    run: PipelineRun,
    source_load_id: uuid.UUID | None,
) -> None:
    """Persist row-level or dataset-level rejections when a source-load anchor exists."""

    for rejection in rejections:
        session.add(
            RejectedRecord(
                pipeline_run_id=run.id,
                source_load_id=source_load_id,
                dataset_name=rejection.dataset_name,
                source_row_number=rejection.row_number,
                source_natural_key=rejection.natural_key,
                raw_row_fingerprint=rejection.raw_fingerprint,
                source_row_ref=str(rejection.row_number or "dataset"),
                defect_code=rejection.code,
                field_name=rejection.field_name,
                observed_value_hash=safe_value_hash(rejection.rejected_value) if rejection.rejected_value else None,
                classification=rejection.classification.value,
                severity=rejection.classification.value,
                disposition=_disposition(rejection),
                resolution_status="open",
                notes=rejection.message,
                rejected_at=datetime.now(UTC),
            )
        )


def _load_dataset(
    session: Session,
    mapping: TableMapping,
    records: list[SourceRecord],
    batch_size: int,
) -> tuple[int, int, list[Rejection]]:
    if not records:
        return 0, 0, []
    table = Base.metadata.tables[mapping.table_name]
    inserted_rows = 0
    existing_rows = 0
    rejections: list[Rejection] = []
    for batch in _chunks(records, batch_size):
        existing_by_id = _existing_rows_by_id(session, table, batch)
        payload: list[dict[str, object]] = []
        for record in batch:
            row_id = record.values["id"]
            row = {column: record.values[column] for column in mapping.columns}
            existing = existing_by_id.get(row_id)
            if existing is None:
                payload.append(row)
            elif _rows_match(mapping, existing, row):
                existing_rows += 1
            else:
                rejections.append(
                    Rejection(
                        mapping.dataset_name,
                        record.row_number,
                        "SOURCE_IDENTITY_CONFLICT",
                        "Source row has the same governed identity as an existing row but different mapped content.",
                        RejectionClass.DATASET_BLOCKING,
                        "id",
                        str(row_id),
                        record.natural_key,
                        record.raw_fingerprint,
                    )
                )
        if payload:
            inserted_rows += _insert_payload(session, table, payload)
    return inserted_rows, existing_rows, rejections


def _load_source_loads(
    session: Session,
    mapping: TableMapping,
    records: list[SourceRecord],
    run: PipelineRun,
    manifest: BundleManifest,
    source_load_id_map: dict[uuid.UUID, uuid.UUID],
    batch_size: int,
) -> DatasetLoadResult:
    payload: list[dict[str, object]] = []
    for record in records:
        upstream_source_load_id = record.values["id"]
        new_source_load_id = uuid.uuid4()
        assert isinstance(upstream_source_load_id, uuid.UUID)
        source_load_id_map[upstream_source_load_id] = new_source_load_id
        dataset_type = str(record.values["dataset_type"])
        manifest_row = manifest.rows.get(dataset_type)
        row = {column: record.values[column] for column in mapping.columns}
        row["id"] = new_source_load_id
        row["pipeline_run_id"] = run.id
        row["upstream_source_load_id"] = upstream_source_load_id
        row["upstream_pipeline_run_id"] = record.values["pipeline_run_id"]
        row["manifest_dataset_name"] = manifest_row.dataset_name if manifest_row else dataset_type
        row["manifest_file_name"] = manifest_row.file_name if manifest_row else None
        row["manifest_file_hash"] = manifest_row.file_hash if manifest_row else None
        payload.append(row)
    inserted = 0
    table = Base.metadata.tables[mapping.table_name]
    for batch in _chunks(payload, batch_size):
        inserted += _insert_payload(session, table, batch)
    return DatasetLoadResult(
        dataset_name=mapping.dataset_name,
        source_rows=len(records),
        inserted_rows=inserted,
        existing_rows=0,
        conflicting_rows=0,
        rejected_rows=0,
        rejections=[],
    )


def _insert_payload(session: Session, table: Table, payload: list[dict[str, object]]) -> int:
    statement = insert(table).values(payload).returning(table.c.id)
    return len(session.execute(statement).scalars().all())


def _existing_rows_by_id(
    session: Session, table: Table, records: list[SourceRecord]
) -> dict[object, dict[str, object]]:
    ids = [record.values["id"] for record in records]
    rows = session.execute(select(table).where(table.c.id.in_(ids))).mappings().all()
    return {row["id"]: dict(row) for row in rows}


def _rows_match(mapping: TableMapping, existing: dict[str, object], incoming: dict[str, object]) -> bool:
    ignored_columns = {"source_load_id"}
    for column in mapping.columns:
        if column in ignored_columns:
            continue
        if existing.get(column) != incoming.get(column):
            return False
    return True


def _remap_source_load_reference(record: SourceRecord, source_load_id_map: dict[uuid.UUID, uuid.UUID]) -> SourceRecord:
    source_load_id = record.values.get("source_load_id")
    if not isinstance(source_load_id, uuid.UUID):
        return record
    mapped_id = source_load_id_map.get(source_load_id)
    if mapped_id is None:
        return record
    values = dict(record.values)
    values["source_load_id"] = mapped_id
    return SourceRecord(
        dataset_name=record.dataset_name,
        row_number=record.row_number,
        values=values,
        natural_key=record.natural_key,
        raw_fingerprint=record.raw_fingerprint,
    )


def _chunks[T](items: list[T], size: int) -> list[list[T]]:
    iterator = iter(items)
    chunks: list[list[T]] = []
    while chunk := list(islice(iterator, size)):
        chunks.append(chunk)
    return chunks


def _disposition(rejection: Rejection) -> str:
    if rejection.classification.value == "bundle-blocking":
        return "stop_run"
    if rejection.classification.value == "dataset-blocking":
        return "stop_dataset"
    if rejection.classification.value == "warning-only":
        return "warning"
    return "reject_row"
