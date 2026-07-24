"""PostgreSQL integration tests for core exception workflow commands."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from scecs.database import create_database_engine, create_session_factory, session_scope
from scecs.ingestion.service import load_bundle
from scecs.models.master_data import User
from scecs.models.scoring import CandidateRiskEvaluation
from scecs.models.source_control import PipelineRun
from scecs.models.workflow import (
    ApprovalDecision,
    EvidenceLink,
    ExceptionAction,
    ExceptionEpisode,
    ExceptionEventEnvelope,
    ExceptionStateEvent,
    OwnershipEvent,
    SuppressionControl,
)
from scecs.risk.service import score_operational_candidates
from scecs.workflow.service import (
    ApprovalControlError,
    CommandContext,
    InvalidTransitionError,
    WorkflowError,
    add_investigation_note,
    add_monitoring_observation,
    assign_episode,
    create_action_agreement,
    open_episode_from_candidate,
    suppress_episode,
    transition_episode,
    update_action_agreement,
)

FIXTURE = Path("data/sample/synthetic_ci")
AS_OF = datetime(2026, 6, 30, 18, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Return migrated PostgreSQL with ingested CI data and scored candidates."""

    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")
    load_result = load_bundle(FIXTURE)
    assert load_result.passed
    score_result = score_operational_candidates(as_of=AS_OF, run_reference="WORKFLOW-CI-SCORING")
    assert score_result.evaluated_count > 0
    return create_database_engine()


@pytest.mark.integration
def test_candidate_opening_eligibility_and_one_active_episode_enforcement(engine: Engine) -> None:
    """Only opening-eligible candidates open episodes; later candidates link to the active episode."""

    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        actor, _, _ = _human_users(session)
        candidate = _fresh_candidate(session, "below-opening-threshold")

        with pytest.raises(WorkflowError):
            open_episode_from_candidate(
                session,
                candidate.id,
                context=_context(actor, "candidate-not-eligible"),
                idempotency_key=f"open-reject-{uuid.uuid4()}",
            )

        candidate.disposition = "opening-eligible-no-workflow"
        first = open_episode_from_candidate(
            session,
            candidate.id,
            context=_context(actor, "candidate-open"),
            idempotency_key=f"open-{candidate.id}",
        )
        replay = open_episode_from_candidate(
            session,
            candidate.id,
            context=_context(actor, "candidate-open"),
            idempotency_key=f"open-{candidate.id}",
        )
        duplicate_candidate = _duplicate_candidate(session, candidate)
        linked = open_episode_from_candidate(
            session,
            duplicate_candidate.id,
            context=_context(actor, "active-episode-link"),
            idempotency_key=f"link-{duplicate_candidate.id}",
        )

        active_count = int(
            session.execute(
                select(func.count()).select_from(ExceptionEpisode).where(
                    ExceptionEpisode.po_line_id == candidate.po_line_id,
                    ExceptionEpisode.site_id == candidate.site_id,
                    ExceptionEpisode.closed_at.is_(None),
                )
            ).scalar_one()
        )
        linked_event = session.get(ExceptionEventEnvelope, linked.event_id)

    assert first.episode_id == replay.episode_id
    assert replay.idempotent_replay
    assert linked.episode_id == first.episode_id
    assert duplicate_candidate.disposition == "linked-existing-active-episode"
    assert active_count == 1
    assert linked_event is not None
    assert linked_event.event_type == "candidate_linked"


