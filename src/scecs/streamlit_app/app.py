"""Streamlit operational MVP for governed exception control."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import cast

import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from scecs.database import create_database_engine, create_session_factory, session_scope
from scecs.streamlit_app.actions import (
    ActionAvailability,
    agree_action,
    append_investigation_note,
    append_monitoring_observation,
    approve_closure,
    approve_resolution,
    approve_suppression,
    assign_owner,
    availability_for_state,
    independent_approver_available,
    move_to_investigating,
    move_to_monitoring,
    open_candidate,
    reopen_exception,
    revise_action,
)
from scecs.streamlit_app.queries import OperationalReadService
from scecs.streamlit_app.view_models import (
    CandidateRow,
    ExceptionDetail,
    ExceptionQueueRow,
    UserOption,
    rows_to_records,
)
from scecs.workflow.service import WorkflowError

APP_TITLE = "Supply Chain Exception Control"
SIMULATION_WARNING = "Simulation only - not production authentication."
SessionFactory = sessionmaker[Session]


def main() -> None:
    """Run the Streamlit application."""

    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.info(SIMULATION_WARNING)
    if os.getenv("SCECS_STREAMLIT_STARTUP_SMOKE") == "1":
        st.caption("Startup smoke mode: database reads are intentionally skipped.")
        return

    read_service = _read_service()
    session_factory = _session_factory()
    users = read_service.active_users()
    actor = _actor_selector(users)
    if actor is None:
        st.warning("No active human users are available in PostgreSQL.")
        return

    filters = read_service.filter_options()
    page = st.sidebar.radio(
        "Page",
        ("Control Tower", "Exception Queue", "Exception Detail", "Pipeline Health"),
        label_visibility="collapsed",
    )

    if page == "Control Tower":
        render_control_tower(read_service, session_factory, users, actor, filters)
    elif page == "Exception Queue":
        render_exception_queue(read_service, filters)
    elif page == "Exception Detail":
        render_exception_detail(read_service, session_factory, users, actor)
    else:
        render_pipeline_health(read_service)


def render_control_tower(
    read_service: OperationalReadService,
    session_factory: SessionFactory,
    users: Sequence[UserOption],
    actor: UserOption,
    filters: dict[str, tuple[str, ...]],
) -> None:
    """Render dashboard KPIs and opening-eligible candidate actions."""

    st.header("Control Tower")
    selected_sites = st.sidebar.multiselect("Site", filters["sites"], key="tower_sites")
    selected_suppliers = st.sidebar.multiselect("Supplier", filters["suppliers"], key="tower_suppliers")
    summary = read_service.control_tower_summary(site_codes=selected_sites, supplier_names=selected_suppliers)
    metric_columns = st.columns(5)
    metric_columns[0].metric("Active exceptions", summary.active_exceptions)
    metric_columns[1].metric("Critical and high", summary.critical_high_exceptions)
    metric_columns[2].metric("Unassigned", summary.unassigned_exceptions)
    metric_columns[3].metric("SLA breached", summary.sla_breached_conditions)
    metric_columns[4].metric("Candidates not opened", summary.opening_eligible_candidates)

    chart_columns = st.columns(2)
    with chart_columns[0]:
        st.subheader("State Distribution")
        _table_or_empty(rows_to_records(summary.state_distribution), "No exception states to show.")
    with chart_columns[1]:
        st.subheader("Risk-Band Distribution")
        _table_or_empty(rows_to_records(summary.risk_band_distribution), "No risk bands to show.")

    st.subheader("Highest-Priority Active Exceptions")
    _queue_table(summary.highest_priority)

    st.subheader("Opening-Eligible Candidates")
    candidates = read_service.opening_eligible_candidates(site_codes=selected_sites, supplier_names=selected_suppliers)
    if not candidates:
        st.caption("No opening-eligible candidates are waiting for workflow opening.")
    else:
        _candidate_table(candidates)
        selected_candidate = st.selectbox(
            "Candidate to open",
            candidates,
            format_func=lambda row: f"{row.site_code} | {row.supplier_name} | {row.po_line} | {row.band} {row.score}",
        )
        reason = st.text_input("Opening reason", value="Opened from governed risk candidate.")
        if st.button("Open Exception", type="primary"):
            _run_command(
                lambda: _open_candidate_command(session_factory, selected_candidate, actor, reason),
                "Exception opened from candidate.",
            )

    _pipeline_status(summary.pipeline_status)


def render_exception_queue(read_service: OperationalReadService, filters: dict[str, tuple[str, ...]]) -> None:
    """Render searchable and filterable exception queue."""

    st.header("Exception Queue")
    selected_states = st.sidebar.multiselect("State", filters["states"], key="queue_states")
    selected_bands = st.sidebar.multiselect("Risk band", filters["bands"], key="queue_bands")
    selected_sites = st.sidebar.multiselect("Site", filters["sites"], key="queue_sites")
    selected_suppliers = st.sidebar.multiselect("Supplier", filters["suppliers"], key="queue_suppliers")
    selected_owners = st.sidebar.multiselect("Owner", filters["owners"], key="queue_owners")
    unassigned_only = st.sidebar.checkbox("Unassigned only")
    selected_sla = st.sidebar.multiselect("SLA condition", ("breached", "active", "not_tracked"))
    search = st.text_input("Search by exception, site, supplier, PO line or product")
    rows = read_service.exception_queue(
        states=selected_states,
        risk_bands=selected_bands,
        site_codes=selected_sites,
        supplier_names=selected_suppliers,
        owner_names=selected_owners,
        unassigned_only=unassigned_only,
        sla_statuses=selected_sla,
        search_text=search,
    )
    _queue_table(rows)
    if rows:
        selected = st.selectbox(
            "Open Exception Detail",
            rows,
            format_func=lambda row: f"{row.exception_reference} | {row.state} | {row.site_code} | {row.po_line}",
        )
        if st.button("Open selected detail"):
            st.session_state["selected_episode_id"] = str(selected.episode_id)
            st.success("Selected exception is ready on the Exception Detail page.")


def render_exception_detail(
    read_service: OperationalReadService,
    session_factory: SessionFactory,
    users: Sequence[UserOption],
    actor: UserOption,
) -> None:
    """Render exception detail and governed lifecycle actions."""

    st.header("Exception Detail")
    selected_episode_id = _selected_episode_id(read_service)
    if selected_episode_id is None:
        st.caption("Select an exception from the Exception Queue.")
        return
    detail = read_service.exception_detail(selected_episode_id)
    if detail is None:
        st.warning("The selected exception no longer exists.")
        return

    _render_detail_summary(detail)
    availability = availability_for_state(
        detail.summary.state,
        has_action_agreement=any(action.category == "action_agreement" for action in detail.actions),
    )
    render_governed_actions(read_service, session_factory, users, actor, detail, availability)
    _render_detail_tabs(detail)


def render_pipeline_health(read_service: OperationalReadService) -> None:
    """Render latest pipeline/publication status."""

    st.header("Pipeline Health")
    _pipeline_status(read_service.pipeline_status())


def render_governed_actions(
    read_service: OperationalReadService,
    session_factory: SessionFactory,
    users: Sequence[UserOption],
    actor: UserOption,
    detail: ExceptionDetail,
    availability: ActionAvailability,
) -> None:
    """Render only governed actions available for the current state."""

    st.subheader("Governed Actions")
    st.caption("Candidate Risk is analytical only; it is not a lifecycle state.")
    if detail.summary.state == "closed":
        st.caption("Closed exceptions are read-only in this MVP.")
        return
    if detail.summary.state == "suppressed":
        st.caption("Suppressed exceptions are read-only until a future suppression-review workflow exists.")
        return

    action_tabs = st.tabs(["Assignment", "Investigation", "Action", "Monitoring", "Approval", "Suppression"])
    with action_tabs[0]:
        _render_assignment_action(session_factory, users, actor, detail, availability)
    with action_tabs[1]:
        _render_investigation_actions(session_factory, actor, detail, availability)
    with action_tabs[2]:
        _render_action_agreement_actions(read_service, session_factory, users, actor, detail, availability)
    with action_tabs[3]:
        _render_monitoring_actions(session_factory, actor, detail, availability)
    with action_tabs[4]:
        _render_resolution_closure_actions(session_factory, users, actor, detail, availability)
    with action_tabs[5]:
        _render_suppression_action(session_factory, users, actor, detail, availability)


def _render_assignment_action(
    session_factory: SessionFactory,
    users: Sequence[UserOption],
    actor: UserOption,
    detail: ExceptionDetail,
    availability: ActionAvailability,
) -> None:
    if not availability.can_assign:
        st.caption("Assignment is not available for this state.")
        return
    owner = st.selectbox("Owner", users, format_func=lambda user: user.label)
    reason = st.text_input("Assignment reason", value="Operational ownership assigned.")
    if st.button("Assign / Reassign"):
        _run_command(
            lambda: _assign_command(session_factory, detail.summary.episode_id, actor, owner, reason),
            "Assignment recorded.",
        )


def _render_investigation_actions(
    session_factory: SessionFactory,
    actor: UserOption,
    detail: ExceptionDetail,
    availability: ActionAvailability,
) -> None:
    if availability.can_start_investigation:
        reason = st.text_input("Investigation start reason", value="Investigation started.")
        if st.button("Move to Investigating"):
            _run_command(
                lambda: _investigate_command(session_factory, detail.summary.episode_id, actor, reason),
                "Exception moved to Investigating.",
            )
    if availability.can_add_investigation_note:
        note = st.text_area("Investigation note")
        if st.button("Add Investigation Note", disabled=note.strip() == ""):
            _run_command(
                lambda: _note_command(session_factory, detail.summary.episode_id, actor, note),
                "Investigation note added.",
            )
    if not availability.can_start_investigation and not availability.can_add_investigation_note:
        st.caption("Investigation controls are not available for this state.")


def _render_action_agreement_actions(
    read_service: OperationalReadService,
    session_factory: SessionFactory,
    users: Sequence[UserOption],
    actor: UserOption,
    detail: ExceptionDetail,
    availability: ActionAvailability,
) -> None:
    if availability.can_create_action_agreement:
        action = st.text_area("Action agreement")
        owner = st.selectbox("Action owner", users, format_func=lambda user: user.label, key="action_owner")
        if st.button("Create Action Agreement", disabled=action.strip() == ""):
            _run_command(
                lambda: _agreement_command(session_factory, detail.summary.episode_id, actor, owner, action),
                "Action agreement created.",
            )
    elif availability.can_update_action_agreement:
        action = st.text_area("Updated action agreement")
        previous_action_id = read_service.latest_action_agreement_id(detail.summary.episode_id)
        disabled = action.strip() == "" or previous_action_id is None
        if st.button("Update Action Agreement", disabled=disabled):
            assert previous_action_id is not None
            _run_command(
                lambda: _agreement_update_command(
                    session_factory, detail.summary.episode_id, previous_action_id, actor, action
                ),
                "Action agreement update added.",
            )
    else:
        st.caption("Action agreement controls are not available for this state.")


def _render_monitoring_actions(
    session_factory: SessionFactory,
    actor: UserOption,
    detail: ExceptionDetail,
    availability: ActionAvailability,
) -> None:
    if availability.can_start_monitoring:
        reason = st.text_input("Monitoring start reason", value="Agreed action is ready for monitoring.")
        if st.button("Move to Monitoring"):
            _run_command(
                lambda: _monitoring_command(session_factory, detail.summary.episode_id, actor, reason),
                "Exception moved to Monitoring.",
            )
    if availability.can_add_monitoring_observation:
        observation = st.text_area("Monitoring observation")
        if st.button("Add Monitoring Observation", disabled=observation.strip() == ""):
            _run_command(
                lambda: _observation_command(session_factory, detail.summary.episode_id, actor, observation),
                "Monitoring observation added.",
            )
    if not availability.can_start_monitoring and not availability.can_add_monitoring_observation:
        st.caption("Monitoring controls are not available for this state.")


def _render_resolution_closure_actions(
    session_factory: SessionFactory,
    users: Sequence[UserOption],
    actor: UserOption,
    detail: ExceptionDetail,
    availability: ActionAvailability,
) -> None:
    approver = st.selectbox("Independent approver", users, format_func=lambda user: user.label, key="approval_user")
    independent = independent_approver_available(actor.user_id, approver.user_id)
    if not independent:
        st.warning("Self-approval is blocked before submission.")

    if availability.can_resolve:
        statement = st.text_area("Residual risk statement", value="Residual risk reviewed and accepted.")
        if st.button("Approve Resolution", disabled=not independent or statement.strip() == ""):
            _run_command(
                lambda: _resolution_command(session_factory, detail.summary.episode_id, actor, approver, statement),
                "Resolution approved and recorded.",
            )
    if availability.can_close:
        reason = st.text_input("Closure reason", value="Closure independently approved.")
        if st.button("Approve Closure", disabled=not independent or reason.strip() == ""):
            _run_command(
                lambda: _closure_command(session_factory, detail.summary.episode_id, actor, approver, reason),
                "Closure approved and recorded.",
            )
    if availability.can_reopen:
        reason = st.text_input("Reopen reason", value="Material condition changed; investigation reopened.")
        if st.button("Reopen to Investigating", disabled=reason.strip() == ""):
            _run_command(
                lambda: _reopen_command(session_factory, detail.summary.episode_id, actor, reason),
                "Reopened event recorded.",
            )
    if not availability.can_resolve and not availability.can_close and not availability.can_reopen:
        st.caption("Resolution, closure, and reopening controls are not available for this state.")


def _render_suppression_action(
    session_factory: SessionFactory,
    users: Sequence[UserOption],
    actor: UserOption,
    detail: ExceptionDetail,
    availability: ActionAvailability,
) -> None:
    if not availability.can_suppress:
        st.caption("Suppression is not available for this state.")
        return
    approver = st.selectbox("Suppression approver", users, format_func=lambda user: user.label, key="suppression_user")
    reason_code = st.text_input("Suppression reason code", value="controlled_duplicate")
    reason_text = st.text_area("Suppression reason")
    evidence = st.text_input("Evidence reference")
    expiry_date = cast(
        date,
        st.date_input("Suppression expiry date", value=datetime.now(UTC).date() + timedelta(days=7)),
    )
    independent = independent_approver_available(actor.user_id, approver.user_id)
    future_expiry = datetime.combine(expiry_date, time(23, 59), tzinfo=UTC) > datetime.now(UTC)
    disabled = (
        not independent
        or not future_expiry
        or not reason_code.strip()
        or not reason_text.strip()
        or not evidence.strip()
    )
    if not independent:
        st.warning("Self-approval is blocked before submission.")
    if not future_expiry:
        st.warning("Suppression expiry must be in the future.")
    if st.button("Approve Suppression", disabled=disabled):
        expires_at = datetime.combine(expiry_date, time(23, 59), tzinfo=UTC)
        _run_command(
            lambda: _suppression_command(
                session_factory,
                detail.summary.episode_id,
                actor,
                approver,
                reason_code,
                reason_text,
                evidence,
                expires_at,
            ),
            "Suppression approved and recorded.",
        )


def _render_detail_summary(detail: ExceptionDetail) -> None:
    row = detail.summary
    metric_columns = st.columns(5)
    metric_columns[0].metric("State", row.state)
    metric_columns[1].metric("Owner", row.owner or "Unassigned")
    metric_columns[2].metric("Score", str(row.score or "n/a"))
    metric_columns[3].metric("Band", row.band or "n/a")
    metric_columns[4].metric("SLA", row.sla_status)
    st.write(
        {
            "exception_reference": row.exception_reference,
            "site": row.site_code,
            "supplier": row.supplier_name,
            "po_line": row.po_line,
            "product": row.product,
            "residual_quantity": row.residual_quantity,
            "residual_value": row.residual_value,
            "need_date": row.need_date,
            "age_days": row.age_days,
        }
    )


def _render_detail_tabs(detail: ExceptionDetail) -> None:
    tabs = st.tabs(
        [
            "Risk Breakdown",
            "Missing Signals",
            "Assignment History",
            "Notes and Actions",
            "Approvals",
            "Suppression",
            "Audit History",
        ]
    )
    with tabs[0]:
        _table_or_empty(rows_to_records(detail.risk_contributions), "No risk contributions found.")
    with tabs[1]:
        st.json(detail.missing_signals or {"message": "No missing signals recorded."})
    with tabs[2]:
        _table_or_empty(rows_to_records(detail.ownership_history), "No assignment history found.")
    with tabs[3]:
        _table_or_empty(
            rows_to_records(detail.actions),
            "No investigation notes, action agreements, or observations yet.",
        )
    with tabs[4]:
        _table_or_empty(rows_to_records(detail.approvals), "No approvals recorded.")
    with tabs[5]:
        _table_or_empty(rows_to_records(detail.suppressions), "No suppression controls recorded.")
    with tabs[6]:
        st.caption("Historical events are immutable and read-only.")
        _table_or_empty(rows_to_records(detail.audit_events), "No audit events recorded.")


def _actor_selector(users: Sequence[UserOption]) -> UserOption | None:
    if not users:
        return None
    selected = st.sidebar.selectbox(
        "Simulated actor",
        users,
        format_func=lambda user: user.label,
        help=SIMULATION_WARNING,
    )
    st.sidebar.warning(SIMULATION_WARNING)
    return selected


def _selected_episode_id(read_service: OperationalReadService) -> uuid.UUID | None:
    queue_rows = read_service.exception_queue()
    if not queue_rows:
        return None
    current = st.session_state.get("selected_episode_id")
    current_id = uuid.UUID(str(current)) if current else queue_rows[0].episode_id
    selected = st.selectbox(
        "Selected exception",
        queue_rows,
        index=_index_for_episode(queue_rows, current_id),
        format_func=lambda row: f"{row.exception_reference} | {row.state} | {row.site_code} | {row.po_line}",
    )
    st.session_state["selected_episode_id"] = str(selected.episode_id)
    return selected.episode_id


def _index_for_episode(rows: Sequence[ExceptionQueueRow], episode_id: uuid.UUID) -> int:
    for index, row in enumerate(rows):
        if row.episode_id == episode_id:
            return index
    return 0


def _queue_table(rows: Sequence[ExceptionQueueRow]) -> None:
    records: list[dict[str, object]] = [
        {
            "exception reference": row.exception_reference,
            "site": row.site_code,
            "supplier": row.supplier_name,
            "PO line": row.po_line,
            "product": row.product,
            "state": row.state,
            "owner": row.owner or "Unassigned",
            "score": row.score,
            "band": row.band,
            "residual exposure": row.residual_value,
            "need date": row.need_date,
            "age": row.age_days,
            "SLA status": row.sla_status,
        }
        for row in rows
    ]
    _table_or_empty(records, "No exceptions match the current filters.")


def _candidate_table(rows: Sequence[CandidateRow]) -> None:
    records = [
        {
            "site": row.site_code,
            "supplier": row.supplier_name,
            "PO line": row.po_line,
            "product": row.product,
            "score": row.score,
            "band": row.band,
            "residual exposure": row.residual_value,
            "need date": row.need_date,
        }
        for row in rows
    ]
    _table_or_empty(records, "No candidates match the current filters.")


def _table_or_empty(records: Sequence[dict[str, object]], empty_message: str) -> None:
    if not records:
        st.caption(empty_message)
        return
    st.dataframe(records, use_container_width=True, hide_index=True)


def _pipeline_status(status: object) -> None:
    st.subheader("Latest Successful Publication and Pipeline Status")
    st.write(status)


def _run_command(command: Callable[[], object], success_message: str) -> None:
    try:
        command()
    except WorkflowError as exc:
        st.error(str(exc))
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.success(success_message)
        st.rerun()


def _open_candidate_command(
    session_factory: SessionFactory, candidate: CandidateRow, actor: UserOption, reason: str
) -> None:
    with session_scope(session_factory) as session:
        open_candidate(session, candidate.candidate_id, actor_user_id=actor.user_id, reason_text=reason)


def _assign_command(
    session_factory: SessionFactory, episode_id: uuid.UUID, actor: UserOption, owner: UserOption, reason: str
) -> None:
    with session_scope(session_factory) as session:
        assign_owner(session, episode_id, owner.user_id, actor_user_id=actor.user_id, reason_text=reason)


def _investigate_command(
    session_factory: SessionFactory, episode_id: uuid.UUID, actor: UserOption, reason: str
) -> None:
    with session_scope(session_factory) as session:
        move_to_investigating(session, episode_id, actor_user_id=actor.user_id, reason_text=reason)


def _note_command(session_factory: SessionFactory, episode_id: uuid.UUID, actor: UserOption, note: str) -> None:
    with session_scope(session_factory) as session:
        append_investigation_note(session, episode_id, note, actor_user_id=actor.user_id)


def _agreement_command(
    session_factory: SessionFactory, episode_id: uuid.UUID, actor: UserOption, owner: UserOption, action: str
) -> None:
    with session_scope(session_factory) as session:
        agree_action(
            session,
            episode_id,
            {"action": action},
            actor_user_id=actor.user_id,
            action_owner_user_id=owner.user_id,
        )


def _agreement_update_command(
    session_factory: SessionFactory,
    episode_id: uuid.UUID,
    previous_action_id: uuid.UUID,
    actor: UserOption,
    action: str,
) -> None:
    with session_scope(session_factory) as session:
        revise_action(session, episode_id, previous_action_id, {"action": action}, actor_user_id=actor.user_id)


def _monitoring_command(session_factory: SessionFactory, episode_id: uuid.UUID, actor: UserOption, reason: str) -> None:
    with session_scope(session_factory) as session:
        move_to_monitoring(session, episode_id, actor_user_id=actor.user_id, reason_text=reason)


def _observation_command(
    session_factory: SessionFactory, episode_id: uuid.UUID, actor: UserOption, observation: str
) -> None:
    with session_scope(session_factory) as session:
        append_monitoring_observation(session, episode_id, {"observation": observation}, actor_user_id=actor.user_id)


def _resolution_command(
    session_factory: SessionFactory,
    episode_id: uuid.UUID,
    actor: UserOption,
    approver: UserOption,
    statement: str,
) -> None:
    with session_scope(session_factory) as session:
        approve_resolution(
            session,
            episode_id,
            actor_user_id=actor.user_id,
            approver_user_id=approver.user_id,
            residual_risk_statement=statement,
        )


def _closure_command(
    session_factory: SessionFactory, episode_id: uuid.UUID, actor: UserOption, approver: UserOption, reason: str
) -> None:
    with session_scope(session_factory) as session:
        approve_closure(
            session,
            episode_id,
            actor_user_id=actor.user_id,
            approver_user_id=approver.user_id,
            reason_text=reason,
        )


def _reopen_command(session_factory: SessionFactory, episode_id: uuid.UUID, actor: UserOption, reason: str) -> None:
    with session_scope(session_factory) as session:
        reopen_exception(session, episode_id, actor_user_id=actor.user_id, reason_text=reason)


def _suppression_command(
    session_factory: SessionFactory,
    episode_id: uuid.UUID,
    actor: UserOption,
    approver: UserOption,
    reason_code: str,
    reason_text: str,
    evidence: str,
    expires_at: datetime,
) -> None:
    with session_scope(session_factory) as session:
        approve_suppression(
            session,
            episode_id,
            actor_user_id=actor.user_id,
            approver_user_id=approver.user_id,
            reason_code=reason_code,
            reason_text=reason_text,
            evidence_reference=evidence,
            expires_at=expires_at,
        )


@st.cache_resource
def _read_service() -> OperationalReadService:
    return OperationalReadService(create_database_engine())


@st.cache_resource
def _session_factory() -> SessionFactory:
    return create_session_factory(create_database_engine())


if __name__ == "__main__":
    main()
