"""Core exception-episode lifecycle service.

This module owns workflow commands only. It does not calculate risk scores,
send notifications, run SLA processing, or automatically resolve exceptions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import FromClause

from scecs.models.master_data import User
from scecs.models.scoring import CandidateRiskEvaluation
from scecs.models.workflow import (
    ApprovalDecision,
    ApprovalRequest,
    EvidenceLink,
    EvidenceReference,
    ExceptionAction,
    ExceptionEpisode,
    ExceptionEventEnvelope,
    ExceptionStateEvent,
    OwnershipEvent,
    ResolutionRecord,
    SuppressionControl,
)

ACTIVE_STATES = frozenset(
    {"open", "assigned", "investigating", "action_agreed", "monitoring", "resolved", "suppressed"}
)
TERMINAL_STATES = frozenset({"closed"})
SUPPORTED_STATES = ACTIVE_STATES | TERMINAL_STATES
STATE_TRANSITIONS = frozenset(
    {
        ("open", "assigned"),
        ("assigned", "investigating"),
        ("investigating", "action_agreed"),
        ("action_agreed", "monitoring"),
        ("monitoring", "resolved"),
        ("resolved", "closed"),
        ("resolved", "investigating"),
    }
)


class WorkflowError(RuntimeError):
    """Base workflow command error."""


class InvalidTransitionError(WorkflowError):
    """Raised before persistence when a lifecycle transition is not allowed."""


class IdempotencyConflictError(WorkflowError):
    """Raised when an idempotency key is reused for a different command."""


class ApprovalControlError(WorkflowError):
    """Raised when approval controls are not satisfied."""


@dataclass(frozen=True)
class CommandContext:
    """Common audit metadata for workflow commands."""

    actor_user_id: uuid.UUID
    actor_type: str = "human"
    effective_at: datetime | None = None
    reason_code: str | None = None
    reason_text: str | None = None
    correlation_id: str | None = None
    causation_event_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CommandResult:
    """Result of an idempotent workflow command."""

    episode_id: uuid.UUID
    event_id: uuid.UUID
    idempotent_replay: bool = False


def open_episode_from_candidate(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    context: CommandContext,
    idempotency_key: str,
) -> CommandResult:
    """Open a new episode from an opening-eligible analytical candidate."""

    candidate = session.get(CandidateRiskEvaluation, candidate_id)
    if candidate is None:
        raise WorkflowError("candidate not found")
    if candidate.linked_episode_id is not None:
        event = _event_by_idempotency(session, candidate.linked_episode_id, idempotency_key)
        if event is None:
            event = _first_event(session, candidate.linked_episode_id)
        return CommandResult(candidate.linked_episode_id, event.id, True)
    if candidate.disposition != "opening-eligible-no-workflow":
        raise WorkflowError("candidate is not opening-eligible for workflow opening")
    existing_active = session.execute(
        select(ExceptionEpisode).where(
            ExceptionEpisode.po_line_id == candidate.po_line_id,
            ExceptionEpisode.site_id == candidate.site_id,
            ExceptionEpisode.closed_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        before_payload = _episode_payload(existing_active)
        candidate.linked_episode_id = existing_active.id
        candidate.disposition = "linked-existing-active-episode"
        event = _create_event(
            session,
            existing_active,
            idempotency_key,
            "candidate_linked",
            context,
            before_payload=before_payload,
            after_payload=before_payload | {"linked_candidate_id": str(candidate.id)},
            pipeline_run_id=candidate.pipeline_run_id,
            rule_version_id=candidate.rule_version_id,
        )
        return CommandResult(existing_active.id, event.id)

    episode = ExceptionEpisode(
        po_line_id=candidate.po_line_id,
        site_id=candidate.site_id,
        episode_sequence=_next_episode_sequence(session, candidate.po_line_id, candidate.site_id),
        opening_candidate_id=candidate.id,
        opening_run_id=candidate.pipeline_run_id,
        current_state="open",
        calculated_severity=candidate.calculated_severity,
        effective_severity=candidate.calculated_severity,
        opened_at=_effective_at(context),
        current_candidate_id=candidate.id,
    )
    session.add(episode)
    session.flush()
    event = _create_event(
        session,
        episode,
        idempotency_key,
        "state_changed",
        context,
        before_payload=None,
        after_payload={"state": "open", "candidate_id": str(candidate.id)},
        pipeline_run_id=candidate.pipeline_run_id,
        rule_version_id=candidate.rule_version_id,
    )
    session.add(
        ExceptionStateEvent(
            event_envelope_id=event.id,
            from_state=None,
            to_state="open",
            transition_reason="candidate_opening",
            authority="workflow_service",
        )
    )
    candidate.linked_episode_id = episode.id
    candidate.disposition = "opened-new-episode"
    return CommandResult(episode.id, event.id)


def transition_episode(
    session: Session,
    episode_id: uuid.UUID,
    to_state: str,
    *,
    context: CommandContext,
    idempotency_key: str,
    approval_user_id: uuid.UUID | None = None,
    resolution_payload: dict[str, object] | None = None,
) -> CommandResult:
    """Transition an episode through the supported lifecycle matrix."""

    episode = _episode(session, episode_id)
    existing = _event_by_idempotency(session, episode.id, idempotency_key)
    if existing is not None and existing.event_type in {"state_changed", "reopened"}:
        return CommandResult(episode.id, existing.id, True)
    if existing is not None:
        raise IdempotencyConflictError("idempotency key reused for a different command")
    from_state = episode.current_state
    _validate_transition(from_state, to_state)
    if to_state in {"resolved", "closed"}:
        _validate_material_approval(context.actor_user_id, approval_user_id)
        _validate_authorised_approver(session, approval_user_id, _effective_at(context))

    resolution_id = None
    if to_state == "resolved":
        resolution = _create_resolution(session, episode, context, approval_user_id, resolution_payload or {})
        resolution_id = resolution.id
    if to_state == "closed":
        _approval(
            session,
            episode,
            "closure",
            context.actor_user_id,
            approval_user_id,
            context.reason_text or "human-controlled closure",
            None,
        )

    before = _episode_payload(episode)
    episode.current_state = to_state
    if to_state == "closed":
        episode.closed_at = _effective_at(context)
    if to_state == "investigating" and from_state == "resolved":
        transition_reason = "reopened"
    else:
        transition_reason = f"{from_state}_to_{to_state}"
    event = _create_event(
        session,
        episode,
        idempotency_key,
        "state_changed" if transition_reason != "reopened" else "reopened",
        context,
        before_payload=before,
        after_payload=_episode_payload(episode),
    )
    session.add(
        ExceptionStateEvent(
            event_envelope_id=event.id,
            from_state=from_state,
            to_state=to_state,
            transition_reason=transition_reason,
            authority="human_controlled" if to_state in {"resolved", "closed"} else "workflow_service",
            resolution_id=resolution_id,
        )
    )
    return CommandResult(episode.id, event.id)


def assign_episode(
    session: Session,
    episode_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    *,
    context: CommandContext,
    idempotency_key: str,
) -> CommandResult:
    """Assign or reassign an active episode and preserve owner change evidence."""

    episode = _episode(session, episode_id)
    existing = _idempotent_event(session, episode.id, idempotency_key, "ownership_changed")
    if existing is not None:
        return CommandResult(episode.id, existing.id, True)
    if episode.current_state not in ACTIVE_STATES:
        raise InvalidTransitionError("closed episodes cannot be assigned")
    previous_owner = episode.current_owner_user_id
    before = _episode_payload(episode)
    episode.current_owner_user_id = owner_user_id
    if episode.current_state == "open":
        episode.current_state = "assigned"
    event = _create_event(
        session,
        episode,
        idempotency_key,
        "ownership_changed",
        context,
        before_payload=before,
        after_payload=_episode_payload(episode) | {"new_owner_user_id": str(owner_user_id)},
    )
    session.add(
        OwnershipEvent(
            episode_id=episode.id,
            event_envelope_id=event.id,
            ownership_sequence=_next_sequence(
                session,
                OwnershipEvent.__table__,
                "ownership_sequence",
                episode.id,
            ),
            previous_owner_user_id=previous_owner,
            new_owner_user_id=owner_user_id,
            effective_from=_effective_at(context),
            authority="workflow_service",
        )
    )
    if before["state"] == "open":
        session.add(
            ExceptionStateEvent(
                event_envelope_id=event.id,
                from_state="open",
                to_state="assigned",
                transition_reason="assignment",
                authority="workflow_service",
            )
        )
    return CommandResult(episode.id, event.id)


def add_investigation_note(
    session: Session,
    episode_id: uuid.UUID,
    note_text: str,
    *,
    context: CommandContext,
    idempotency_key: str,
) -> CommandResult:
    """Append an investigation note as immutable action evidence."""

    return _append_action(
        session,
        episode_id,
        "investigation_note",
        "recorded",
        {"note": note_text},
        context=context,
        idempotency_key=idempotency_key,
        allowed_states={"investigating"},
    )


def create_action_agreement(
    session: Session,
    episode_id: uuid.UUID,
    action_payload: dict[str, object],
    *,
    context: CommandContext,
    idempotency_key: str,
    action_owner_user_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
) -> CommandResult:
    """Create the action agreement and move Investigating -> Action Agreed."""

    transition_episode(
        session,
        episode_id,
        "action_agreed",
        context=context,
        idempotency_key=f"{idempotency_key}:state",
    )
    return _append_action(
        session,
        episode_id,
        "action_agreement",
        "agreed",
        action_payload,
        context=context,
        idempotency_key=idempotency_key,
        action_owner_user_id=action_owner_user_id,
        due_at=due_at,
        allowed_states={"action_agreed"},
    )


def update_action_agreement(
    session: Session,
    episode_id: uuid.UUID,
    previous_action_id: uuid.UUID,
    action_payload: dict[str, object],
    *,
    context: CommandContext,
    idempotency_key: str,
) -> CommandResult:
    """Append an updated action agreement without editing the old action row."""

    return _append_action(
        session,
        episode_id,
        "action_agreement",
        "updated",
        action_payload,
        context=context,
        idempotency_key=idempotency_key,
        allowed_states={"action_agreed", "monitoring"},
        supersedes_action_id=previous_action_id,
    )


def add_monitoring_observation(
    session: Session,
    episode_id: uuid.UUID,
    observation_payload: dict[str, object],
    *,
    context: CommandContext,
    idempotency_key: str,
) -> CommandResult:
    """Append monitoring evidence."""

    return _append_action(
        session,
        episode_id,
        "monitoring_observation",
        "recorded",
        observation_payload,
        context=context,
        idempotency_key=idempotency_key,
        allowed_states={"monitoring"},
    )


def suppress_episode(
    session: Session,
    episode_id: uuid.UUID,
    *,
    reason_code: str,
    reason_text: str,
    evidence_reference: str,
    expires_at: datetime,
    approver_user_id: uuid.UUID,
    context: CommandContext,
    idempotency_key: str,
) -> CommandResult:
    """Suppress an active episode through independent approval and evidence."""

    episode = _episode(session, episode_id)
    existing = _idempotent_event(session, episode.id, idempotency_key, "state_changed")
    if existing is not None:
        return CommandResult(episode.id, existing.id, True)
    if episode.current_state not in ACTIVE_STATES or episode.current_state == "suppressed":
        raise InvalidTransitionError("episode is not suppressible")
    if not reason_code or not reason_text or not evidence_reference:
        raise ApprovalControlError("suppression requires reason and evidence")
    if expires_at <= _effective_at(context):
        raise ApprovalControlError("suppression expiry must be in the future")
    _validate_material_approval(context.actor_user_id, approver_user_id)
    _validate_authorised_approver(session, approver_user_id, _effective_at(context))
    prior_state = episode.current_state
    before = _episode_payload(episode)
    approval_request = _approval(
        session,
        episode,
        "suppression",
        context.actor_user_id,
        approver_user_id,
        reason_text,
        expires_at,
    )
    evidence = _evidence(session, evidence_reference)
    suppression = SuppressionControl(
        episode_id=episode.id,
        approval_request_id=approval_request.id,
        prior_state=prior_state,
        reason_code=reason_code,
        starts_at=_effective_at(context),
        expires_at=expires_at,
        recurrence_criteria={},
    )
    session.add(suppression)
    session.flush()
    session.add(
        EvidenceLink(
            evidence_reference_id=evidence.id,
            target_type="suppression_control",
            target_id=suppression.id,
            link_reason="suppression_evidence",
        )
    )
    episode.current_state = "suppressed"
    event = _create_event(
        session,
        episode,
        idempotency_key,
        "state_changed",
        context,
        before_payload=before,
        after_payload=_episode_payload(episode) | {"suppression_control_id": str(suppression.id)},
    )
    session.add(
        ExceptionStateEvent(
            event_envelope_id=event.id,
            from_state=prior_state,
            to_state="suppressed",
            transition_reason="approved_suppression",
            authority="human_controlled",
            suppression_control_id=suppression.id,
        )
    )
    return CommandResult(episode.id, event.id)


def _append_action(
    session: Session,
    episode_id: uuid.UUID,
    category: str,
    status: str,
    payload: dict[str, object],
    *,
    context: CommandContext,
    idempotency_key: str,
    allowed_states: set[str],
    action_owner_user_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
    supersedes_action_id: uuid.UUID | None = None,
) -> CommandResult:
    episode = _episode(session, episode_id)
    existing = _idempotent_event(session, episode.id, idempotency_key, "action_recorded")
    if existing is not None:
        return CommandResult(episode.id, existing.id, True)
    if episode.current_state not in allowed_states:
        raise InvalidTransitionError(f"{category} is not allowed from {episode.current_state}")
    event = _create_event(
        session,
        episode,
        idempotency_key,
        "action_recorded",
        context,
        before_payload=None,
        after_payload={"category": category, "status": status, "payload": payload},
    )
    session.add(
        ExceptionAction(
            episode_id=episode.id,
            event_envelope_id=event.id,
            action_sequence=_next_sequence(
                session,
                ExceptionAction.__table__,
                "action_sequence",
                episode.id,
            ),
            action_category=category,
            action_status=status,
            action_owner_user_id=action_owner_user_id,
            due_at=due_at,
            action_payload=payload,
            supersedes_action_id=supersedes_action_id,
        )
    )
    return CommandResult(episode.id, event.id)


def _create_resolution(
    session: Session,
    episode: ExceptionEpisode,
    context: CommandContext,
    approver_user_id: uuid.UUID | None,
    payload: dict[str, object],
) -> ResolutionRecord:
    approval_request = _approval(
        session,
        episode,
        "resolution",
        context.actor_user_id,
        approver_user_id,
        str(payload.get("residual_risk_statement", context.reason_text or "human-controlled resolution")),
        None,
    )
    resolution = ResolutionRecord(
        episode_id=episode.id,
        resolution_sequence=_next_sequence(
            session,
            ResolutionRecord.__table__,
            "resolution_sequence",
            episode.id,
        ),
        resolution_category=str(payload.get("resolution_category", "protected_requirement_covered")),
        cause_code=str(payload.get("cause_code", "human_verified")),
        resolver_user_id=context.actor_user_id,
        residual_risk_statement=str(payload.get("residual_risk_statement", "Human-controlled resolution.")),
        monitoring_result=payload.get("monitoring_result")
        if isinstance(payload.get("monitoring_result"), str)
        else None,
        approval_request_id=approval_request.id,
        current_candidate_id=episode.current_candidate_id,
    )
    session.add(resolution)
    session.flush()
    return resolution


def _approval(
    session: Session,
    episode: ExceptionEpisode,
    request_type: str,
    requester_user_id: uuid.UUID,
    approver_user_id: uuid.UUID | None,
    reason: str,
    expires_at: datetime | None,
) -> ApprovalRequest:
    if approver_user_id is None:
        raise ApprovalControlError(f"{request_type} requires independent approval")
    _validate_material_approval(requester_user_id, approver_user_id)
    _validate_authorised_approver(session, approver_user_id, datetime.now(UTC))
    request = ApprovalRequest(
        episode_id=episode.id,
        request_reference=f"{request_type}-{uuid.uuid4().hex}",
        request_type=request_type,
        requester_user_id=requester_user_id,
        requested_payload={"request_type": request_type},
        reason=reason,
        expires_at=expires_at,
    )
    session.add(request)
    session.flush()
    session.add(
        ApprovalDecision(
            approval_request_id=request.id,
            decision_role="authorised_approver",
            approver_user_id=approver_user_id,
            outcome="approved",
            independence_check_passed=True,
        )
    )
    return request


def _evidence(session: Session, external_reference: str) -> EvidenceReference:
    existing = session.execute(
        select(EvidenceReference).where(
            EvidenceReference.evidence_source == "workflow_service",
            EvidenceReference.external_reference == external_reference,
            EvidenceReference.evidence_version == "1",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    evidence = EvidenceReference(
        evidence_type="suppression_approval",
        label=external_reference,
        evidence_source="workflow_service",
        external_reference=external_reference,
        evidence_version="1",
        availability_status="available",
    )
    session.add(evidence)
    session.flush()
    return evidence


def _create_event(
    session: Session,
    episode: ExceptionEpisode,
    idempotency_key: str,
    event_type: str,
    context: CommandContext,
    *,
    before_payload: dict[str, object] | None,
    after_payload: dict[str, object] | None,
    pipeline_run_id: uuid.UUID | None = None,
    rule_version_id: uuid.UUID | None = None,
) -> ExceptionEventEnvelope:
    event = ExceptionEventEnvelope(
        episode_id=episode.id,
        event_sequence=_next_event_sequence(session, episode.id),
        idempotency_key=idempotency_key,
        event_type=event_type,
        effective_at=_effective_at(context),
        actor_user_id=context.actor_user_id,
        actor_type=context.actor_type,
        reason_code=context.reason_code,
        reason_text=context.reason_text,
        correlation_id=context.correlation_id,
        causation_event_id=context.causation_event_id,
        pipeline_run_id=pipeline_run_id,
        rule_version_id=rule_version_id,
        before_payload=before_payload,
        after_payload=after_payload,
    )
    session.add(event)
    session.flush()
    return event


def _idempotent_event(
    session: Session, episode_id: uuid.UUID, idempotency_key: str, event_type: str
) -> ExceptionEventEnvelope | None:
    event = _event_by_idempotency(session, episode_id, idempotency_key)
    if event is None:
        return None
    if event.event_type != event_type:
        raise IdempotencyConflictError("idempotency key reused for a different command")
    return event


def _event_by_idempotency(
    session: Session, episode_id: uuid.UUID, idempotency_key: str
) -> ExceptionEventEnvelope | None:
    return session.execute(
        select(ExceptionEventEnvelope).where(
            ExceptionEventEnvelope.episode_id == episode_id,
            ExceptionEventEnvelope.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def _first_event(session: Session, episode_id: uuid.UUID) -> ExceptionEventEnvelope:
    return session.execute(
        select(ExceptionEventEnvelope)
        .where(ExceptionEventEnvelope.episode_id == episode_id)
        .order_by(ExceptionEventEnvelope.event_sequence)
        .limit(1)
    ).scalar_one()


def _validate_transition(from_state: str, to_state: str) -> None:
    if from_state not in SUPPORTED_STATES or to_state not in SUPPORTED_STATES:
        raise InvalidTransitionError(f"unsupported state transition {from_state}->{to_state}")
    if (from_state, to_state) not in STATE_TRANSITIONS:
        raise InvalidTransitionError(f"invalid transition {from_state}->{to_state}")


def is_transition_allowed(from_state: str, to_state: str) -> bool:
    """Return whether the core workflow matrix allows a transition."""

    return (
        from_state in SUPPORTED_STATES
        and to_state in SUPPORTED_STATES
        and (from_state, to_state) in STATE_TRANSITIONS
    )


def _validate_material_approval(actor_user_id: uuid.UUID, approver_user_id: uuid.UUID | None) -> None:
    if approver_user_id is None:
        raise ApprovalControlError("material decision requires approval")
    if approver_user_id == actor_user_id:
        raise ApprovalControlError("material decision prohibits self-approval")


def _validate_authorised_approver(session: Session, approver_user_id: uuid.UUID | None, effective_at: datetime) -> None:
    if approver_user_id is None:
        raise ApprovalControlError("material decision requires approval")
    approver = session.get(User, approver_user_id)
    if approver is None or approver.actor_type != "human":
        raise ApprovalControlError("approval requires an authorised human user")
    if approver.active_from > effective_at or (approver.active_to is not None and approver.active_to <= effective_at):
        raise ApprovalControlError("approval requires an active authorised user")


def _episode(session: Session, episode_id: uuid.UUID) -> ExceptionEpisode:
    episode = session.get(ExceptionEpisode, episode_id)
    if episode is None:
        raise WorkflowError("episode not found")
    return episode


def _next_episode_sequence(session: Session, po_line_id: uuid.UUID, site_id: uuid.UUID) -> int:
    value = session.execute(
        select(func.coalesce(func.max(ExceptionEpisode.episode_sequence), 0)).where(
            ExceptionEpisode.po_line_id == po_line_id,
            ExceptionEpisode.site_id == site_id,
        )
    ).scalar_one()
    return int(value) + 1


def _next_event_sequence(session: Session, episode_id: uuid.UUID) -> int:
    value = session.execute(
        select(func.coalesce(func.max(ExceptionEventEnvelope.event_sequence), 0)).where(
            ExceptionEventEnvelope.episode_id == episode_id
        )
    ).scalar_one()
    return int(value) + 1


def _next_sequence(session: Session, table: FromClause, column_name: str, episode_id: uuid.UUID) -> int:
    statement: Select[tuple[int]] = select(func.coalesce(func.max(table.c[column_name]), 0)).where(
        table.c.episode_id == episode_id
    )
    value = session.execute(statement).scalar_one()
    return int(value) + 1


def _episode_payload(episode: ExceptionEpisode) -> dict[str, object]:
    return {
        "episode_id": str(episode.id),
        "state": episode.current_state,
        "owner_user_id": str(episode.current_owner_user_id) if episode.current_owner_user_id else None,
        "current_candidate_id": str(episode.current_candidate_id) if episode.current_candidate_id else None,
        "closed_at": episode.closed_at.isoformat() if episode.closed_at else None,
    }


def _effective_at(context: CommandContext) -> datetime:
    return (context.effective_at or datetime.now(UTC)).astimezone(UTC)
