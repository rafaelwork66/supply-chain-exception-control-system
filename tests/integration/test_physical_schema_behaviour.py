"""Behavioural PostgreSQL tests for the physical schema."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from scecs.database import create_database_engine


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Return the configured PostgreSQL engine."""

    return create_database_engine()


def execute_scalar(connection: Connection, statement: str, values: dict[str, object]) -> object:
    """Execute a statement and return the first scalar value."""

    return connection.execute(text(statement), values).scalar_one()


def new_suffix() -> str:
    """Return a compact unique suffix for test data."""

    return uuid.uuid4().hex[:10]


def migrate_to_head() -> None:
    """Apply all schema migrations."""

    command.upgrade(Config("alembic.ini"), "head")


def make_reference_context(connection: Connection, suffix: str) -> dict[str, object]:
    """Insert reference, source, PO, line, schedule, users, and one candidate."""

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    source_system_id = execute_scalar(
        connection,
        """
        insert into source_systems (source_code, display_name, source_type, is_active)
        values (:code, 'Synthetic ERP', 'erp', true)
        returning id
        """,
        {"code": f"ERP-{suffix}"},
    )
    pipeline_run_id = create_pipeline_run(connection, suffix, "initial")
    source_load_id = execute_scalar(
        connection,
        """
        insert into source_loads (
            pipeline_run_id, source_system_id, dataset_type, object_ref, content_hash,
            schema_version, extracted_at, received_at, row_count
        )
        values (
            :run_id, :source_system_id, 'purchase_orders', :object_ref, :content_hash,
            'v1', :now, :now, 1
        )
        returning id
        """,
        {
            "run_id": pipeline_run_id,
            "source_system_id": source_system_id,
            "object_ref": f"po-{suffix}.csv",
            "content_hash": f"hash-{suffix}",
            "now": now,
        },
    )
    site_id = create_site(connection, f"SITE-{suffix}", now)
    second_site_id = create_site(connection, f"SITE2-{suffix}", now)
    supplier_id = execute_scalar(
        connection,
        "insert into suppliers (supplier_code) values (:code) returning id",
        {"code": f"SUP-{suffix}"},
    )
    connection.execute(
        text(
            """
            insert into supplier_versions (
                supplier_id, display_name, supplier_category, effective_from, effective_to
            )
            values (:supplier_id, 'Synthetic Supplier', 'standard', :now, null)
            """
        ),
        {"supplier_id": supplier_id, "now": now},
    )
    product_id = execute_scalar(
        connection,
        "insert into products (sku) values (:sku) returning id",
        {"sku": f"SKU-{suffix}"},
    )
    connection.execute(
        text(
            """
            insert into product_versions (
                product_id, description, category, base_uom, handling_precision,
                effective_from, effective_to
            )
            values (:product_id, 'Synthetic Part', 'components', 'EA', 0, :now, null)
            """
        ),
        {"product_id": product_id, "now": now},
    )
    rule_version_id = execute_scalar(
        connection,
        """
        insert into rule_versions (
            rule_code, version, status, owner, rationale, approved_at, effective_from, effective_to
        )
        values (:rule_code, '1.0', 'active', 'governance', 'schema test', :now, :now, null)
        returning id
        """,
        {"rule_code": f"RULE-{suffix}", "now": now},
    )
    rule_component_id = execute_scalar(
        connection,
        """
        insert into rule_component_definitions (
            rule_version_id, component_code, component_family, max_points, metadata_json
        )
        values (:rule_version_id, 'late_commitment', 'supplier', 25, '{}')
        returning id
        """,
        {"rule_version_id": rule_version_id},
    )
    requester_user_id = create_user(connection, f"REQ-{suffix}", "Requester", now)
    approver_user_id = create_user(connection, f"APR-{suffix}", "Approver", now)
    purchase_order_id = execute_scalar(
        connection,
        """
        insert into purchase_orders (source_system_id, po_number)
        values (:source_system_id, :po_number)
        returning id
        """,
        {"source_system_id": source_system_id, "po_number": f"PO-{suffix}"},
    )
    connection.execute(
        text(
            """
            insert into purchase_order_versions (
                purchase_order_id, source_load_id, supplier_id, amendment_version,
                buyer_group, currency_code, order_date, order_status, effective_at
            )
            values (
                :purchase_order_id, :source_load_id, :supplier_id, 1, 'OPS',
                'USD', :order_date, 'open', :now
            )
            """
        ),
        {
            "purchase_order_id": purchase_order_id,
            "source_load_id": source_load_id,
            "supplier_id": supplier_id,
            "order_date": date(2026, 7, 1),
            "now": now,
        },
    )
    po_line_id = execute_scalar(
        connection,
        """
        insert into purchase_order_lines (purchase_order_id, canonical_line_key)
        values (:purchase_order_id, :line_key)
        returning id
        """,
        {"purchase_order_id": purchase_order_id, "line_key": f"PO-{suffix}-10"},
    )
    connection.execute(
        text(
            """
            insert into purchase_order_line_versions (
                po_line_id, source_load_id, product_id, site_id, amendment_version,
                ordered_quantity, order_uom, base_quantity, need_date, requested_date,
                line_status, effective_at
            )
            values (
                :po_line_id, :source_load_id, :product_id, :site_id, 1, 100,
                'EA', 100, :need_date, :need_date, 'open', :now
            )
            """
        ),
        {
            "po_line_id": po_line_id,
            "source_load_id": source_load_id,
            "product_id": product_id,
            "site_id": site_id,
            "need_date": date(2026, 8, 1),
            "now": now,
        },
    )
    schedule_id = execute_scalar(
        connection,
        """
        insert into delivery_schedules (
            po_line_id, source_schedule_key, schedule_version, scheduled_quantity,
            requested_date, confirmed_date, expected_date, schedule_status
        )
        values (:po_line_id, :schedule_key, 1, 100, :need_date, null, :need_date, 'open')
        returning id
        """,
        {
            "po_line_id": po_line_id,
            "schedule_key": f"SCH-{suffix}",
            "need_date": date(2026, 8, 1),
        },
    )
    candidate_id = create_candidate(
        connection,
        suffix,
        "opening",
        po_line_id,
        site_id,
        rule_version_id,
        score=60,
        disposition="opened-new-episode",
    )

    return {
        "now": now,
        "source_system_id": source_system_id,
        "pipeline_run_id": pipeline_run_id,
        "source_load_id": source_load_id,
        "site_id": site_id,
        "second_site_id": second_site_id,
        "supplier_id": supplier_id,
        "product_id": product_id,
        "rule_version_id": rule_version_id,
        "rule_component_id": rule_component_id,
        "requester_user_id": requester_user_id,
        "approver_user_id": approver_user_id,
        "purchase_order_id": purchase_order_id,
        "po_line_id": po_line_id,
        "schedule_id": schedule_id,
        "candidate_id": candidate_id,
    }