@pytest.mark.integration
def test_valid_lifecycle_path_and_invalid_transition_prevention(engine: Engine) -> None:
    """The core state path should persist, while prohibited transitions fail before persistence."""

    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        actor, owner, approver = _human_users(session)
        episode_id = _open_fresh_episode(session, actor)

        with pytest.raises(InvalidTransitionError):
            transition_episode(
                session,
                episode_id,
                "monitoring",
                context=_context(actor, "invalid-skip"),
                idempotency_key=f"invalid-{uuid.uuid4()}",
            )

        assign_episode(
            session,
            episode_id,
            owner,
            context=_context(actor, "assign"),
            idempotency_key=f"assign-{uuid.uuid4()}",
        )
        transition_episode(
            session,
            episode_id,
            "investigating",
            context=_context(actor, "start-investigation"),
            idempotency_key=f"investigate-{uuid.uuid4()}",
        )
        action_result = create_action_agreement(
            session,
            episode_id,
            {"action": "expedite supplier confirmation", "owner": "procurement"},
            context=_context(actor, "agree-action"),
            idempotency_key=f"action-{uuid.uuid4()}",
            action_owner_user_id=owner,
        )
        transition_episode(
            session,
            episode_id,
            "monitoring",
            context=_context(actor, "start-monitoring"),
            idempotency_key=f"monitor-{uuid.uuid4()}",
        )
        transition_episode(
            session,
            episode_id,
            "resolved",
            context=_context(actor, "resolve"),
            idempotency_key=f"resolve-{uuid.uuid4()}",
            approval_user_id=approver,
            resolution_payload={
                "residual_risk_statement": "Supplier confirmation received and residual risk accepted.",
            },
        )
        transition_episode(
            session,
            episode_id,
            "closed",
            context=_context(actor, "close"),
            idempotency_key=f"close-{uuid.uuid4()}",
            approval_user_id=approver,
        )

        episode = session.get(ExceptionEpisode, episode_id)
        state_events = session.execute(
            select(ExceptionStateEvent)
            .join(ExceptionEventEnvelope, ExceptionEventEnvelope.id == ExceptionStateEvent.event_envelope_id)
            .where(ExceptionEventEnvelope.episode_id == episode_id)
            .order_by(ExceptionEventEnvelope.event_sequence)
        ).scalars().all()

    assert action_result.episode_id == episode_id
    assert episode is not None
    assert episode.current_state == "closed"
    assert [event.to_state for event in state_events] == [
        "open",
        "assigned",
        "investigating",
        "action_agreed",
        "monitoring",
        "resolved",
        "closed",
    ]


@pytest.mark.integration
def test_assignment_reassignment_notes_action_agreement_and_monitoring_observation(engine: Engine) -> None:
    """Assignments and operational notes/actions should append immutable evidence rows."""

    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        actor, first_owner, second_owner = _human_users(session)
        episode_id = _open_fresh_episode(session, actor)

        first_assignment = assign_episode(
            session,
            episode_id,
            first_owner,
            context=_context(actor, "assign"),
            idempotency_key=f"assign-first-{uuid.uuid4()}",
        )
        replay = assign_episode(
            session,
            episode_id,
            first_owner,
            context=_context(actor, "assign"),
            idempotency_key=next(
                event.idempotency_key
                for event in session.execute(
                    select(ExceptionEventEnvelope).where(ExceptionEventEnvelope.id == first_assignment.event_id)
                ).scalars()
            ),
        )
        assign_episode(
            session,
            episode_id,
            second_owner,
            context=_context(actor, "reassign"),
            idempotency_key=f"reassign-{uuid.uuid4()}",
        )
        transition_episode(
            session,
            episode_id,
            "investigating",
            context=_context(actor, "investigate"),
            idempotency_key=f"investigate-{uuid.uuid4()}",
        )
        add_investigation_note(
            session,
            episode_id,
            "Supplier confirmed a late dispatch risk; buyer is validating alternatives.",
            context=_context(actor, "note"),
            idempotency_key=f"note-{uuid.uuid4()}",
        )
        agreement = create_action_agreement(
            session,
            episode_id,
            {"action": "Split residual requirement across alternate supplier and expedited freight."},
            context=_context(actor, "agreement"),
            idempotency_key=f"agreement-{uuid.uuid4()}",
            action_owner_user_id=second_owner,
        )
        update_action_agreement(
            session,
            episode_id,
            _action_id_for_event(session, agreement.event_id),
            {"action": "Expedite confirmed quantity and source residual from backup supplier."},
            context=_context(actor, "agreement-update"),
            idempotency_key=f"agreement-update-{uuid.uuid4()}",
        )
        transition_episode(
            session,
            episode_id,
            "monitoring",
            context=_context(actor, "monitoring"),
            idempotency_key=f"monitoring-{uuid.uuid4()}",
        )
        add_monitoring_observation(
            session,
            episode_id,
            {"observation": "Expedited shipment booked; backup supplier PO pending."},
            context=_context(actor, "monitoring-observation"),
            idempotency_key=f"observation-{uuid.uuid4()}",
        )

        owners = session.execute(
            select(OwnershipEvent)
            .where(OwnershipEvent.episode_id == episode_id)
            .order_by(OwnershipEvent.ownership_sequence)
        ).scalars().all()
        actions = session.execute(
            select(ExceptionAction)
            .where(ExceptionAction.episode_id == episode_id)
            .order_by(ExceptionAction.action_sequence)
        ).scalars().all()

    assert replay.idempotent_replay
    assert len(owners) == 2
    assert owners[0].previous_owner_user_id is None
    assert owners[0].new_owner_user_id == first_owner
    assert owners[1].previous_owner_user_id == first_owner
    assert owners[1].new_owner_user_id == second_owner
    assert [action.action_category for action in actions] == [
        "investigation_note",
        "action_agreement",
        "action_agreement",
        "monitoring_observation",
    ]
    assert actions[2].supersedes_action_id == actions[1].id


