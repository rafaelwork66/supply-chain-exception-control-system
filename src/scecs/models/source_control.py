"""Source, pipeline control, reconciliation, and publication tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scecs.models.base import Base, RecordedTimestampMixin, UuidPrimaryKeyMixin


class SourceSystem(UuidPrimaryKeyMixin, Base):
    """Registry of simulated source systems without credentials."""

    __tablename__ = "source_systems"
    __table_args__ = (UniqueConstraint("source_code"),)

    source_code: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class PipelineRun(UuidPrimaryKeyMixin, Base):
    """Immutable orchestration attempt for ingestion, scoring, or publication."""

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        UniqueConstraint("run_reference"),
        CheckConstraint(
            "status in ('pending','running','success','failed','cancelled')", name="status"
        ),
    )

    run_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    run_type: Mapped[str] = mapped_column(String(40), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_version: Mapped[str | None] = mapped_column(String(80))
    configuration_hash: Mapped[str | None] = mapped_column(String(128))
    is_publication_eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    bundle_reference: Mapped[str | None] = mapped_column(String(255))
    manifest_hash: Mapped[str | None] = mapped_column(String(128))
    bundle_fingerprint: Mapped[str | None] = mapped_column(String(128))
    upstream_generator_version: Mapped[str | None] = mapped_column(String(80))
    source_row_count: Mapped[int | None] = mapped_column(Integer)
    accepted_row_count: Mapped[int | None] = mapped_column(Integer)
    rejected_row_count: Mapped[int | None] = mapped_column(Integer)
    failure_reason: Mapped[str | None] = mapped_column(Text)


class SourceLoad(UuidPrimaryKeyMixin, Base):
    """One delivered dataset object within a pipeline run."""

    __tablename__ = "source_loads"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "source_system_id", "dataset_type", "object_ref"),
    )

    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=False
    )
    source_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_systems.id"), nullable=False
    )
    dataset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    upstream_source_load_id: Mapped[uuid.UUID | None] = mapped_column()
    upstream_pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column()
    manifest_dataset_name: Mapped[str | None] = mapped_column(String(80))
    manifest_file_name: Mapped[str | None] = mapped_column(String(255))
    manifest_file_hash: Mapped[str | None] = mapped_column(String(128))


class PipelineStepResult(UuidPrimaryKeyMixin, Base):
    """Result of one named step attempt inside a pipeline run."""

    __tablename__ = "pipeline_step_results"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "step_name", "attempt_number"),
        CheckConstraint("attempt_number > 0", name="positive_attempt_number"),
        CheckConstraint(
            "status in ('pending','running','success','failed','skipped')", name="status"
        ),
    )

    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_hash: Mapped[str | None] = mapped_column(String(128))
    output_hash: Mapped[str | None] = mapped_column(String(128))
    error_classification: Mapped[str | None] = mapped_column(String(80))


class RejectedRecord(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Validation failure, rejection, or quarantine metadata for a source row."""

    __tablename__ = "rejected_records"
    __table_args__ = (
        CheckConstraint(
            "disposition in ('reject_row','quarantine_row','stop_dataset','stop_run','warning')",
            name="disposition",
        ),
    )

    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    source_load_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_loads.id"))
    dataset_name: Mapped[str | None] = mapped_column(String(80))
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    source_natural_key: Mapped[str | None] = mapped_column(String(255))
    raw_row_fingerprint: Mapped[str | None] = mapped_column(String(128))
    source_row_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    defect_code: Mapped[str] = mapped_column(String(80), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(80))
    observed_value_hash: Mapped[str | None] = mapped_column(String(128))
    classification: Mapped[str | None] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    disposition: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    notes: Mapped[str | None] = mapped_column(Text)
    rejected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReconciliationResult(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Control-total comparison for a pipeline run stage."""

    __tablename__ = "reconciliation_results"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "stage_name", "metric_name"),
        CheckConstraint("difference_count >= 0", name="nonnegative_difference_count"),
    )

    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=False
    )
    stage_name: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    difference_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_blocking: Mapped[bool] = mapped_column(nullable=False, default=False)
    inserted_count: Mapped[int | None] = mapped_column(Integer)
    existing_count: Mapped[int | None] = mapped_column(Integer)
    conflicting_count: Mapped[int | None] = mapped_column(Integer)
    rejected_count: Mapped[int | None] = mapped_column(Integer)
    matched_target_count: Mapped[int | None] = mapped_column(Integer)
    total_table_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(20))
    explanation: Mapped[str | None] = mapped_column(Text)


class AnalyticsPublication(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Immutable reporting publication manifest and latest-success pointer support."""

    __tablename__ = "analytics_publications"
    __table_args__ = (
        UniqueConstraint("publication_reference"),
        CheckConstraint("status in ('success','failed','superseded')", name="status"),
    )

    publication_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    reconciliation_hash: Mapped[str | None] = mapped_column(String(128))
    is_current_success: Mapped[bool] = mapped_column(nullable=False, default=False)
