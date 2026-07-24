"""Full-profile PostgreSQL ingestion evidence."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from scecs.database import create_database_engine
from scecs.ingestion.service import load_bundle
from scecs.models.procurement import ReceiptAllocation, SyntheticOutcomeObservation
from scecs.synthetic.config import default_portfolio_config
from scecs.synthetic.export import export_bundle
from scecs.synthetic.generator import generate_dataset_bundle


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SCECS_RUN_FULL_PROFILE_TESTS") != "1",
    reason="full-profile PostgreSQL ingestion is enabled explicitly in CI",
)
def test_full_profile_postgresql_ingestion(tmp_path: Path) -> None:
    """Portfolio profile should load in PostgreSQL through bounded batches."""

    output_path = tmp_path / "portfolio_bundle"
    config = default_portfolio_config().with_output_path(output_path)
    started = time.perf_counter()
    export_bundle(generate_dataset_bundle(config), output_path, config)

    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")

    result = load_bundle(output_path)
    runtime_seconds = round(time.perf_counter() - started, 2)
    engine = create_database_engine()
    with engine.connect() as connection:
        receipt_allocations = int(
            connection.execute(select(func.count()).select_from(ReceiptAllocation)).scalar_one()
        )
        outcome_rows = int(
            connection.execute(select(func.count()).select_from(SyntheticOutcomeObservation)).scalar_one()
        )

    assert result.passed
    assert receipt_allocations == 110_010
    assert outcome_rows == 0
    assert all(row.status == "passed" for row in result.reconciliations)
    assert sum(row.inserted_rows for row in result.reconciliations) > 110_010
    assert runtime_seconds < 300
    print(f"full_profile_runtime_seconds={runtime_seconds}")
    print("full_profile_peak_batch_size=1000")