def create_pipeline_run(connection: Connection, suffix: str, label: str) -> object:
    """Insert one pipeline run."""

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    return execute_scalar(
        connection,
        """
        insert into pipeline_runs (
            run_reference, run_type, trigger_type, status, started_at, finished_at,
            release_version, configuration_hash, is_publication_eligible
        )
        values (:run_reference, 'scoring', 'manual', 'success', :now, :now, 'test', null, true)
        returning id
        """,
        {"run_reference": f"RUN-{suffix}-{label}", "now": now},
    )


def create_site(connection: Connection, code: str, now: datetime) -> object:
    """Insert one site."""

    return execute_scalar(
        connection,
        """
        insert into sites (site_code, site_name, state_code, timezone_name, active_from, active_to)
        values (:code, :code, 'NSW', 'Australia/Sydney', :now, null)
        returning id
        """,
        {"code": code, "now": now},
    )


def create_user(connection: Connection, code: str, display_name: str, now: datetime) -> object:
    """Insert one human user."""

    return execute_scalar(
        connection,
        """
        insert into users (
            user_code, display_name, role_classification, actor_type, active_from, active_to
        )
        values (:code, :display_name, 'operations', 'human', :now, null)
        returning id
        """,
        {"code": code, "display_name": display_name, "now": now},
    )


