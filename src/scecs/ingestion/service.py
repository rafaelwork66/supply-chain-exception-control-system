"""High-level ingestion orchestration service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from scecs.database import create_database_engine, create_session_factory, session_scope
from scecs.ingestion.config import LOAD_ORDER
from scecs.ingestion.contracts import Rejection, RejectionClass, SourceRecord, build_contracts
from scecs.ingestion.loaders import create_ingestion_run, load_operational_records, persist_rejections
from scecs.ingestion.manifest import BundleManifest, verify_bundle
from scecs.ingestion.parsers import parse_dataset_rows
from scecs.ingestion.publication import publish_successful_run
from scecs.ingestion.readers import read_csv_rows
from scecs.ingestion.reconciliation import DatasetReconciliation, reconcile_loaded_datasets
from scecs.ingestion.validators import has_blocking_rejections, validate_cross_dataset, validate_operational_scope
from scecs.models.source_control import AnalyticsPublication, PipelineRun, ReconciliationResult


class SourceIdentityConflictError(RuntimeError):
    """Raised when source rows conflict with existing governed identities."""

    def __init__(self, rejections: list[Rejection]) -> None:
        super().__init__("source identity conflict")
        self.rejections = rejections


@dataclass(frozen=True)
class InspectionResult:
    """Bundle inspection result."""

    manifest: BundleManifest | None
    rejections: list[Rejection]

    @property
    def passed(self) -> bool:
        """Return whether the inspection has no blocking rejection."""

        return self.manifest is not None and not has_blocking_rejections(self.rejections)


@dataclass(frozen=True)
class ValidationResult:
    """Full validation result."""

    manifest: BundleManifest | None
    records_by_dataset: dict[str, list[SourceRecord]]
    rejections: list[Rejection]

    @property
    def passed(self) -> bool:
        """Return whether validation has no blocking rejection."""

        return self.manifest is not None and not has_blocking_rejections(self.rejections)


@dataclass(frozen=True)
class LoadResult:
    """Operational load result."""

    run_reference: str
    publication_reference: str | None
    rejections: list[Rejection]
    reconciliations: list[DatasetReconciliation]

    @property
    def passed(self) -> bool:
        """Return whether the load published successfully."""

        return self.publication_reference is not None


def inspect_bundle(input_path: Path) -> InspectionResult:
    """Inspect bundle control files and manifest only."""

    manifest, rejections = verify_bundle(input_path)
    return InspectionResult(manifest=manifest, rejections=rejections)


def validate_bundle(input_path: Path) -> ValidationResult:
    """Run Stage A and Stage B validation without loading operational data."""

    inspection = inspect_bundle(input_path)
    manifest = inspection.manifest
    rejections = list(inspection.rejections)
    records_by_dataset: dict[str, list[SourceRecord]] = {}
    if manifest is None:
        return ValidationResult(None, records_by_dataset, rejections)

    rejections.extend(validate_operational_scope(set(manifest.rows)))
    contracts = build_contracts()
    for dataset_name in LOAD_ORDER:
        manifest_row = manifest.rows.get(dataset_name)
        if manifest_row is None:
            continue
        raw_rows = read_csv_rows(manifest.input_path, dataset_name, manifest_row.file_name)
        records, dataset_rejections = parse_dataset_rows(contracts[dataset_name], raw_rows)
        records_by_dataset[dataset_name] = records
        rejections.extend(dataset_rejections)

    if not has_blocking_rejections(rejections):
        as_of = datetime.fromisoformat(manifest.as_of_timestamp).astimezone(UTC)
        rejections.extend(validate_cross_dataset(records_by_dataset, as_of))

    return ValidationResult(manifest, records_by_dataset, rejections)


def load_bundle(input_path: Path) -> LoadResult:
    """Validate, load, reconcile, and publish an operational source bundle."""

    validation = validate_bundle(input_path)
    if validation.manifest is None:
        raise ValueError("Cannot create an ingestion run without a readable manifest.")

    engine = create_database_engine()
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        run = create_ingestion_run(session, validation.manifest)
        run_reference = run.run_reference

    if has_blocking_rejections(validation.rejections):
        with session_scope(session_factory) as session:
            run = session.execute(select(PipelineRun).where(PipelineRun.run_reference == run_reference)).scalar_one()
            _persist_and_fail_run(session, run, validation.rejections, "validation_blocked")
            return LoadResult(run.run_reference, None, validation.rejections, [])

    if validation.rejections:
        with session_scope(session_factory) as session:
            run = session.execute(select(PipelineRun).where(PipelineRun.run_reference == run_reference)).scalar_one()
            persist_rejections(session, validation.rejections, run, None)

    try:
        with session_scope(session_factory) as session:
            run = session.execute(select(PipelineRun).where(PipelineRun.run_reference == run_reference)).scalar_one()
            load_results = load_operational_records(session, validation.records_by_dataset, run, validation.manifest)
            load_rejections = [rejection for result in load_results for rejection in result.rejections]
            if load_rejections:
                raise SourceIdentityConflictError(load_rejections)
            reconciliations = reconcile_loaded_datasets(session, run, load_results, validation.rejections)
            if any(item.status != "passed" for item in reconciliations):
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
                run.failure_reason = "reconciliation_failed"
                run.rejected_row_count = len(validation.rejections)
                return LoadResult(run.run_reference, None, validation.rejections, reconciliations)
            publication = publish_successful_run(session, run, validation.manifest, reconciliations)
            run.accepted_row_count = sum(item.accepted_rows for item in reconciliations)
            run.rejected_row_count = sum(item.rejected_rows for item in reconciliations) + len(validation.rejections)
            return LoadResult(
                run.run_reference, publication.publication_reference, validation.rejections, reconciliations
            )
    except SourceIdentityConflictError as exc:
        validation.rejections.extend(exc.rejections)
        with session_scope(session_factory) as session:
            run = session.execute(select(PipelineRun).where(PipelineRun.run_reference == run_reference)).scalar_one()
            _persist_and_fail_run(session, run, validation.rejections, "source_identity_conflict")
            return LoadResult(run.run_reference, None, validation.rejections, [])
    except SQLAlchemyError as exc:
        with session_scope(session_factory) as session:
            run = session.execute(select(PipelineRun).where(PipelineRun.run_reference == run_reference)).scalar_one()
            failure = Rejection(
                "database",
                None,
                "DATABASE_LOAD_FAILURE",
                exc.__class__.__name__,
                RejectionClass.DATASET_BLOCKING,
            )
            _persist_and_fail_run(session, run, [failure], "database_load_failure")
            return LoadResult(run.run_reference, None, [failure], [])


def get_status(run_reference: str) -> dict[str, object]:
    """Return run and publication status for a run reference."""

    engine = create_database_engine()
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        run = session.execute(select(PipelineRun).where(PipelineRun.run_reference == run_reference)).scalar_one()
        publication = session.execute(
            select(AnalyticsPublication).where(AnalyticsPublication.pipeline_run_id == run.id)
        ).scalar_one_or_none()
        return {
            "run_reference": run.run_reference,
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "is_publication_eligible": run.is_publication_eligible,
            "publication_reference": publication.publication_reference if publication else None,
        }


def get_reconciliation(run_reference: str) -> list[dict[str, object]]:
    """Return persisted reconciliation rows for a run reference."""

    engine = create_database_engine()
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        run = session.execute(select(PipelineRun).where(PipelineRun.run_reference == run_reference)).scalar_one()
        return [
            {
                "stage_name": row.stage_name,
                "metric_name": row.metric_name,
                "source_count": row.source_count,
                "target_count": row.target_count,
                "difference_count": row.difference_count,
                "is_blocking": row.is_blocking,
                "inserted_count": row.inserted_count,
                "existing_count": row.existing_count,
                "conflicting_count": row.conflicting_count,
                "rejected_count": row.rejected_count,
                "matched_target_count": row.matched_target_count,
                "total_table_count": row.total_table_count,
                "status": row.status,
                "explanation": row.explanation,
            }
            for row in run_reconciliation_rows(session, run.id)
        ]


def run_reconciliation_rows(session: object, run_id: UUID) -> list[ReconciliationResult]:
    """Fetch reconciliation rows with a small helper to keep CLI output simple."""

    from sqlalchemy.orm import Session

    typed_session = session
    assert isinstance(typed_session, Session)
    return list(
        typed_session.execute(
            select(ReconciliationResult).where(ReconciliationResult.pipeline_run_id == run_id)
        ).scalars()
    )


def _persist_and_fail_run(
    session: object,
    run: PipelineRun,
    rejections: list[Rejection],
    failure_reason: str,
) -> None:
    from sqlalchemy.orm import Session

    typed_session = session
    assert isinstance(typed_session, Session)
    persist_rejections(typed_session, rejections, run, None)
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.failure_reason = failure_reason
    run.rejected_row_count = len(rejections)
