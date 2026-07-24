"""PostgreSQL integration tests for governed ingestion."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import scecs.ingestion.service as ingestion_service
from scecs.database import create_database_engine
from scecs.ingestion.contracts import SourceRecord
from scecs.ingestion.loaders import DatasetLoadResult
from scecs.ingestion.loaders import load_operational_records as original_load_operational_records
from scecs.ingestion.manifest import BundleManifest
from scecs.ingestion.service import load_bundle, validate_bundle
from scecs.models import Base
from scecs.models.procurement import SyntheticOutcomeObservation
from scecs.models.source_control import AnalyticsPublication, PipelineRun, ReconciliationResult, RejectedRecord
from scecs.synthetic.manifest import file_hash

FIXTURE = Path("data/sample/synthetic_ci")


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Return the configured PostgreSQL engine."""

    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")
    return create_database_engine()


@pytest.mark.integration
def test_ingestion_pipeline_database_behaviour(engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CI ingestion must exercise PostgreSQL behaviour, idempotency, and publication rollback."""

    with engine.connect() as connection:
        assert connection.execute(text("select to_regclass('public.pipeline_runs')")).scalar_one()

    validation = validate_bundle(FIXTURE)
    first = load_bundle(FIXTURE)
    assert validation.passed
    assert first.passed
    assert first.publication_reference is not None
    assert all(row.status == "passed" for row in first.reconciliations)
    assert all(row.rejected_rows == 0 for row in first.reconciliations)
    assert any(row.inserted_rows > 0 for row in first.reconciliations)
    assert _risk_input_count(engine) > 0
    assert _run_is_publication_eligible(engine, first.run_reference)
    assert _reconciliation_count(engine, first.run_reference) >= 25
    assert _synthetic_outcome_count(engine) == 0

    before_counts = _operational_counts(engine)
    source_loads_after_first = before_counts["source_loads"]
    second = load_bundle(FIXTURE)
    after_counts = _operational_counts(engine)
    assert second.passed
    assert after_counts["source_loads"] == source_loads_after_first * 2
    assert _without_source_loads(before_counts) == _without_source_loads(after_counts)
    assert any(row.existing_rows > 0 for row in second.reconciliations)
    assert second.run_reference != first.run_reference

    changed_bundle = tmp_path / "changed_bundle"
    shutil.copytree(FIXTURE, changed_bundle)
    _mutate_supplier_code(changed_bundle)
    changed = load_bundle(changed_bundle)
    assert not changed.passed
    assert {row.code for row in changed.rejections} >= {"SOURCE_IDENTITY_CONFLICT"}

    current_before = _current_publication_reference(engine)
    counts_before_failure = _operational_counts(engine)
    rejected_before = _rejected_record_count(engine)
    bundle = tmp_path / "bundle"
    shutil.copytree(FIXTURE, bundle)
    _mutate_receipt_after_as_of(bundle)
    validation = validate_bundle(bundle)
    failed = load_bundle(bundle)
    current_after = _current_publication_reference(engine)
    counts_after_failure = _operational_counts(engine)

    assert not validation.passed
    assert not failed.passed
    assert current_before == current_after
    assert counts_before_failure == counts_after_failure
    assert _failed_run_count(engine, failed.run_reference) == 1
    assert _rejected_record_count(engine) > rejected_before

    database_failure_before = _operational_counts(engine)
    def fail_after_load_started(
        session: Session,
        records_by_dataset: dict[str, list[SourceRecord]],
        run: PipelineRun,
        manifest: BundleManifest,
        *,
        batch_size: int = 1000,
    ) -> list[DatasetLoadResult]:
        original_load_operational_records(session, records_by_dataset, run, manifest, batch_size=batch_size)
        raise SQLAlchemyError("forced failure after load started")

    monkeypatch.setattr(ingestion_service, "load_operational_records", fail_after_load_started)
    failed_database = load_bundle(FIXTURE)
    monkeypatch.setattr(ingestion_service, "load_operational_records", original_load_operational_records)

    assert not failed_database.passed
    assert _operational_counts(engine) == database_failure_before
    assert _failed_run_count(engine, failed_database.run_reference) == 1
    assert _current_publication_reference(engine) == current_before


def _operational_counts(engine: Engine) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for dataset_name in (
            "source_systems",
            "source_loads",
            "sites",
            "suppliers",
            "products",
            "purchase_order_lines",
            "receipt_transactions",
            "receipt_allocations",
            "inventory_snapshots",
            "demand_requirements",
        ):
            table = Base.metadata.tables[dataset_name]
            counts[dataset_name] = int(connection.execute(select(func.count()).select_from(table)).scalar_one())
    return counts


def _without_source_loads(counts: dict[str, int]) -> dict[str, int]:
    return {name: count for name, count in counts.items() if name != "source_loads"}


def _risk_input_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    select count(*)
                    from purchase_order_line_versions
                    where unit_price_aud is not null
                      and line_value_aud is not null
                    """
                )
            ).scalar_one()
        )


def _current_publication_reference(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                select(AnalyticsPublication.publication_reference).where(
                    AnalyticsPublication.is_current_success.is_(True)
                )
            ).scalar_one()
        )


def _run_is_publication_eligible(engine: Engine, run_reference: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                select(PipelineRun.is_publication_eligible).where(
                    PipelineRun.run_reference == run_reference
                )
            ).scalar_one()
        )


def _reconciliation_count(engine: Engine, run_reference: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count())
                .select_from(ReconciliationResult)
                .join(PipelineRun, PipelineRun.id == ReconciliationResult.pipeline_run_id)
                .where(PipelineRun.run_reference == run_reference)
            ).scalar_one()
        )


def _synthetic_outcome_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(select(func.count()).select_from(SyntheticOutcomeObservation)).scalar_one()
        )


def _failed_run_count(engine: Engine, run_reference: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count())
                .select_from(PipelineRun)
                .where(PipelineRun.run_reference == run_reference, PipelineRun.status == "failed")
            ).scalar_one()
        )


def _rejected_record_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(RejectedRecord)).scalar_one())


def _mutate_supplier_code(bundle: Path) -> None:
    path = bundle / "suppliers.csv"
    rows, fieldnames = _read_csv(path)
    rows[0]["supplier_code"] = f"{rows[0]['supplier_code']}-CHANGED"
    _write_csv(path, rows, fieldnames)
    _sync_manifest_hash(bundle, "suppliers")


def _mutate_receipt_after_as_of(bundle: Path) -> None:
    path = bundle / "receipt_transactions.csv"
    rows, fieldnames = _read_csv(path)
    rows[0]["posted_at"] = "2026-07-01T09:00:00+10:00"
    _write_csv(path, rows, fieldnames)
    _sync_manifest_hash(bundle, "receipt_transactions")


def _sync_manifest_hash(bundle: Path, dataset_name: str) -> None:
    manifest_path = bundle / "manifest.csv"
    manifest_rows, manifest_fields = _read_csv(manifest_path)
    data_path = bundle / f"{dataset_name}.csv"
    for row in manifest_rows:
        if row["dataset_name"] == dataset_name:
            row["file_hash"] = file_hash(data_path)
    _write_csv(manifest_path, manifest_rows, manifest_fields)


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