def create_candidate(
    connection: Connection,
    suffix: str,
    label: str,
    po_line_id: object,
    site_id: object,
    rule_version_id: object,
    *,
    score: int,
    disposition: str,
    linked_episode_id: object | None = None,
) -> object:
    """Insert one candidate risk evaluation."""

    pipeline_run_id = create_pipeline_run(connection, suffix, label)
    return execute_scalar(
        connection,
        """
        insert into candidate_risk_evaluations (
            pipeline_run_id, po_line_id, site_id, rule_version_id, evaluated_at,
            input_fingerprint, eligibility_status, score, calculated_severity,
            score_confidence, disposition, linked_episode_id, explanation_summary,
            missing_signal_payload
        )
        values (
            :pipeline_run_id, :po_line_id, :site_id, :rule_version_id, :now,
            :fingerprint, 'eligible', :score, 'medium', 'normal', :disposition,
            :linked_episode_id, 'schema behaviour test', '{}'
        )
        returning id
        """,
        {
            "pipeline_run_id": pipeline_run_id,
            "po_line_id": po_line_id,
            "site_id": site_id,
            "rule_version_id": rule_version_id,
            "now": datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
            "fingerprint": f"fp-{suffix}-{label}",
            "score": score,
            "disposition": disposition,
            "linked_episode_id": linked_episode_id,
        },
    )


def create_episode(
    connection: Connection,
    context: dict[str, object],
    suffix: str,
    label: str,
    *,
    site_id: object | None = None,
    current_state: str = "open",
    closed_at: datetime | None = None,
    predecessor_episode_id: object | None = None,
) -> object:
    """Insert one exception episode."""

    target_site_id = site_id or context["site_id"]
    candidate_id = create_candidate(
        connection,
        suffix,
        f"candidate-{label}",
        context["po_line_id"],
        target_site_id,
        context["rule_version_id"],
        score=65,
        disposition="opened-new-episode",
    )
    return execute_scalar(
        connection,
        """
        insert into exception_episodes (
            po_line_id, site_id, episode_sequence, opening_candidate_id, opening_run_id,
            predecessor_episode_id, current_state, calculated_severity, effective_severity,
            opened_at, closed_at, current_owner_user_id, current_candidate_id
        )
        values (
            :po_line_id, :site_id, :episode_sequence, :candidate_id, :pipeline_run_id,
            :predecessor_episode_id, :current_state, 'medium', 'medium',
            :opened_at, :closed_at, :owner_id, :candidate_id
        )
        returning id
        """,
        {
            "po_line_id": context["po_line_id"],
            "site_id": target_site_id,
            "episode_sequence": int(uuid.uuid4().int % 1000000) + 1,
            "candidate_id": candidate_id,
            "pipeline_run_id": context["pipeline_run_id"],
            "predecessor_episode_id": predecessor_episode_id,
            "current_state": current_state,
            "opened_at": context["now"],
            "closed_at": closed_at,
            "owner_id": context["requester_user_id"],
        },
    )


def create_approval_request(
    connection: Connection,
    context: dict[str, object],
    episode_id: object,
    suffix: str,
    request_type: str,
) -> object:
    """Insert one approval request."""

    return execute_scalar(
        connection,
        """
        insert into approval_requests (
            episode_id, request_reference, request_type, requester_user_id,
            requested_payload, reason, expires_at
        )
        values (
            :episode_id, :request_reference, :request_type, :requester_user_id,
            '{}', 'schema behaviour test', null
        )
        returning id
        """,
        {
            "episode_id": episode_id,
            "request_reference": f"APR-{suffix}-{uuid.uuid4().hex[:6]}",
            "request_type": request_type,
            "requester_user_id": context["requester_user_id"],
        },
    )


