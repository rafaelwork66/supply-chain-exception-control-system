"""PostgreSQL integration tests for the Power BI reporting layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from scecs.database import create_database_engine, create_session_factory, session_scope
from scecs.ingestion.service import load_bundle
from scecs.models.scoring import CandidateRiskEvaluation
from scecs.risk.service import score_operational_candidates
from scecs.workflow.service import (
    CommandContext,
    assign_episode,
    create_action_agreement,
    open_episode_from_candidate,
    suppress_episode,
    transition_episode,
)

FIXTURE = Path("data/sample/synthetic_ci")
AS_OF = datetime(2026, 6, 30, 18, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def reporting_engine() -> Engine:
    """Return migrated PostgreSQL populated with source, risk, workflow, and reporting data."""

    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")
    load_result = load_bundle(FIXTURE)
    assert load_result.passed
    score_result = score_operational_candidates(as_of=AS_OF, run_reference="REPORTING-CI-SCORING")
    assert score_result.evaluated_count > 0
    engine = create_database_engine()
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        actor, owner, approver = _human_users(session)
        candidate_ids = _opening_candidate_ids(session, 3)
        assert len(candidate_ids) >= 3

        suppressed_episode_id = open_episode_from_candidate(
            session,
            candidate_ids[0],
            context=_context(actor, "reporting-open-suppressed"),
            idempotency_key=f"reporting-open-suppressed-{candidate_ids[0]}",
        ).episode_id
        suppress_episode(
            session,
            suppressed_episode_id,
            reason_code="reporting_validation",
            reason_text="Reporting validation suppression.",
            evidence_reference=f"REPORTING-EVIDENCE-{uuid.uuid4()}",
            expires_at=AS_OF + timedelta(days=14),
            approver_user_id=approver,
            context=_context(actor, "reporting-suppress"),
            idempotency_key=f"reporting-suppress-{suppressed_episode_id}",
        )

        closed_episode_id = open_episode_from_candidate(
            session,
            candidate_ids[1],
            context=_context(actor, "reporting-open-closed"),
            idempotency_key=f"reporting-open-closed-{candidate_ids[1]}",
        ).episode_id
        assign_episode(
            session,
            closed_episode_id,
            owner,
            context=_context(actor, "reporting-assign"),
            idempotency_key=f"reporting-assign-{closed_episode_id}",
        )
        transition_episode(
            session,
            closed_episode_id,
            "investigating",
            context=_context(actor, "reporting-investigate"),
            idempotency_key=f"reporting-investigate-{closed_episode_id}",
        )
        create_action_agreement(
            session,
            closed_episode_id,
            {"action": "Reporting validation action agreement."},
            context=_context(actor, "reporting-action"),
            idempotency_key=f"reporting-action-{closed_episode_id}",
            action_owner_user_id=owner,
        )
        transition_episode(
            session,
            closed_episode_id,
            "monitoring",
            context=_context(actor, "reporting-monitor"),
            idempotency_key=f"reporting-monitor-{closed_episode_id}",
        )
        transition_episode(
            session,
            closed_episode_id,
            "resolved",
            context=_context(actor, "reporting-resolve"),
            idempotency_key=f"reporting-resolve-{closed_episode_id}",
            approval_user_id=approver,
        )
        transition_episode(
            session,
            closed_episode_id,
            "closed",
            context=_context(actor, "reporting-close"),
            idempotency_key=f"reporting-close-{closed_episode_id}",
            approval_user_id=approver,
        )

        active_open_result = open_episode_from_candidate(
            session,
            candidate_ids[2],
            context=_context(actor, "reporting-open-active"),
            idempotency_key=f"reporting-open-active-{candidate_ids[2]}",
        )
        assert active_open_result.episode_id
        active_candidate = session.get(CandidateRiskEvaluation, candidate_ids[2])
        assert active_candidate is not None
        session.execute(
            text(
                """
                update purchase_order_line_versions
                set unit_price_aud = null,
                    line_value_aud = null
                where po_line_id = :po_line_id
                """
            ),
            {"po_line_id": active_candidate.po_line_id},
        )

        _add_pipeline_children(session, actor)

    return engine


@pytest.mark.integration
def test_reporting_schema_and_views_exist(reporting_engine: Engine) -> None:
    """Every approved reporting object should exist as a PostgreSQL view."""

    expected = {
        "dim_date",
        "dim_exception",
        "dim_site",
        "dim_supplier",
        "dim_product",
        "dim_user",
        "dim_exception_state",
        "dim_severity",
        "dim_rule_component",
        "rpt_exception_summary",
        "rpt_exception_events",
        "rpt_risk_assessments",
        "rpt_risk_components",
        "rpt_approvals",
        "rpt_suppressions",
        "rpt_pipeline_runs",
    }
    with reporting_engine.connect() as connection:
        actual = {
            str(row[0])
            for row in connection.execute(
                text(
                    """
                    select table_name
                    from information_schema.views
                    where table_schema = 'reporting'
                    """
                )
            )
        }

    assert expected <= actual


@pytest.mark.integration
def test_exception_summary_grain_and_state_reconciliation(reporting_engine: Engine) -> None:
    """Exception summary should preserve one row per episode and governed state flags."""

    with reporting_engine.connect() as connection:
        source_count = connection.execute(text("select count(*) from exception_episodes")).scalar_one()
        view_count = connection.execute(text("select count(*) from reporting.rpt_exception_summary")).scalar_one()
        duplicate_count = connection.execute(
            text(
                """
                select count(*)
                from (
                    select episode_id
                    from reporting.rpt_exception_summary
                    group by episode_id
                    having count(*) > 1
                ) duplicates
                """
            )
        ).scalar_one()
        source_states = connection.execute(
            text(
                """
                select
                    count(*) filter (
                        where current_state in (
                            'open', 'assigned', 'investigating', 'action_agreed',
                            'monitoring', 'resolved'
                        )
                    ) as active_operational_count,
                    count(*) filter (where current_state = 'closed' and closed_at is not null) as closed_count,
                    count(*) filter (where current_state = 'suppressed') as suppressed_count
                from exception_episodes
                """
            )
        ).one()
        reporting_states = connection.execute(
            text(
                """
                select
                    count(*) filter (where is_active_operational) as active_operational_count,
                    count(*) filter (where is_closed) as closed_count,
                    count(*) filter (where is_suppressed) as suppressed_count
                from reporting.rpt_exception_summary
                """
            )
        ).one()

    assert view_count == source_count
    assert duplicate_count == 0
    assert reporting_states == source_states


@pytest.mark.integration
def test_residual_quantity_and_null_exposure_preservation(reporting_engine: Engine) -> None:
    """Residual quantity should be non-negative and missing exposure should remain NULL."""

    with reporting_engine.connect() as connection:
        negative_residual_count = connection.execute(
            text(
                """
                select count(*)
                from reporting.rpt_exception_summary
                where residual_base_quantity < 0
                """
            )
        ).scalar_one()
        null_exposure_count = connection.execute(
            text(
                """
                select count(*)
                from reporting.rpt_exception_summary
                where residual_value_aud is null
                  and exposure_value_available = false
                """
            )
        ).scalar_one()

    assert negative_residual_count == 0
    assert null_exposure_count >= 1


@pytest.mark.integration
def test_candidate_and_risk_component_reporting_logic(reporting_engine: Engine) -> None:
    """Candidate-not-opened and component arithmetic should follow governed stored fields."""

    with reporting_engine.connect() as connection:
        candidate_not_opened = connection.execute(
            text(
                """
                select count(*)
                from reporting.rpt_risk_assessments
                where is_candidate_not_opened
                """
            )
        ).scalar_one()
        expected_candidate_not_opened = connection.execute(
            text(
                """
                select count(*)
                from candidate_risk_evaluations
                where disposition = 'opening-eligible-no-workflow'
                  and linked_episode_id is null
                """
            )
        ).scalar_one()
        arithmetic_failures = connection.execute(
            text(
                """
                select count(*)
                from reporting.rpt_risk_components
                where applied_points <> gross_points + cap_adjustment
                """
            )
        ).scalar_one()
        duplicate_components = connection.execute(
            text(
                """
                select count(*)
                from (
                    select candidate_evaluation_id, component_code
                    from reporting.rpt_risk_components
                    group by candidate_evaluation_id, component_code
                    having count(*) > 1
                ) duplicates
                """
            )
        ).scalar_one()

    assert candidate_not_opened == expected_candidate_not_opened
    assert arithmetic_failures == 0
    assert duplicate_components == 0


@pytest.mark.integration
def test_approval_and_suppression_reporting_reconciliation(reporting_engine: Engine) -> None:
    """Approval and suppression views should reconcile to operational controls."""

    with reporting_engine.connect() as connection:
        request_count = connection.execute(
            text("select count(distinct approval_request_id) from reporting.rpt_approvals")
        ).scalar_one()
        source_request_count = connection.execute(text("select count(*) from approval_requests")).scalar_one()
        decision_count = connection.execute(
            text("select count(distinct approval_decision_id) from reporting.rpt_approvals")
        ).scalar_one()
        source_decision_count = connection.execute(text("select count(*) from approval_decisions")).scalar_one()
        self_approval_violations = connection.execute(
            text("select count(*) from reporting.rpt_approvals where is_self_approval_violation")
        ).scalar_one()
        suppression_count = connection.execute(text("select count(*) from reporting.rpt_suppressions")).scalar_one()
        source_suppression_count = connection.execute(text("select count(*) from suppression_controls")).scalar_one()

    assert request_count == source_request_count
    assert decision_count == source_decision_count
    assert self_approval_violations == 0
    assert suppression_count == source_suppression_count


@pytest.mark.integration
def test_pipeline_child_count_reconciliation(reporting_engine: Engine) -> None:
    """Pipeline view child counts should reconcile to source child tables."""

    with reporting_engine.connect() as connection:
        mismatches = connection.execute(
            text(
                """
                select count(*)
                from reporting.rpt_pipeline_runs r
                where r.source_load_count <> (
                    select count(*) from source_loads sl where sl.pipeline_run_id = r.pipeline_run_id
                )
                   or r.step_count <> (
                    select count(*) from pipeline_step_results psr where psr.pipeline_run_id = r.pipeline_run_id
                )
                   or r.blocking_reconciliation_count <> (
                    select count(*)
                    from reconciliation_results rr
                    where rr.pipeline_run_id = r.pipeline_run_id
                      and rr.is_blocking
                )
                   or r.rejected_record_count <> (
                    select count(*) from rejected_records rej where rej.pipeline_run_id = r.pipeline_run_id
                )
                   or r.publication_count <> (
                    select count(*) from analytics_publications ap where ap.pipeline_run_id = r.pipeline_run_id
                )
                """
            )
        ).scalar_one()

    assert mismatches == 0


def _human_users(session: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    users = list(
        session.execute(
            text(
                """
                select id
                from users
                where actor_type = 'human'
                order by user_code
                limit 3
                """
            )
        ).scalars()
    )
    assert len(users) >= 3
    return (uuid.UUID(str(users[0])), uuid.UUID(str(users[1])), uuid.UUID(str(users[2])))


def _opening_candidate_ids(session: Session, count: int) -> list[uuid.UUID]:
    values = list(
        session.execute(
            text(
                """
                select c.id
                from candidate_risk_evaluations c
                where c.disposition = 'opening-eligible-no-workflow'
                  and c.linked_episode_id is null
                order by c.score desc, c.evaluated_at, c.id
                limit :count
                """
            ),
            {"count": count},
        ).scalars()
    )
    return [uuid.UUID(str(value)) for value in values]


def _context(actor_user_id: uuid.UUID, reason_code: str) -> CommandContext:
    return CommandContext(
        actor_user_id=actor_user_id,
        effective_at=AS_OF,
        reason_code=reason_code,
        reason_text=reason_code.replace("-", " "),
        correlation_id=f"reporting-test-{reason_code}",
    )


def _add_pipeline_children(session: Session, actor_user_id: uuid.UUID) -> None:
    run_id = session.execute(
        text(
            """
            insert into pipeline_runs (
                run_reference, run_type, trigger_type, status, started_at, finished_at,
                source_row_count, accepted_row_count, rejected_row_count,
                release_version, configuration_hash, is_publication_eligible
            )
            values (
                :run_reference, 'reporting_validation', 'manual', 'success', :started_at,
                :finished_at, 10, 9, 1, 'test', 'reporting-test', true
            )
            returning id
            """
        ),
        {
            "run_reference": f"REPORTING-PIPELINE-{uuid.uuid4().hex[:8]}",
            "started_at": AS_OF,
            "finished_at": AS_OF + timedelta(minutes=5),
        },
    ).scalar_one()
    source_system_id = session.execute(text("select id from source_systems order by source_code limit 1")).scalar_one()
    source_load_id = session.execute(
        text(
            """
            insert into source_loads (
                pipeline_run_id, source_system_id, dataset_type, object_ref, content_hash,
                schema_version, extracted_at, received_at, row_count
            )
            values (
                :run_id, :source_system_id, 'reporting_validation', :object_ref,
                :content_hash, 'v1', :as_of, :as_of, 10
            )
            returning id
            """
        ),
        {
            "run_id": run_id,
            "source_system_id": source_system_id,
            "object_ref": f"reporting-{uuid.uuid4().hex[:8]}.csv",
            "content_hash": f"hash-{uuid.uuid4().hex}",
            "as_of": AS_OF,
        },
    ).scalar_one()
    session.execute(
        text(
            """
            insert into pipeline_step_results (
                pipeline_run_id, step_name, attempt_number, status, started_at, finished_at,
                input_hash, output_hash, error_classification
            )
            values
                (:run_id, 'extract', 1, 'success', :as_of, :as_of, null, 'extract-output', null),
                (:run_id, 'validate', 1, 'failed', :as_of, :as_of, 'extract-output', null, 'test_failure')
            """
        ),
        {"run_id": run_id, "as_of": AS_OF},
    )
    session.execute(
        text(
            """
            insert into reconciliation_results (
                pipeline_run_id, stage_name, metric_name, source_count, target_count,
                difference_count, is_blocking, rejected_count, status, explanation
            )
            values (
                :run_id, 'validation', 'rows', 10, 9, 1, true, 1, 'failed',
                'Reporting validation row'
            )
            """
        ),
        {"run_id": run_id},
    )
    session.execute(
        text(
            """
            insert into rejected_records (
                pipeline_run_id, source_load_id, dataset_name, source_row_number,
                source_natural_key, raw_row_fingerprint, source_row_ref, defect_code,
                field_name, observed_value_hash, classification, severity, disposition,
                resolution_status, notes, rejected_at
            )
            values (
                :run_id, :source_load_id, 'reporting_validation', 1, 'natural-key',
                'fingerprint', 'row-1', 'REPORTING_TEST', 'field', 'hash', 'data_quality',
                'warning', 'warning', 'open', 'Reporting validation row', :as_of
            )
            """
        ),
        {"run_id": run_id, "source_load_id": source_load_id, "as_of": AS_OF},
    )
    session.execute(
        text(
            """
            insert into analytics_publications (
                publication_reference, pipeline_run_id, status, published_at, manifest,
                reconciliation_hash, is_current_success
            )
            values (
                :publication_reference, :run_id, 'success', :as_of, '{}',
                'reporting-hash', false
            )
            """
        ),
        {
            "publication_reference": f"REPORTING-PUBLICATION-{uuid.uuid4().hex[:8]}",
            "run_id": run_id,
            "as_of": AS_OF,
        },
    )
    assert actor_user_id
