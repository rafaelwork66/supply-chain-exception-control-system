"""Governed UI action availability and command wrappers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from scecs.workflow.service import (
    ACTIVE_STATES,
    CommandContext,
    CommandResult,
    add_investigation_note,
    add_monitoring_observation,
    assign_episode,
    create_action_agreement,
    open_episode_from_candidate,
    suppress_episode,
    transition_episode,
    update_action_agreement,
)

LIFECYCLE_STATES = (
    "open",
    "assigned",
    "investigating",
    "action_agreed",
    "monitoring",
    "resolved",
    "closed",
    "suppressed",
)


@dataclass(frozen=True)
class ActionAvailability:
    """Action visibility/enablement flags for the current actor and episode."""

    can_open_candidate: bool = False
    can_assign: bool = False
    can_reassign: bool = False
    can_start_investigation: bool = False
    can_add_investigation_note: bool = False
    can_create_action_agreement: bool = False
    can_update_action_agreement: bool = False
    can_start_monitoring: bool = False
    can_add_monitoring_observation: bool = False
    can_resolve: bool = False
    can_close: bool = False
    can_reopen: bool = False
    can_suppress: bool = False


def availability_for_state(state: str, *, has_action_agreement: bool = False) -> ActionAvailability:
    """Return UI actions that should be offered for a lifecycle state."""

    return ActionAvailability(
        can_assign=state in ACTIVE_STATES,
        can_reassign=state in ACTIVE_STATES,
        can_start_investigation=state == "assigned",
        can_add_investigation_note=state == "investigating",
        can_create_action_agreement=state == "investigating",
        can_update_action_agreement=state in {"action_agreed", "monitoring"} and has_action_agreement,
        can_start_monitoring=state == "action_agreed",
        can_add_monitoring_observation=state == "monitoring",
        can_resolve=state == "monitoring",
        can_close=state == "resolved",
        can_reopen=state == "resolved",
        can_suppress=state in ACTIVE_STATES and state != "suppressed",
    )


def candidate_open_available(disposition: str, linked_episode_id: uuid.UUID | None) -> bool:
    """Return whether a candidate can be offered for exception opening."""

    return disposition == "opening-eligible-no-workflow" and linked_episode_id is None


def independent_approver_available(actor_user_id: uuid.UUID, approver_user_id: uuid.UUID | None) -> bool:
    """Return whether a material action has a different selected approver."""

    return approver_user_id is not None and approver_user_id != actor_user_id


def build_context(actor_user_id: uuid.UUID, reason_code: str, reason_text: str | None = None) -> CommandContext:
    """Build audit context for a user-triggered Streamlit command."""

    return CommandContext(
        actor_user_id=actor_user_id,
        effective_at=datetime.now(UTC),
        reason_code=reason_code,
        reason_text=reason_text,
        correlation_id=f"streamlit-{uuid.uuid4().hex[:12]}",
    )


def open_candidate(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    reason_text: str,
) -> CommandResult:
    """Open a candidate through the governed workflow service."""

    return open_episode_from_candidate(
        session,
        candidate_id,
        context=build_context(actor_user_id, "streamlit-candidate-open", reason_text),
        idempotency_key=f"streamlit-open-{candidate_id}-{uuid.uuid4().hex}",
    )


def assign_owner(
    session: Session,
    episode_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    reason_text: str,
) -> CommandResult:
    """Assign or reassign an episode through the governed workflow service."""

    return assign_episode(
        session,
        episode_id,
        owner_user_id,
        context=build_context(actor_user_id, "streamlit-assignment", reason_text),
        idempotency_key=f"streamlit-assign-{episode_id}-{uuid.uuid4().hex}",
    )


def move_to_investigating(
    session: Session,
    episode_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    reason_text: str,
) -> CommandResult:
    """Move Assigned -> Investigating."""

    return transition_episode(
        session,
        episode_id,
        "investigating",
        context=build_context(actor_user_id, "streamlit-start-investigation", reason_text),
        idempotency_key=f"streamlit-investigate-{episode_id}-{uuid.uuid4().hex}",
    )


def append_investigation_note(
    session: Session,
    episode_id: uuid.UUID,
    note_text: str,
    *,
    actor_user_id: uuid.UUID,
) -> CommandResult:
    """Append an investigation note."""

    return add_investigation_note(
        session,
        episode_id,
        note_text,
        context=build_context(actor_user_id, "streamlit-investigation-note", note_text),
        idempotency_key=f"streamlit-note-{episode_id}-{uuid.uuid4().hex}",
    )


def agree_action(
    session: Session,
    episode_id: uuid.UUID,
    action_payload: dict[str, object],
    *,
    actor_user_id: uuid.UUID,
    action_owner_user_id: uuid.UUID | None,
) -> CommandResult:
    """Create an action agreement."""

    return create_action_agreement(
        session,
        episode_id,
        action_payload,
        context=build_context(actor_user_id, "streamlit-action-agreement", str(action_payload.get("action"))),
        idempotency_key=f"streamlit-agreement-{episode_id}-{uuid.uuid4().hex}",
        action_owner_user_id=action_owner_user_id,
    )


def revise_action(
    session: Session,
    episode_id: uuid.UUID,
    previous_action_id: uuid.UUID,
    action_payload: dict[str, object],
    *,
    actor_user_id: uuid.UUID,
) -> CommandResult:
    """Append an updated action agreement."""

    return update_action_agreement(
        session,
        episode_id,
        previous_action_id,
        action_payload,
        context=build_context(actor_user_id, "streamlit-action-update", str(action_payload.get("action"))),
        idempotency_key=f"streamlit-agreement-update-{episode_id}-{uuid.uuid4().hex}",
    )


def move_to_monitoring(
    session: Session,
    episode_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    reason_text: str,
) -> CommandResult:
    """Move Action Agreed -> Monitoring."""

    return transition_episode(
        session,
        episode_id,
        "monitoring",
        context=build_context(actor_user_id, "streamlit-start-monitoring", reason_text),
        idempotency_key=f"streamlit-monitoring-{episode_id}-{uuid.uuid4().hex}",
    )


def append_monitoring_observation(
    session: Session,
    episode_id: uuid.UUID,
    observation_payload: dict[str, object],
    *,
    actor_user_id: uuid.UUID,
) -> CommandResult:
    """Append a monitoring observation."""

    return add_monitoring_observation(
        session,
        episode_id,
        observation_payload,
        context=build_context(actor_user_id, "streamlit-monitoring-observation", str(observation_payload)),
        idempotency_key=f"streamlit-observation-{episode_id}-{uuid.uuid4().hex}",
    )


def approve_resolution(
    session: Session,
    episode_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    approver_user_id: uuid.UUID,
    residual_risk_statement: str,
) -> CommandResult:
    """Resolve an episode through independent approval."""

    return transition_episode(
        session,
        episode_id,
        "resolved",
        context=build_context(actor_user_id, "streamlit-resolution", residual_risk_statement),
        idempotency_key=f"streamlit-resolve-{episode_id}-{uuid.uuid4().hex}",
        approval_user_id=approver_user_id,
        resolution_payload={"residual_risk_statement": residual_risk_statement},
    )


def approve_closure(
    session: Session,
    episode_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    approver_user_id: uuid.UUID,
    reason_text: str,
) -> CommandResult:
    """Close a resolved episode through independent approval."""

    return transition_episode(
        session,
        episode_id,
        "closed",
        context=build_context(actor_user_id, "streamlit-closure", reason_text),
        idempotency_key=f"streamlit-close-{episode_id}-{uuid.uuid4().hex}",
        approval_user_id=approver_user_id,
    )


def reopen_exception(
    session: Session,
    episode_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    reason_text: str,
) -> CommandResult:
    """Reopen a resolved episode as an event-backed transition."""

    return transition_episode(
        session,
        episode_id,
        "investigating",
        context=build_context(actor_user_id, "streamlit-reopen", reason_text),
        idempotency_key=f"streamlit-reopen-{episode_id}-{uuid.uuid4().hex}",
    )


def approve_suppression(
    session: Session,
    episode_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    approver_user_id: uuid.UUID,
    reason_code: str,
    reason_text: str,
    evidence_reference: str,
    expires_at: datetime,
) -> CommandResult:
    """Suppress an active episode through independent approval."""

    return suppress_episode(
        session,
        episode_id,
        reason_code=reason_code,
        reason_text=reason_text,
        evidence_reference=evidence_reference,
        expires_at=expires_at,
        approver_user_id=approver_user_id,
        context=build_context(actor_user_id, "streamlit-suppression", reason_text),
        idempotency_key=f"streamlit-suppress-{episode_id}-{uuid.uuid4().hex}",
    )