@pytest.mark.integration
def test_migration_upgrade_and_documented_downgrade_behaviour(engine: Engine) -> None:
    """The unreleased initial migration should upgrade and downgrade from an empty database."""

    command.downgrade(Config("alembic.ini"), "base")
    migrate_to_head()
    with engine.connect() as connection:
        assert connection.execute(text("select to_regclass('public.exception_episodes')")).scalar_one()

    command.downgrade(Config("alembic.ini"), "base")
    with engine.connect() as connection:
        assert connection.execute(text("select to_regclass('public.exception_episodes')")).scalar_one() is None

    migrate_to_head()


@pytest.mark.integration
def test_reference_procurement_receipt_and_candidate_behaviour(engine: Engine) -> None:
    """Reference, PO, schedule, receipt, allocation, and contribution inserts should work."""

    migrate_to_head()
    suffix = new_suffix()
    with engine.begin() as connection:
        context = make_reference_context(connection, suffix)
        connection.execute(
            text(
                """
                insert into uom_conversions (
                    product_id, from_uom, to_uom, conversion_factor, effective_from, effective_to
                )
                values (:product_id, 'CASE', 'EA', 12, :now, null)
                """
            ),
            {"product_id": context["product_id"], "now": context["now"]},
        )
        receipt_id = execute_scalar(
            connection,
            """
            insert into receipt_transactions (
                source_system_id, source_load_id, po_line_id, receipt_document,
                receipt_item_sequence, transaction_type, source_quantity, source_uom,
                base_quantity, posted_at, corrects_receipt_id
            )
            values (
                :source_system_id, :source_load_id, :po_line_id, :doc, '1',
                'receipt', 40, 'EA', 40, :now, null
            )
            returning id
            """,
            {
                "source_system_id": context["source_system_id"],
                "source_load_id": context["source_load_id"],
                "po_line_id": context["po_line_id"],
                "doc": f"GR-{suffix}",
                "now": context["now"],
            },
        )
        connection.execute(
            text(
                """
                insert into receipt_allocations (
                    receipt_transaction_id, delivery_schedule_id, allocation_sequence,
                    allocation_bucket, allocated_base_quantity
                )
                values (:receipt_id, :schedule_id, 1, 'schedule', 25)
                """
            ),
            {"receipt_id": receipt_id, "schedule_id": context["schedule_id"]},
        )
        connection.execute(
            text(
                """
                insert into receipt_allocations (
                    receipt_transaction_id, delivery_schedule_id, allocation_sequence,
                    allocation_bucket, allocated_base_quantity
                )
                values (:receipt_id, null, 2, 'line_residual', 15)
                """
            ),
            {"receipt_id": receipt_id},
        )
        reversal_id = execute_scalar(
            connection,
            """
            insert into receipt_transactions (
                source_system_id, source_load_id, po_line_id, receipt_document,
                receipt_item_sequence, transaction_type, source_quantity, source_uom,
                base_quantity, posted_at, corrects_receipt_id
            )
            values (
                :source_system_id, :source_load_id, :po_line_id, :doc, '1',
                'reversal', -40, 'EA', -40, :now, :receipt_id
            )
            returning id
            """,
            {
                "source_system_id": context["source_system_id"],
                "source_load_id": context["source_load_id"],
                "po_line_id": context["po_line_id"],
                "doc": f"GR-REV-{suffix}",
                "now": cast(datetime, context["now"]) + timedelta(minutes=5),
                "receipt_id": receipt_id,
            },
        )
        for idx, points in enumerate((10, 5, 0), start=1):
            connection.execute(
                text(
                    """
                    insert into candidate_risk_contributions (
                        candidate_evaluation_id, rule_component_id, component_code,
                        component_family, availability_status, observed_value, comparator,
                        threshold_value, triggered, gross_points, cap_adjustment,
                        applied_points, missing_signal_reason, explanation_code, input_lineage
                    )
                    values (
                        :candidate_id, :rule_component_id, :component_code, 'supplier',
                        'triggered', 'late', '>', '0', true, :points, 0,
                        :points, null, 'observed', '{}'
                    )
                    """
                ),
                {
                    "candidate_id": context["candidate_id"],
                    "rule_component_id": context["rule_component_id"],
                    "component_code": f"component_{idx}",
                    "points": points,
                },
            )

        counts = connection.execute(
            text(
                """
                select
                    (select count(*) from receipt_allocations where receipt_transaction_id = :receipt_id),
                    (select po_line_id from receipt_transactions where id = :receipt_id),
                    (select corrects_receipt_id from receipt_transactions where id = :reversal_id),
                    (select count(*) from candidate_risk_contributions where candidate_evaluation_id = :candidate_id)
                """
            ),
            {
                "receipt_id": receipt_id,
                "reversal_id": reversal_id,
                "candidate_id": context["candidate_id"],
            },
        ).one()

    assert counts[0] == 2
    assert counts[1] == context["po_line_id"]
    assert counts[2] == receipt_id
    assert counts[3] == 3

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    insert into candidate_risk_contributions (
                        candidate_evaluation_id, rule_component_id, component_code,
                        component_family, availability_status, observed_value, comparator,
                        threshold_value, triggered, gross_points, cap_adjustment,
                        applied_points, missing_signal_reason, explanation_code, input_lineage
                    )
                    values (
                        :candidate_id, :rule_component_id, 'bad_arithmetic', 'supplier',
                        'triggered', 'late', '>', '0', true, 10, -2, 10,
                        null, 'invalid', '{}'
                    )
                    """
                ),
                {
                    "candidate_id": context["candidate_id"],
                    "rule_component_id": context["rule_component_id"],
                },
            )


@pytest.mark.integration
def test_database_rejects_invalid_scores_uom_and_foreign_keys(engine: Engine) -> None:
    """PostgreSQL should reject invalid scores, UOM factors, and missing parents."""

    migrate_to_head()
    suffix = new_suffix()
    with engine.begin() as connection:
        context = make_reference_context(connection, suffix)

    for invalid_score in (-1, 101):
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                create_candidate(
                    connection,
                    suffix,
                    f"bad-score-{invalid_score}",
                    context["po_line_id"],
                    context["site_id"],
                    context["rule_version_id"],
                    score=invalid_score,
                    disposition="opened-new-episode",
                )

    for factor in (0, -1, 1.5):
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        insert into uom_conversions (
                            product_id, from_uom, to_uom, conversion_factor,
                            effective_from, effective_to
                        )
                        values (:product_id, :from_uom, 'EA', :factor, :now, null)
                        """
                    ),
                    {
                        "product_id": context["product_id"],
                        "from_uom": f"BAD-{factor}",
                        "factor": factor,
                        "now": context["now"],
                    },
                )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    insert into purchase_order_lines (purchase_order_id, canonical_line_key)
                    values (:missing_id, :line_key)
                    """
                ),
                {"missing_id": uuid.uuid4(), "line_key": f"MISSING-{suffix}"},
            )


@pytest.mark.integration
def test_episode_uniqueness_state_projection_and_successor_controls(engine: Engine) -> None:
    """Episode projection and material recurrence controls should be enforced by PostgreSQL."""

    migrate_to_head()
    suffix = new_suffix()
    with engine.begin() as connection:
        context = make_reference_context(connection, suffix)
        active_episode_id = create_episode(connection, context, suffix, "active")
        separate_site_episode_id = create_episode(
            connection,
            context,
            suffix,
            "separate-site",
            site_id=context["second_site_id"],
        )

    assert separate_site_episode_id != active_episode_id

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            create_episode(
                connection,
                context,
                suffix,
                "closed-without-closed-at",
                current_state="closed",
                closed_at=None,
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            create_episode(
                connection,
                context,
                suffix,
                "open-with-closed-at",
                current_state="open",
                closed_at=datetime(2026, 7, 23, 9, 0, tzinfo=UTC),
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            create_episode(connection, context, suffix, "duplicate-active")

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            create_episode(
                connection,
                context,
                suffix,
                "active-predecessor",
                predecessor_episode_id=active_episode_id,
            )

    closed_at = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                update exception_episodes
                set current_state = 'closed', closed_at = :closed_at
                where id = :episode_id
                """
            ),
            {"episode_id": active_episode_id, "closed_at": closed_at},
        )
        successor_id = create_episode(
            connection,
            context,
            suffix,
            "closed-successor",
            predecessor_episode_id=active_episode_id,
        )
        connection.execute(
            text(
                """
                insert into episode_relationships (
                    from_episode_id, to_episode_id, relationship_type, relationship_reason
                )
                values (:from_episode_id, :to_episode_id, 'material_recurrence', 'closed predecessor')
                """
            ),
            {"from_episode_id": active_episode_id, "to_episode_id": successor_id},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    update exception_episodes
                    set predecessor_episode_id = id
                    where id = :episode_id
                    """
                ),
                {"episode_id": successor_id},
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    insert into episode_relationships (
                        from_episode_id, to_episode_id, relationship_type, relationship_reason
                    )
                    values (:episode_id, :episode_id, 'material_recurrence', 'self cycle')
                    """
                ),
                {"episode_id": successor_id},
            )


