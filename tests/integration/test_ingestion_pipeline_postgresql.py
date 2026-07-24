"""PostgreSQL integration tests for governed ingestion."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select

from scecs.database import create_database_engine
from scecs.ingestion.service import load_bundle, validate_bundle
from scecs.models import Base
from scecs.models.source_control import AnalyticsPublication
from scecs.synthetic.manifest import file_hash

FIXTURE = Path("data/sample/synthetic_ci")


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Return the configured PostgreSQL engine."""

    command.upgrade(Config("alembic.ini"), "head")
    return create_database_engine()


@pytest.mark.integration
def test_valid_sample_bundle_loads_and_reruns_idempotently(engine: Engine) -> None:
    """A valid operational fixture should publish once and rerun without duplicating domain rows."""

    first = load_bundle(FIXTURE)
    before_counts = _operational_counts(engine)
    second = load_bundle(FIXTURE)
    after_counts = _operational_counts(engine)

    assert first.passed
    assert second.passed
    assert before_counts == after_counts
    assert any(row.existing_rows > 0 for row in second.reconciliations)


@pytest.mark.integration
def test_failed_bundle_does_not_replace_current_publication(engine: Engine, tmp_path: Path) -> None:
    """A blocking validation failure should not replace the current successful publication pointer."""

    successful = load_bundle(FIXTURE)
    assert successful.passed
    current_before = _current_publication_reference(engine)

    bundle = tmp_path / "bundle"
    shutil.copytree(FIXTURE, bundle)
    _mutate_receipt_after_as_of(bundle)
    validation = validate_bundle(bundle)
    failed = load_bundle(bundle)
    current_after = _current_publication_reference(engine)

    assert not validation.passed
    assert not failed.passed
    assert current_before == current_after


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


def _current_publication_reference(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                select(AnalyticsPublication.publication_reference).where(
                    AnalyticsPublication.is_current_success.is_(True)
                )
            ).scalar_one()
        )


def _mutate_receipt_after_as_of(bundle: Path) -> None:
    path = bundle / "receipt_transactions.csv"
    rows, fieldnames = _read_csv(path)
    rows[0]["posted_at"] = "2026-07-01T09:00:00+10:00"
    _write_csv(path, rows, fieldnames)
    manifest_path = bundle / "manifest.csv"
    manifest_rows, manifest_fields = _read_csv(manifest_path)
    for row in manifest_rows:
        if row["dataset_name"] == "receipt_transactions":
            row["file_hash"] = file_hash(path)
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