@pytest.mark.integration
def test_human_controls_suppression_reopening_idempotency_and_immutable_history(engine: Engine) -> None:
    """Material controls should require independent approval and preserve append-only event history."""

    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        actor, owner, approver = _human_users(session)
        episode_id = _open_fresh_episode(session, actor)
        _move_to_monitoring(session, episode_id, actor, owner)

        with pytest.raises(ApprovalControlError):
            transition_episode(
                session,
                episode_id,
                "resolved",
                context=_context(actor, "self-resolve"),
                idempotency_key=f"self-resolve-{uuid.uuid4()}",
                approval_user_id=actor,
            )

        transition_episode(
            session,
            episode_id,
            "resolved",
            context=_context(actor, "approved-resolve"),
            idempotency_key=f"resolve-{uuid.uuid4()}",
            approval_user_id=approver,
        )
        reopened_key = f"reopen-{uuid.uuid4()}"
        reopened = transition_episode(
            session,
            episode_id,
            "investigating",
            context=_context(actor, "reopen"),
            idempotency_key=reopened_key,
        )
        reopened_replay = transition_episode(
            session,
            episode_id,
            "investigating",
            context=_context(actor, "reopen"),
            idempotency_key=reopened_key,
        )

        with pytest.raises(ApprovalControlError):
            suppress_episode(
                session,
                episode_id,
                reason_code="duplicate_supplier_commitment",
                reason_text="Supplier issue is already controlled by approved mitigation.",
                evidence_reference="WF-EVIDENCE-SELF",
                expires_at=AS_OF + timedelta(days=7),
                approver_user_id=actor,
                context=_context(actor, "self-suppress"),
                idempotency_key=f"self-suppress-{uuid.uuid4()}",
            )

        suppression = suppress_episode(
            session,
            episode_id,
            reason_code="duplicate_supplier_commitment",
            reason_text="Supplier issue is already controlled by approved mitigation.",
            evidence_reference=f"WF-EVIDENCE-{uuid.uuid4()}",
            expires_at=AS_OF + timedelta(days=7),
            approver_user_id=approver,
            context=_context(actor, "approved-suppress"),
            idempotency_key=f"suppress-{uuid.uuid4()}",
        )

        episode = session.get(ExceptionEpisode, episode_id)
        reopened_event = session.get(ExceptionEventEnvelope, reopened.event_id)
        event_count = int(
            session.execute(
                select(func.count()).select_from(ExceptionEventEnvelope).where(
                    ExceptionEventEnvelope.episode_id == episode_id
                )
            ).scalar_one()
        )
        approval_count = int(session.execute(select(func.count()).select_from(ApprovalDecision)).scalar_one())
        suppression_count = int(session.execute(select(func.count()).select_from(SuppressionControl)).scalar_one())
        evidence_link_count = int(session.execute(select(func.count()).select_from(EvidenceLink)).scalar_one())

    assert reopened_replay.idempotent_replay
    assert suppression.episode_id == episode_id
    assert episode is not None
    assert episode.current_state == "suppressed"
    assert reopened_event is not None
    assert reopened_event.event_type == "reopened"
    assert approval_count >= 2
    assert suppression_count >= 1
    assert evidence_link_count >= 1

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(DBAPIError):
                connection.execute(
                    text(
                        "update exception_event_envelopes "
                        "set reason_text = 'tampered' "
                        "where episode_id = :episode_id"
                    ),
                    {"episode_id": episode_id},
                )
        finally:
            transaction.rollback()

    with engine.connect() as connection:
        persisted_event_count = int(
            connection.execute(
                select(func.count())
                .select_from(ExceptionEventEnvelope)
                .where(ExceptionEventEnvelope.episode_id == episode_id)
            ).scalar_one()
        )

    assert persisted_event_count == event_count