@pytest.mark.integration
def test_repeated_candidates_events_suppression_and_approval_controls(engine: Engine) -> None:
    """Event, suppression, candidate-linking, and material approval controls should hold."""

    migrate_to_head()
    suffix = new_suffix()
    with engine.begin() as connection:
        context = make_reference_context(connection, suffix)
        episode_id = create_episode(connection, context, suffix, "events")
        first_link = create_candidate(
            connection,
            suffix,
            "linked-1",
            context["po_line_id"],
            context["site_id"],
            context["rule_version_id"],
            score=55,
            disposition="linked-existing-active-episode",
            linked_episode_id=episode_id,
        )
        second_link = create_candidate(
            connection,
            suffix,
            "linked-2",
            context["po_line_id"],
            context["site_id"],
            context["rule_version_id"],
            score=58,
            disposition="linked-existing-active-episode",
            linked_episode_id=episode_id,
        )
        event_id = execute_scalar(
            connection,
            """
            insert into exception_event_envelopes (
                episode_id, event_sequence, idempotency_key, event_type, effective_at,
                actor_user_id, actor_type, reason_code, reason_text, correlation_id,
                causation_event_id, pipeline_run_id, rule_version_id, calendar_version_id,
                before_payload, after_payload
            )
            values (
                :episode_id, 1, :idempotency_key, 'state_changed', :now,
                :actor_user_id, 'human', 'opened', 'opened for test', 'corr-1',
                null, :pipeline_run_id, :rule_version_id, null, null, null
            )
            returning id
            """,
            {
                "episode_id": episode_id,
                "idempotency_key": f"event-{suffix}",
                "now": context["now"],
                "actor_user_id": context["requester_user_id"],
                "pipeline_run_id": context["pipeline_run_id"],
                "rule_version_id": context["rule_version_id"],
            },
        )
        connection.execute(
            text(
                """
                insert into exception_state_events (
                    event_envelope_id, from_state, to_state, transition_reason,
                    authority, resolution_id, suppression_control_id
                )
                values (:event_id, null, 'open', 'initial open', 'system', null, null)
                """
            ),
            {"event_id": event_id},
        )
        connection.execute(
            text(
                """
                update exception_episodes
                set current_state = 'investigating'
                where id = :episode_id
                """
            ),
            {"episode_id": episode_id},
        )
        approval_request_id = create_approval_request(
            connection, context, episode_id, suffix, "suppression"
        )
        connection.execute(
            text(
                """
                insert into approval_decisions (
                    approval_request_id, decision_role, approver_user_id, outcome,
                    conditions, independence_check_passed
                )
                values (:request_id, 'manager', :approver_id, 'approved', null, true)
                """
            ),
            {
                "request_id": approval_request_id,
                "approver_id": context["approver_user_id"],
            },
        )
        linked_count = connection.execute(
            text(
                """
                select count(*)
                from candidate_risk_evaluations
                where linked_episode_id = :episode_id
                  and id in (:first_link, :second_link)
                """
            ),
            {"episode_id": episode_id, "first_link": first_link, "second_link": second_link},
        ).scalar_one()
        state_event_count = connection.execute(
            text(
                """
                select count(*)
                from exception_state_events ses
                join exception_event_envelopes eee on eee.id = ses.event_envelope_id
                where eee.episode_id = :episode_id
                """
            ),
            {"episode_id": episode_id},
        ).scalar_one()

    assert linked_count == 2
    assert state_event_count == 1

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    insert into exception_event_envelopes (
                        episode_id, event_sequence, idempotency_key, event_type, effective_at,
                        actor_user_id, actor_type, reason_code, reason_text, correlation_id,
                        causation_event_id, pipeline_run_id, rule_version_id, calendar_version_id,
                        before_payload, after_payload
                    )
                    values (
                        :episode_id, 2, :idempotency_key, 'state_changed', :now,
                        :actor_user_id, 'human', 'duplicate', 'duplicate test', 'corr-2',
                        null, :pipeline_run_id, :rule_version_id, null, null, null
                    )
                    """
                ),
                {
                    "episode_id": episode_id,
                    "idempotency_key": f"event-{suffix}",
                    "now": context["now"],
                    "actor_user_id": context["requester_user_id"],
                    "pipeline_run_id": context["pipeline_run_id"],
                    "rule_version_id": context["rule_version_id"],
                },
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            bad_request_id = create_approval_request(
                connection, context, episode_id, suffix, "suppression"
            )
            connection.execute(
                text(
                    """
                    insert into approval_decisions (
                        approval_request_id, decision_role, approver_user_id, outcome,
                        conditions, independence_check_passed
                    )
                    values (:request_id, 'manager', :requester_id, 'approved', null, false)
                    """
                ),
                {
                    "request_id": bad_request_id,
                    "requester_id": context["requester_user_id"],
                },
            )

    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    """
                    select count(*)
                    from approval_decisions ad
                    join approval_requests ar on ar.id = ad.approval_request_id
                    where ar.episode_id = :episode_id
                      and ad.approver_user_id = ar.requester_user_id
                    """
                ),
                {"episode_id": episode_id},
            ).scalar_one()
            == 0
        )

    starts_at = cast(datetime, context["now"])
    for expires_at in (starts_at, starts_at - timedelta(minutes=1)):
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                request_id = create_approval_request(
                    connection, context, episode_id, suffix, "suppression"
                )
                connection.execute(
                    text(
                        """
                        insert into suppression_controls (
                            episode_id, approval_request_id, prior_state, reason_code,
                            starts_at, expires_at, review_at, recurrence_criteria,
                            sla_consumed_minutes_at_pause
                        )
                        values (
                            :episode_id, :request_id, 'investigating', 'test',
                            :starts_at, :expires_at, null, '{}', null
                        )
                        """
                    ),
                    {
                        "episode_id": episode_id,
                        "request_id": request_id,
                        "starts_at": context["now"],
                        "expires_at": expires_at,
                    },
                )


@pytest.mark.integration
def test_timezone_aware_timestamps_round_trip(engine: Engine) -> None:
    """PostgreSQL timestamptz columns should return timezone-aware values."""

    migrate_to_head()
    suffix = new_suffix()
    aware_time = datetime(2026, 7, 22, 21, 30, tzinfo=UTC)
    with engine.begin() as connection:
        context = make_reference_context(connection, suffix)
        episode_id = create_episode(connection, context, suffix, "timezone")
        connection.execute(
            text(
                """
                update exception_episodes
                set opened_at = :opened_at
                where id = :episode_id
                """
            ),
            {"episode_id": episode_id, "opened_at": aware_time},
        )
        round_tripped = connection.execute(
            text("select opened_at from exception_episodes where id = :episode_id"),
            {"episode_id": episode_id},
        ).scalar_one()

    assert round_tripped.tzinfo is not None
    assert round_tripped.utcoffset() is not None
