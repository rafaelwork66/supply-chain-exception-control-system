"""Unit tests for the Streamlit operational MVP helpers."""

from __future__ import annotations

import importlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from scecs.streamlit_app.actions import (
    availability_for_state,
    candidate_open_available,
    independent_approver_available,
)
from scecs.streamlit_app.queries import _matches_candidate_filters, _matches_exception_filters
from scecs.streamlit_app.view_models import CandidateRow, ExceptionQueueRow


def test_action_availability_follows_lifecycle_state() -> None:
    """Invalid lifecycle controls should not be available in the UI model."""

    assert availability_for_state("open").can_assign
    assert availability_for_state("open").can_start_monitoring is False
    assert availability_for_state("assigned").can_start_investigation
    assert availability_for_state("investigating").can_create_action_agreement
    assert availability_for_state("action_agreed", has_action_agreement=True).can_start_monitoring
    assert availability_for_state("monitoring").can_resolve
    assert availability_for_state("resolved").can_close
    assert availability_for_state("resolved").can_reopen
    assert availability_for_state("closed").can_assign is False
    assert availability_for_state("suppressed").can_suppress is False


def test_candidate_opening_is_limited_to_opening_eligible_unlinked_candidates() -> None:
    """Candidate Risk should remain analytical until the governed opening command is available."""

    assert candidate_open_available("opening-eligible-no-workflow", None)
    assert not candidate_open_available("opened-new-episode", None)
    assert not candidate_open_available("opening-eligible-no-workflow", uuid.uuid4())


def test_material_actions_require_actor_approver_separation() -> None:
    """Resolution, closure, and suppression controls should block self-approval before submission."""

    actor = uuid.uuid4()
    assert not independent_approver_available(actor, None)
    assert not independent_approver_available(actor, actor)
    assert independent_approver_available(actor, uuid.uuid4())


def test_exception_filter_helper_covers_queue_filters() -> None:
    """Queue filters should apply state, risk, site, supplier, owner, SLA and search logic."""

    row = ExceptionQueueRow(
        episode_id=uuid.uuid4(),
        exception_reference="EX-1-abcdef",
        site_code="MEL",
        supplier_name="Synthetic Supplier",
        po_line="PO-1-10",
        product="Critical Pump",
        state="monitoring",
        owner="Synthetic Buyer 01",
        owner_user_id=uuid.uuid4(),
        score=Decimal("88.25"),
        band="critical",
        residual_quantity=Decimal("4"),
        residual_value=Decimal("9000"),
        need_date=date(2026, 7, 30),
        opened_at=datetime(2026, 7, 24, tzinfo=UTC),
        age_days=1,
        sla_status="breached",
    )

    assert _matches_exception_filters(
        row,
        states=("monitoring",),
        risk_bands=("critical",),
        site_codes=("MEL",),
        supplier_names=("Synthetic Supplier",),
        owner_names=("Synthetic Buyer 01",),
        unassigned_only=False,
        sla_statuses=("breached",),
        search_text="pump",
    )
    assert not _matches_exception_filters(
        row,
        states=("open",),
        risk_bands=(),
        site_codes=(),
        supplier_names=(),
        owner_names=(),
        unassigned_only=False,
        sla_statuses=(),
        search_text="",
    )
    assert not _matches_exception_filters(
        row,
        states=(),
        risk_bands=(),
        site_codes=(),
        supplier_names=(),
        owner_names=(),
        unassigned_only=True,
        sla_statuses=(),
        search_text="",
    )


def test_candidate_filter_helper_covers_opening_candidate_filters() -> None:
    """Opening-eligible candidates should support site, supplier and search filters."""

    candidate = CandidateRow(
        candidate_id=uuid.uuid4(),
        site_code="PER",
        supplier_name="West Supplier",
        po_line="PO-2-20",
        product="Control Valve",
        score=Decimal("76.00"),
        band="high",
        residual_quantity=Decimal("2"),
        residual_value=Decimal("1200"),
        need_date=date(2026, 8, 1),
    )

    assert _matches_candidate_filters(
        candidate,
        site_codes=("PER",),
        supplier_names=("West Supplier",),
        search_text="valve",
    )
    assert not _matches_candidate_filters(
        candidate,
        site_codes=("MEL",),
        supplier_names=(),
        search_text="",
    )


def test_streamlit_app_import_smoke() -> None:
    """The Streamlit app module should import without starting the application."""

    module = importlib.import_module("scecs.streamlit_app.app")

    assert module.APP_TITLE == "Supply Chain Exception Control"
