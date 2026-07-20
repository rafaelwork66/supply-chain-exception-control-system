"""Exception workflow, approval, evidence, and audit tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from scecs.models.base import Base, RecordedTimestampMixin, UuidPrimaryKeyMixin

ACTIVE_STATES_SQL = (
    "'open','assigned','investigating','action_agreed','monitoring','resolved','suppressed'"
)
ALL_STATES_SQL = f"{ACTIVE_STATES_SQL},'closed'"


class ExceptionEpisode(UuidPrimaryKeyMixin, Base):
    """Operational case identity for one PO-line/site risk episode."""

    __tablename__ = "exception_episodes"
    __table_args__ = (
        UniqueConstraint("po_line_id", "site_id", "episode_sequence"),
        Index(
            "uq_exception_episodes_active_line_site",
            "po_line_id",
            "site_id",
            unique=True,
            postgresql_where=text("current_state <> 'closed'"),
        ),
        CheckConstraint(f"current_state in ({ALL_STATES_SQL})", name="current_state"),
        CheckConstraint(
            "calculated_severity in ('monitor','low','medium','high','critical')",
            name="calculated_severity",
        ),
        CheckConstraint(
            "effective_severity in ('monitor','low','medium','high','critical')",
            name="effective_severity",
        ),
        CheckConstraint("episode_sequence > 0", name="positive_episode_sequence"),
    )

    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False)
    episode_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_risk_evaluations.id"),
        nullable=False,
    )
    opening_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=False
    )
    predecessor_episode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exception_episodes.id")
    )
    current_state: Mapped[str] = mapped_column(String(30), nullable=False)
    calculated_severity: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_severity: Mapped[str] = mapped_column(String(20), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    current_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_risk_evaluations.id")
    )


class ExceptionEventEnvelope(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Shared immutable audit envelope for controlled episode events."""

    __tablename__ = "exception_event_envelopes"
    __table_args__ = (
        UniqueConstraint("episode_id", "event_sequence"),
        CheckConstraint("event_sequence > 0", name="positive_event_sequence"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    reason_text: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(120))
    causation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exception_event_envelopes.id")
    )
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    rule_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rule_versions.id"))
    calendar_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calendar_versions.id")
    )
    before_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    after_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class ExceptionStateEvent(UuidPrimaryKeyMixin, Base):
    """Typed lifecycle transition event."""

    __tablename__ = "exception_state_events"
    __table_args__ = (
        UniqueConstraint("event_envelope_id"),
        CheckConstraint(
            f"from_state is null or from_state in ({ALL_STATES_SQL})", name="from_state"
        ),
        CheckConstraint(f"to_state in ({ALL_STATES_SQL})", name="to_state"),
        CheckConstraint(
            "(from_state is null and to_state = 'open') or from_state is not null",
            name="initial_event_opens_episode",
        ),
    )

    event_envelope_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_event_envelopes.id"),
        nullable=False,
    )
    from_state: Mapped[str | None] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    transition_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    authority: Mapped[str] = mapped_column(String(80), nullable=False)
    resolution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resolution_records.id"))
    suppression_control_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppression_controls.id")
    )


class ExceptionAction(UuidPrimaryKeyMixin, Base):
    """Appended operational action, contact, note, or plan record."""

    __tablename__ = "exception_actions"
    __table_args__ = (UniqueConstraint("episode_id", "action_sequence"),)

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    event_envelope_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_event_envelopes.id"), nullable=False
    )
    action_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action_category: Mapped[str] = mapped_column(String(80), nullable=False)
    action_status: Mapped[str] = mapped_column(String(40), nullable=False)
    action_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    supersedes_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exception_actions.id")
    )


class OwnershipEvent(UuidPrimaryKeyMixin, Base):
    """Assignment, reassignment, delegation, or unassignment event."""

    __tablename__ = "ownership_events"
    __table_args__ = (UniqueConstraint("episode_id", "ownership_sequence"),)

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    event_envelope_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_event_envelopes.id"), nullable=False
    )
    ownership_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    new_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    ownership_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ownership_mappings.id")
    )
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authority: Mapped[str] = mapped_column(String(80), nullable=False)


