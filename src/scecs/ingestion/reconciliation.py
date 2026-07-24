"""Reconciliation result calculation and persistence."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scecs.ingestion.contracts import Rejection
from scecs.ingestion.loaders import DatasetLoadResult
from scecs.models import Base
from scecs.models.source_control import PipelineRun, ReconciliationResult


@dataclass(frozen=True)
class DatasetReconciliation:
    """Reconciliation for one operational dataset."""

    dataset_name: str
    source_rows: int
    accepted_rows: int
    inserted_rows: int
    existing_rows: int
    conflicting_rows: int
    rejected_rows: int
    matched_target_rows: int
    target_rows: int
    difference: int
    status: str
    explanation: str


def reconcile_loaded_datasets(
    session: Session,
    run: PipelineRun,
    load_results: list[DatasetLoadResult],
    validation_rejections: list[Rejection] | None = None,
) -> list[DatasetReconciliation]:
    """Persist and return dataset-level reconciliation results."""

    reconciliations: list[DatasetReconciliation] = []
    rejected_by_dataset: dict[str, int] = {}
    for rejection in validation_rejections or []:
        if rejection.row_number is not None:
            rejected_by_dataset[rejection.dataset_name] = rejected_by_dataset.get(rejection.dataset_name, 0) + 1
    for result in load_results:
        table = Base.metadata.tables[result.dataset_name]
        target_rows = int(session.execute(select(func.count()).select_from(table)).scalar_one())
        rejected_rows = result.rejected_rows + rejected_by_dataset.get(result.dataset_name, 0)
        accepted_rows = result.inserted_rows + result.existing_rows
        matched_target_rows = accepted_rows
        difference = abs(result.source_rows - accepted_rows - rejected_rows)
        status = "passed" if difference == 0 and result.conflicting_rows == 0 else "failed"
        explanation = (
            "Source rows equal accepted plus rejected rows."
            if status == "passed"
            else "Source rows do not reconcile to accepted plus rejected rows, or conflicts exist."
        )
        reconciliations.append(
            DatasetReconciliation(
                dataset_name=result.dataset_name,
                source_rows=result.source_rows,
                accepted_rows=accepted_rows,
                inserted_rows=result.inserted_rows,
                existing_rows=result.existing_rows,
                conflicting_rows=result.conflicting_rows,
                rejected_rows=rejected_rows,
                matched_target_rows=matched_target_rows,
                target_rows=target_rows,
                difference=difference,
                status=status,
                explanation=explanation,
            )
        )
        session.add(
            ReconciliationResult(
                pipeline_run_id=run.id,
                stage_name="operational_load",
                metric_name=result.dataset_name,
                source_count=result.source_rows,
                target_count=accepted_rows,
                difference_count=difference,
                is_blocking=difference != 0,
                inserted_count=result.inserted_rows,
                existing_count=result.existing_rows,
                conflicting_count=result.conflicting_rows,
                rejected_count=rejected_rows,
                matched_target_count=matched_target_rows,
                total_table_count=target_rows,
                status=status,
                explanation=explanation,
            )
        )
    return reconciliations
