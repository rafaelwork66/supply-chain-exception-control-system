"""Reconciliation result calculation and persistence."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    rejected_rows: int
    target_rows: int
    difference: int
    status: str
    explanation: str


def reconcile_loaded_datasets(
    session: Session,
    run: PipelineRun,
    load_results: list[DatasetLoadResult],
) -> list[DatasetReconciliation]:
    """Persist and return dataset-level reconciliation results."""

    reconciliations: list[DatasetReconciliation] = []
    for result in load_results:
        table = Base.metadata.tables[result.dataset_name]
        target_rows = int(session.execute(select(func.count()).select_from(table)).scalar_one())
        accepted_rows = result.inserted_rows + result.existing_rows
        difference = abs(result.source_rows - accepted_rows)
        status = "passed" if difference == 0 else "failed"
        explanation = (
            "Source rows equal accepted rows." if status == "passed" else "Source rows do not equal accepted rows."
        )
        reconciliations.append(
            DatasetReconciliation(
                dataset_name=result.dataset_name,
                source_rows=result.source_rows,
                accepted_rows=accepted_rows,
                inserted_rows=result.inserted_rows,
                existing_rows=result.existing_rows,
                rejected_rows=result.rejected_rows,
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
            )
        )
    return reconciliations