class SlaObligation(UuidPrimaryKeyMixin, Base):
    """Original SLA clock obligation separated from later SLA events."""

    __tablename__ = "sla_obligations"
    __table_args__ = (
        UniqueConstraint("episode_id", "sla_type", "obligation_sequence"),
        CheckConstraint("obligation_sequence > 0", name="positive_obligation_sequence"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    sla_type: Mapped[str] = mapped_column(String(60), nullable=False)
    obligation_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    calendar_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_versions.id"), nullable=False
    )
    severity_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    satisfied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SlaEvent(UuidPrimaryKeyMixin, Base):
    """SLA start, pause, resume, breach, escalation, or satisfaction event."""

    __tablename__ = "sla_events"
    __table_args__ = (UniqueConstraint("sla_obligation_id", "sla_event_sequence"),)

    sla_obligation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sla_obligations.id"), nullable=False
    )
    event_envelope_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_event_envelopes.id"), nullable=False
    )
    sla_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    sla_event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    business_minutes_consumed: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class ApprovalRequest(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Request for a controlled approval route."""

    __tablename__ = "approval_requests"
    __table_args__ = (UniqueConstraint("episode_id", "request_reference"),)

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    request_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    request_type: Mapped[str] = mapped_column(String(80), nullable=False)
    requester_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalDecision(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Role-specific approval decision or governance concurrence."""

    __tablename__ = "approval_decisions"
    __table_args__ = (
        UniqueConstraint("approval_request_id", "decision_role"),
        CheckConstraint(
            "outcome in ('approved','rejected','conditional','expired')", name="outcome"
        ),
    )

    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_requests.id"),
        nullable=False,
    )
    decision_role: Mapped[str] = mapped_column(String(80), nullable=False)
    approver_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    conditions: Mapped[str | None] = mapped_column(Text)
    independence_check_passed: Mapped[bool] = mapped_column(nullable=False)


class SuppressionControl(UuidPrimaryKeyMixin, Base):
    """Approved time-bound suppression interval for an active episode."""

    __tablename__ = "suppression_controls"
    __table_args__ = (
        CheckConstraint(f"prior_state in ({ACTIVE_STATES_SQL})", name="prior_state"),
        CheckConstraint("expires_at > starts_at", name="valid_suppression_interval"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_requests.id"), nullable=False
    )
    prior_state: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recurrence_criteria: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    sla_consumed_minutes_at_pause: Mapped[int | None] = mapped_column(Integer)


class EvidenceReference(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Portfolio-safe evidence metadata without binary document storage."""

    __tablename__ = "evidence_references"
    __table_args__ = (
        UniqueConstraint("evidence_source", "external_reference", "evidence_version"),
        CheckConstraint(
            "availability_status in ('available','missing','broken','corrected')",
            name="availability_status",
        ),
    )

    evidence_type: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(80), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(40), nullable=False)
    integrity_hash: Mapped[str | None] = mapped_column(String(128))
    availability_status: Mapped[str] = mapped_column(String(30), nullable=False)
    correction_of_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_references.id")
    )


class EvidenceLink(UuidPrimaryKeyMixin, Base):
    """Constrained generic evidence-to-object bridge."""

    __tablename__ = "evidence_links"
    __table_args__ = (
        UniqueConstraint("evidence_reference_id", "target_type", "target_id"),
        CheckConstraint(
            "target_type in ("
            "'event','action','approval_request','approval_decision','suppression_control',"
            "'resolution','receipt','source_correction')",
            name="target_type",
        ),
    )

    evidence_reference_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_references.id"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    link_reason: Mapped[str | None] = mapped_column(String(120))


class ResolutionRecord(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Human-controlled resolution assertion retained for audit."""

    __tablename__ = "resolution_records"
    __table_args__ = (
        UniqueConstraint("episode_id", "resolution_sequence"),
        CheckConstraint("resolution_sequence > 0", name="positive_resolution_sequence"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    resolution_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_category: Mapped[str] = mapped_column(String(80), nullable=False)
    cause_code: Mapped[str] = mapped_column(String(80), nullable=False)
    resolver_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    residual_risk_statement: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4))
    outcome_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monitoring_result: Mapped[str | None] = mapped_column(Text)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approval_requests.id")
    )
    current_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_risk_evaluations.id")
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EpisodeRelationship(UuidPrimaryKeyMixin, RecordedTimestampMixin, Base):
    """Directed relationship between exception episodes."""

    __tablename__ = "episode_relationships"
    __table_args__ = (
        UniqueConstraint("from_episode_id", "to_episode_id", "relationship_type"),
        CheckConstraint("from_episode_id <> to_episode_id", name="no_self_relationship"),
    )

    from_episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    to_episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exception_episodes.id"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(80), nullable=False)
    relationship_reason: Mapped[str | None] = mapped_column(Text)