def _human_users(session: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    users = list(
        session.execute(
            select(User.id).where(User.actor_type == "human").order_by(User.user_code).limit(3)
        ).scalars()
    )
    assert len(users) >= 3
    return users[0], users[1], users[2]


def _fresh_candidate(session: Session, disposition: str) -> CandidateRiskEvaluation:
    candidate = session.execute(
        select(CandidateRiskEvaluation)
        .where(CandidateRiskEvaluation.linked_episode_id.is_(None))
        .order_by(CandidateRiskEvaluation.score.desc(), CandidateRiskEvaluation.id)
        .limit(1)
    ).scalar_one()
    candidate.disposition = disposition
    return candidate


def _duplicate_candidate(session: Session, candidate: CandidateRiskEvaluation) -> CandidateRiskEvaluation:
    run = PipelineRun(
        run_reference=f"WORKFLOW-DUP-{uuid.uuid4()}",
        run_type="risk_scoring",
        trigger_type="manual",
        status="success",
        started_at=AS_OF,
        finished_at=AS_OF,
        release_version="RPR-1.0.0",
        configuration_hash="workflow-test",
        is_publication_eligible=False,
    )
    session.add(run)
    session.flush()
    duplicate = CandidateRiskEvaluation(
        pipeline_run_id=run.id,
        po_line_id=candidate.po_line_id,
        site_id=candidate.site_id,
        rule_version_id=candidate.rule_version_id,
        evaluated_at=AS_OF,
        input_fingerprint=f"duplicate-{uuid.uuid4()}",
        eligibility_status="eligible",
        score=Decimal(str(candidate.score)),
        calculated_severity=candidate.calculated_severity,
        score_confidence=candidate.score_confidence,
        disposition="opening-eligible-no-workflow",
        explanation_summary="Workflow duplicate candidate for active-episode enforcement.",
        missing_signal_payload={},
    )
    session.add(duplicate)
    session.flush()
    return duplicate


def _open_fresh_episode(session: Session, actor_user_id: uuid.UUID) -> uuid.UUID:
    candidate = _fresh_candidate(session, "opening-eligible-no-workflow")
    result = open_episode_from_candidate(
        session,
        candidate.id,
        context=_context(actor_user_id, "open"),
        idempotency_key=f"open-{candidate.id}",
    )
    return result.episode_id


def _move_to_monitoring(session: Session, episode_id: uuid.UUID, actor: uuid.UUID, owner: uuid.UUID) -> None:
    assign_episode(
        session,
        episode_id,
        owner,
        context=_context(actor, "assign"),
        idempotency_key=f"assign-{uuid.uuid4()}",
    )
    transition_episode(
        session,
        episode_id,
        "investigating",
        context=_context(actor, "investigate"),
        idempotency_key=f"investigate-{uuid.uuid4()}",
    )
    create_action_agreement(
        session,
        episode_id,
        {"action": "Operational mitigation agreed."},
        context=_context(actor, "agreement"),
        idempotency_key=f"agreement-{uuid.uuid4()}",
    )
    transition_episode(
        session,
        episode_id,
        "monitoring",
        context=_context(actor, "monitoring"),
        idempotency_key=f"monitoring-{uuid.uuid4()}",
    )


def _action_id_for_event(session: Session, event_id: uuid.UUID) -> uuid.UUID:
    return session.execute(select(ExceptionAction.id).where(ExceptionAction.event_envelope_id == event_id)).scalar_one()


def _context(actor_user_id: uuid.UUID, reason_code: str) -> CommandContext:
    return CommandContext(
        actor_user_id=actor_user_id,
        effective_at=AS_OF,
        reason_code=reason_code,
        reason_text=reason_code.replace("-", " "),
        correlation_id=f"workflow-test-{reason_code}",
    )
