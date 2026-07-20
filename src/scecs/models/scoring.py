"""Candidate risk and score contribution tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scecs.models.base import Base, UuidPrimaryKeyMixin


class CandidateRiskEvaluation(UuidPrimaryKeyMixin, Base):
    """Immutable analytical risk evaluation for one eligible line/site/run."""

    __tablename__ = "candidate_risk_evaluations"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "po_line_id", "site_id"),
        CheckConstraint("score >= 0 and score <= 100", name="score_range"),
        CheckConstraint(
            "calculated_severity in ('monitor','low','medium','high','critical')",
            name="calculated_severity",
        ),
        CheckConstraint(
            "disposition in ("
            "'below-opening-threshold',"
            "'opened-new-episode',"
            "'linked-existing-active-episode',"
            "'suppressed-by-existing-control',"
            "'ineligible-after-validation',"
            "'manual-review-data-insufficient',"
            "'scoring-error')",
            name="disposition",
        ),
    )

    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=False
    )
    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule_versions.id"), nullable=False
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    eligibility_status: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    calculated_severity: Mapped[str] = mapped_column(String(20), nullable=False)
    score_confidence: Mapped[str] = mapped_column(String(30), nullable=False)
    disposition: Mapped[str] = mapped_column(String(50), nullable=False)
    linked_episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exception_episodes.id"))
    explanation_summary: Mapped[str | None] = mapped_column(Text)
    missing_signal_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )


class CandidateRiskContribution(UuidPrimaryKeyMixin, Base):
    """One component contribution within a candidate risk evaluation."""

    __tablename__ = "candidate_risk_contributions"
    __table_args__ = (
        UniqueConstraint("candidate_evaluation_id", "component_code"),
        CheckConstraint(
            "availability_status in ('available-not-triggered','triggered','unavailable','invalid')",
            name="availability_status",
        ),
    )

    candidate_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_risk_evaluations.id"),
        nullable=False,
    )
    rule_component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rule_component_definitions.id")
    )
    component_code: Mapped[str] = mapped_column(String(80), nullable=False)
    component_family: Mapped[str] = mapped_column(String(80), nullable=False)
    availability_status: Mapped[str] = mapped_column(String(30), nullable=False)
    observed_value: Mapped[str | None] = mapped_column(String(160))
    comparator: Mapped[str | None] = mapped_column(String(20))
    threshold_value: Mapped[str | None] = mapped_column(String(80))
    triggered: Mapped[bool] = mapped_column(nullable=False)
    gross_points: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    applied_points: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    explanation_code: Mapped[str] = mapped_column(String(80), nullable=False)
    input_lineage: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
