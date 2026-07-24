"""PostgreSQL integration tests for deterministic risk-priority scoring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select

from scecs.database import create_database_engine, create_session_factory, session_scope
from scecs.ingestion.service import load_bundle
from scecs.models.procurement import SyntheticOutcomeObservation
from scecs.models.scoring import CandidateRiskContribution, CandidateRiskEvaluation
from scecs.models.source_control import PipelineRun
from scecs.models.workflow import ExceptionEpisode
from scecs.risk.service import score_operational_candidates

FIXTURE = Path("data/sample/synthetic_ci")
AS_OF = datetime(2026, 6, 30, 18, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Return a migrated PostgreSQL engine loaded with the CI operational fixture."""

    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")
    load_result = load_bundle(FIXTURE)
    assert load_result.passed
    return create_database_engine()


@pytest.mark.integration
def test_risk_priority_engine_scores_and_persists_ci_fixture(engine: Engine) -> None:
    """Full CI fixture scoring should persist candidates and all rule contributions."""

    result = score_operational_candidates(as_of=AS_OF, run_reference="RISK-CI-FIXTURE")

    assert result.evaluated_count > 0
    assert result.inserted_count == result.evaluated_count
    assert result.existing_count == 0
    with engine.connect() as connection:
        candidate_count = int(
            connection.execute(select(func.count()).select_from(CandidateRiskEvaluation)).scalar_one()
        )
        contribution_count = int(
            connection.execute(select(func.count()).select_from(CandidateRiskContribution)).scalar_one()
        )
        outcome_count = int(
            connection.execute(select(func.count()).select_from(SyntheticOutcomeObservation)).scalar_one()
        )
        score_min, score_max = connection.execute(
            select(func.min(CandidateRiskEvaluation.score), func.max(CandidateRiskEvaluation.score))
        ).one()
        rule_versions = set(
            connection.execute(
                select(PipelineRun.release_version).where(PipelineRun.run_reference == "RISK-CI-FIXTURE")
            ).scalars()
        )

    assert candidate_count == result.evaluated_count
    assert contribution_count == result.evaluated_count * 12
    assert outcome_count == 0
    assert Decimal(str(score_min)) >= Decimal("0")
    assert Decimal(str(score_max)) <= Decimal("100")
    assert rule_versions == {"RPR-1.0.0"}


@pytest.mark.integration
def test_duplicate_scoring_run_is_idempotent(engine: Engine) -> None:
    """Repeating the same scoring run reference should not duplicate candidates or contributions."""

    first = score_operational_candidates(as_of=AS_OF, run_reference="RISK-IDEMPOTENT")
    second = score_operational_candidates(as_of=AS_OF, run_reference="RISK-IDEMPOTENT")

    with engine.connect() as connection:
        contribution_count = int(
            connection.execute(
                select(func.count())
                .select_from(CandidateRiskContribution)
                .join(
                    CandidateRiskEvaluation,
                    CandidateRiskEvaluation.id == CandidateRiskContribution.candidate_evaluation_id,
                )
                .join(PipelineRun, PipelineRun.id == CandidateRiskEvaluation.pipeline_run_id)
                .where(PipelineRun.run_reference == "RISK-IDEMPOTENT")
            ).scalar_one()
        )

    assert first.inserted_count == first.evaluated_count
    assert second.inserted_count == 0
    assert second.existing_count == first.evaluated_count
    assert contribution_count == first.evaluated_count * 12


@pytest.mark.integration
def test_evaluation_only_data_cannot_influence_scores(engine: Engine) -> None:
    """Hidden synthetic outcome labels should not affect deterministic scores."""

    before = score_operational_candidates(as_of=AS_OF, run_reference="RISK-BEFORE-OUTCOME")
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        candidate = session.execute(
            select(CandidateRiskEvaluation).join(PipelineRun).where(
                PipelineRun.run_reference == before.run_reference
            )
        ).scalars().first()
        assert candidate is not None
        session.add(
            SyntheticOutcomeObservation(
                po_line_id=candidate.po_line_id,
                site_id=candidate.site_id,
                outcome_window_start=AS_OF.date(),
                outcome_window_end=AS_OF.date(),
                generator_version="test-hidden-label",
                seed_reference="must-not-influence-score",
                outcome_payload={"would_have_been_bad": True, "score": 100},
            )
        )

    after = score_operational_candidates(as_of=AS_OF, run_reference="RISK-AFTER-OUTCOME")
    with engine.connect() as connection:
        before_rows = {
            row.po_line_id: (Decimal(str(row.score)), row.input_fingerprint)
            for row in connection.execute(
                select(
                    CandidateRiskEvaluation.po_line_id,
                    CandidateRiskEvaluation.score,
                    CandidateRiskEvaluation.input_fingerprint,
                )
                .join(PipelineRun)
                .where(PipelineRun.run_reference == before.run_reference)
            )
        }
        after_rows = {
            row.po_line_id: (Decimal(str(row.score)), row.input_fingerprint)
            for row in connection.execute(
                select(
                    CandidateRiskEvaluation.po_line_id,
                    CandidateRiskEvaluation.score,
                    CandidateRiskEvaluation.input_fingerprint,
                )
                .join(PipelineRun)
                .where(PipelineRun.run_reference == after.run_reference)
            )
        }

    assert before_rows == after_rows


@pytest.mark.integration
def test_scoring_links_existing_active_episode_without_modifying_episode(engine: Engine) -> None:
    """A repeated score should link to an existing active episode when present."""

    baseline = score_operational_candidates(as_of=AS_OF, run_reference="RISK-LINK-BASE")
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        candidate = session.execute(
            select(CandidateRiskEvaluation).join(PipelineRun).where(
                PipelineRun.run_reference == baseline.run_reference,
                CandidateRiskEvaluation.disposition == "opening-eligible-no-workflow",
            )
        ).scalars().first()
        assert candidate is not None
        run = session.execute(
            select(PipelineRun).where(PipelineRun.run_reference == baseline.run_reference)
        ).scalar_one()
        episode = ExceptionEpisode(
            po_line_id=candidate.po_line_id,
            site_id=candidate.site_id,
            episode_sequence=int(uuid.uuid4().int % 1_000_000) + 1,
            opening_candidate_id=candidate.id,
            opening_run_id=run.id,
            current_state="open",
            calculated_severity=candidate.calculated_severity,
            effective_severity=candidate.calculated_severity,
            opened_at=AS_OF,
            current_candidate_id=candidate.id,
        )
        session.add(episode)

    linked = score_operational_candidates(as_of=AS_OF, run_reference="RISK-LINK-REPEAT")
    with engine.connect() as connection:
        linked_count = int(
            connection.execute(
                select(func.count())
                .select_from(CandidateRiskEvaluation)
                .join(PipelineRun)
                .where(
                    PipelineRun.run_reference == linked.run_reference,
                    CandidateRiskEvaluation.disposition == "linked-existing-active-episode",
                    CandidateRiskEvaluation.linked_episode_id.is_not(None),
                )
            ).scalar_one()
        )

    assert linked_count >= 1
