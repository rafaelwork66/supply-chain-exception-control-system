"""PostgreSQL loading helpers for governed ingestion."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from scecs.ingestion.contracts import Rejection, SourceRecord
from scecs.ingestion.manifest import BundleManifest
from scecs.ingestion.mappings import TableMapping, build_table_mappings
from scecs.models import Base
from scecs.models.source_control import PipelineRun, RejectedRecord


@dataclass(frozen=True)
class DatasetLoadResult:
    """Load counts for one dataset."""

    dataset_name: str
    source_rows: int
    inserted_rows: int
    existing_rows: int
    rejected_rows: int


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
    )
    session.add(run)
    session.flush()
    return run


def load_operational_records(
    session: Session,
    records_by_dataset: dict[str, list[SourceRecord]],
    run: PipelineRun,
) -> list[DatasetLoadResult]:
    """Load operational records in dependency order with PostgreSQL upserts."""

    mappings = build_table_mappings()
    results: list[DatasetLoadResult] = []
    for dataset_name, mapping in mappings.items():
        records = records_by_dataset.get(dataset_name, [])
        inserted = _load_dataset(session, mapping, records, run)
        results.append(
            DatasetLoadResult(
                dataset_name=dataset_name,
                source_rows=len(records),
                inserted_rows=inserted,
                existing_rows=len(records) - inserted,
                rejected_rows=0,
            )
        )
    return results


def persist_rejections(
    session: Session,
    rejections: list[Rejection],
    source_load_id: uuid.UUID | None,
) -> None:
    """Persist row-level or dataset-level rejections when a source-load anchor exists."""

    if source_load_id is None:
        return
    for rejection in rejections:
        session.add(
            RejectedRecord(
                source_load_id=source_load_id,
                source_row_ref=str(rejection.row_number or "dataset"),
                defect_code=rejection.code,
                field_name=rejection.field_name,
                observed_value_hash=rejection.rejected_value,
                severity=rejection.classification.value,
                disposition=_disposition(rejection),
                resolution_status="open",
                notes=rejection.message,
            )
        )


def _load_dataset(
    session: Session,
    mapping: TableMapping,
    records: list[SourceRecord],
    run: PipelineRun,
) -> int:
    if not records:
        return 0
    table = Base.metadata.tables[mapping.table_name]
    before_count = int(session.execute(select(func.count()).select_from(table)).scalar_one())
    payload: list[dict[str, object]] = []
    for record in records:
        row = {column: record.values[column] for column in mapping.columns}
        if mapping.dataset_name == "source_loads":
            row["pipeline_run_id"] = run.id
        payload.append(row)
    statement = insert(table).values(payload).on_conflict_do_nothing()
    session.execute(statement)
    after_count = int(session.execute(select(func.count()).select_from(table)).scalar_one())
    return after_count - before_count


def _disposition(rejection: Rejection) -> str:
    if rejection.classification.value == "bundle-blocking":
        return "stop_run"
    if rejection.classification.value == "dataset-blocking":
        return "stop_dataset"
    if rejection.classification.value == "warning-only":
        return "warning"
    return "reject_row"
