"""PostgreSQL integration tests for Streamlit operational MVP services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from scecs.database import create_database_engine, create_session_factory, session_scope
from scecs.ingestion.service import load_bundle
from scecs.models.master_data import User
from scecs.models.scoring import CandidateRiskEvaluation
from scecs.models.workflow import ExceptionEventEnvelope
from scecs.risk.service import score_operational_candidates
from scecs.streamlit_app.actions import (
    agree_action,
    append_investigation_note,
    append_monitoring_observation,
    approve_resolution,
    approve_suppression,
    assign_owner,
    move_to_investigating,
    move_to_monitoring,
    open_candidate,
    reopen_exception,
)
from scecs.streamlit_app.queries import OperationalReadService

FIXTURE = Path("data/sample/synthetic_ci")
AS_OF = datetime(2026, 6, 30, 18, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Return migrated PostgreSQL with ingested CI data and scored candidates."""

    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")
    load_result = load_bundle(FIXTURE)
    assert load_result.passed
    score_result = score_operational_candidates(as_of=AS_OF, run_reference="STREAMLIT-MVP-SCORING")
    assert score_result.evaluated_count > 0
    return create_database_engine()


@pytest.mark.integration
def test_streamlit_read_models_cover_governed_workflow_journey(engine: Engine) -> None:
    """The UI read model should reflect governed command-service writes."""

    session_factory = create_session_factory(engine)
    read_service = OperationalReadService(engine)
    with session_scope(session_factory) as session:
        actor, owner, approver = _human_users(session)
        candidate = session.execute(
            select(CandidateRiskEvaluation)
            .where(
                CandidateRiskEvaluation.disposition == "opening-eligible-no-workflow",
                CandidateRiskEvaluation.linked_episode_id.is_(None),
            )
            .order_by(CandidateRiskEvaluation.score.desc())
            .limit(1)
        ).scalar_one()

        opened = open_candidate(
            session,
            candidate.id,
            actor_user_id=actor,
            reason_text="Open from Streamlit MVP test.",
        )
        assign_owner(
            session,
            opened.episode_id,
            owner,
            actor_user_id=actor,
            reason_text="Assign owner from Streamlit MVP test.",
        )
        move_to_investigating(
            session,
            opened.episode_id,
            actor_user_id=actor,
            reason_text="Investigate from Streamlit MVP test.",
        )
        append_investigation_note(
            session,
            opened.episode_id,
            "Supplier commitment and inventory exposure reviewed.",
            actor_user_id=actor,
        )
        agree_action(
            session,
            opened.episode_id,
            {"action": "Expedite confirmed quantity and monitor receipt."},
            actor_user_id=actor,
            action_owner_user_id=owner,
        )
        move_to_monitoring(
            session,
            opened.episode_id,
            actor_user_id=actor,
            reason_text="Action agreement ready for monitoring.",
        )
        append_monitoring_observation(
            session,
            opened.episode_id,
            {"observation": "Supplier confirmed expedited dispatch."},
            actor_user_id=actor,
        )
        approve_resolution(
            session,
            opened.episode_id,
            actor_user_id=actor,
            approver_user_id=approver,
            residual_risk_statement="Residual risk reviewed and accepted for MVP test.",
        )
        reopen_exception(
            session,
            opened.episode_id,
            actor_user_id=actor,
            reason_text="Reopened due to changed operational evidence.",
        )
        approve_suppression(
            session,
            opened.episode_id,
            actor_user_id=actor,
            approver_user_id=approver,
            reason_code="mvp_controlled_duplicate",
            reason_text="Suppressed with evidence for MVP test.",
            evidence_reference=f"MVP-EVIDENCE-{uuid.uuid4()}",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        episode_id = opened.episode_id

    queue_rows = read_service.exception_queue()
    detail = read_service.exception_detail(episode_id)
    summary = read_service.control_tower_summary()
    users = read_service.active_users()

    assert any(row.episode_id == episode_id for row in queue_rows)
    assert detail is not None
    assert detail.summary.state == "suppressed"
    assert detail.summary.owner_user_id == owner
    assert detail.risk_contributions
    assert detail.actions
    assert any(action.category == "investigation_note" for action in detail.actions)
    assert any(action.category == "action_agreement" for action in detail.actions)
    assert any(action.category == "monitoring_observation" for action in detail.actions)
    assert any(approval.request_type == "resolution" for approval in detail.approvals)
    assert detail.suppressions
    assert any(event.event_type == "reopened" for event in detail.audit_events)
    assert any(event.event_type == "state_changed" for event in detail.audit_events)
    assert summary.opening_eligible_candidates >= 0
    assert len(users) >= 3

    with engine.connect() as connection:
        persisted_events = list(
            connection.execute(
                select(ExceptionEventEnvelope.event_type)
                .where(ExceptionEventEnvelope.episode_id == episode_id)
                .order_by(ExceptionEventEnvelope.event_sequence)
            ).scalars()
        )

    assert "candidate_risk" not in {detail.summary.state, *persisted_events}


def _human_users(session: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    users = list(
        session.execute(select(User.id).where(User.actor_type == "human").order_by(User.user_code).limit(3)).scalars()
    )
    assert len(users) >= 3
    return users[0], users[1], users[2]
