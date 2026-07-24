"""Publication pointer management for successful ingestion runs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from scecs.ingestion.manifest import BundleManifest
from scecs.ingestion.reconciliation import DatasetReconciliation
from scecs.models.source_control import AnalyticsPublication, PipelineRun


def publish_successful_run(
    session: Session,
    run: PipelineRun,
    manifest: BundleManifest,
    reconciliations: list[DatasetReconciliation],
) -> AnalyticsPublication:
    """Atomically mark the latest successful operational ingestion publication."""

    payload = {
        "manifest_hash": manifest.manifest_hash,
        "configuration_hash": manifest.configuration_hash,
        "generator_version": manifest.generator_version,
        "schema_version": manifest.schema_version,
        "as_of_timestamp": manifest.as_of_timestamp,
        "datasets": [item.__dict__ for item in reconciliations],
    }
    reconciliation_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    session.execute(
        update(AnalyticsPublication)
        .where(AnalyticsPublication.is_current_success.is_(True))
        .values(is_current_success=False, status="superseded")
    )
    publication = AnalyticsPublication(
        publication_reference=f"PUB-{run.run_reference}",
        pipeline_run_id=run.id,
        status="success",
        published_at=datetime.now(UTC),
        manifest=payload,
        reconciliation_hash=reconciliation_hash,
        is_current_success=True,
    )
    session.add(publication)
    run.status = "success"
    run.finished_at = datetime.now(UTC)
    run.is_publication_eligible = True
    return publication
