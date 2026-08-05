"""add Power BI reporting schema and views

Revision ID: 20260805_0005
Revises: 20260724_0004
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260805_0005"
down_revision: str | None = "20260724_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPORTING_OBJECTS = (
    "rpt_pipeline_runs",
    "rpt_suppressions",
    "rpt_approvals",
    "rpt_risk_components",
    "rpt_risk_assessments",
    "rpt_exception_events",
    "rpt_exception_summary",
    "dim_rule_component",
    "dim_severity",
    "dim_exception_state",
    "dim_user",
    "dim_product",
    "dim_supplier",
    "dim_site",
    "dim_exception",
    "dim_date",
)


def upgrade() -> None:
    """Create governed read-only reporting views for Power BI."""

    op.execute("create schema if not exists reporting;")
    op.execute(DIM_DATE_VIEW)
    op.execute(DIM_EXCEPTION_VIEW)
    op.execute(DIM_SITE_VIEW)
    op.execute(DIM_SUPPLIER_VIEW)
    op.execute(DIM_PRODUCT_VIEW)
    op.execute(DIM_USER_VIEW)
    op.execute(DIM_EXCEPTION_STATE_VIEW)
    op.execute(DIM_SEVERITY_VIEW)
    op.execute(DIM_RULE_COMPONENT_VIEW)
    op.execute(RPT_EXCEPTION_SUMMARY_VIEW)
    op.execute(RPT_EXCEPTION_EVENTS_VIEW)
    op.execute(RPT_RISK_ASSESSMENTS_VIEW)
    op.execute(RPT_RISK_COMPONENTS_VIEW)
    op.execute(RPT_APPROVALS_VIEW)
    op.execute(RPT_SUPPRESSIONS_VIEW)
    op.execute(RPT_PIPELINE_RUNS_VIEW)
    op.execute(
        """
        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'powerbi_reporting_reader') then
                grant usage on schema reporting to powerbi_reporting_reader;
                grant select on all tables in schema reporting to powerbi_reporting_reader;
            end if;
        end;
        $$;
        """
    )


def downgrade() -> None:
    """Drop reporting views and the reporting schema."""

    op.execute(
        """
        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'powerbi_reporting_reader') then
                revoke all privileges on all tables in schema reporting from powerbi_reporting_reader;
                revoke all privileges on schema reporting from powerbi_reporting_reader;
            end if;
        end;
        $$;
        """
    )
    for object_name in REPORTING_OBJECTS:
        op.execute(f"drop view if exists reporting.{object_name} cascade;")
    op.execute("drop schema if exists reporting;")


DIM_DATE_VIEW = """
create or replace view reporting.dim_date as
with source_dates as (
    select opened_at::date as date_value from exception_episodes
    union all select closed_at::date from exception_episodes where closed_at is not null
    union all select evaluated_at::date from candidate_risk_evaluations
    union all select started_at::date from pipeline_runs
    union all select finished_at::date from pipeline_runs where finished_at is not null
    union all select starts_at::date from suppression_controls
    union all select expires_at::date from suppression_controls
    union all select original_due_at::date from sla_obligations
    union all select order_date from purchase_order_versions
    union all select need_date from purchase_order_line_versions
),
bounds as (
    select
        coalesce(min(date_value), current_date) as min_date,
        coalesce(max(date_value), current_date) as max_date
    from source_dates
)
select
    to_char(day_value::date, 'YYYYMMDD')::integer as date_key,
    day_value::date as date,
    extract(year from day_value)::integer as year,
    extract(quarter from day_value)::integer as quarter,
    extract(month from day_value)::integer as month,
    to_char(day_value, 'Mon') as month_name,
    date_trunc('week', day_value)::date as week_start_date,
    extract(isodow from day_value)::integer as day_of_week
from bounds
cross join generate_series(
    bounds.min_date - 30,
    bounds.max_date + 365,
    interval '1 day'
) as generated(day_value);
"""

DIM_EXCEPTION_VIEW = """
create or replace view reporting.dim_exception as
select
    e.id as episode_id,
    ('EX-' || e.episode_sequence::text || '-' || left(e.id::text, 8)) as exception_reference,
    e.po_line_id,
    e.site_id,
    e.opened_at,
    e.closed_at,
    e.current_state
from exception_episodes e;
"""

DIM_SITE_VIEW = """
create or replace view reporting.dim_site as
select
    s.id as site_id,
    s.site_code,
    s.site_name,
    s.state_code,
    s.timezone_name,
    s.active_from,
    s.active_to,
    (s.active_from <= current_timestamp and (s.active_to is null or s.active_to > current_timestamp)) as is_active_now
from sites s;
"""

DIM_SUPPLIER_VIEW = """
create or replace view reporting.dim_supplier as
select
    s.id as supplier_id,
    s.supplier_code,
    sv.display_name,
    sv.supplier_category,
    sv.effective_from,
    sv.effective_to
from suppliers s
left join lateral (
    select
        supplier_versions.display_name,
        supplier_versions.supplier_category,
        supplier_versions.effective_from,
        supplier_versions.effective_to
    from supplier_versions
    where supplier_versions.supplier_id = s.id
    order by (supplier_versions.effective_to is null) desc, supplier_versions.effective_from desc
    limit 1
) sv on true;
"""

DIM_PRODUCT_VIEW = """
create or replace view reporting.dim_product as
select
    p.id as product_id,
    p.sku,
    pv.description,
    pv.category,
    pv.base_uom,
    pv.handling_precision,
    pv.effective_from,
    pv.effective_to
from products p
left join lateral (
    select
        product_versions.description,
        product_versions.category,
        product_versions.base_uom,
        product_versions.handling_precision,
        product_versions.effective_from,
        product_versions.effective_to
    from product_versions
    where product_versions.product_id = p.id
    order by (product_versions.effective_to is null) desc, product_versions.effective_from desc
    limit 1
) pv on true;
"""

DIM_USER_VIEW = """
create or replace view reporting.dim_user as
select
    u.id as user_id,
    u.user_code,
    u.display_name,
    u.role_classification,
    u.actor_type,
    u.active_from,
    u.active_to,
    (u.active_from <= current_timestamp and (u.active_to is null or u.active_to > current_timestamp)) as is_active_now
from users u;
"""

DIM_EXCEPTION_STATE_VIEW = """
create or replace view reporting.dim_exception_state as
select *
from (
    values
        ('open', 'Open', 10, false, false, true),
        ('assigned', 'Assigned', 20, false, false, true),
        ('investigating', 'Investigating', 30, false, false, true),
        ('action_agreed', 'Action Agreed', 40, false, false, true),
        ('monitoring', 'Monitoring', 50, false, false, true),
        ('resolved', 'Resolved', 60, false, false, true),
        ('suppressed', 'Suppressed', 70, false, true, false),
        ('closed', 'Closed', 80, true, false, false)
) as states(
    state_code,
    state_label,
    state_sort_order,
    is_closed_state,
    is_suppressed_state,
    is_active_operational_state
);
"""

DIM_SEVERITY_VIEW = """
create or replace view reporting.dim_severity as
select *
from (
    values
        ('monitor', 'Monitor', 10),
        ('low', 'Low', 20),
        ('medium', 'Medium', 30),
        ('high', 'High', 40),
        ('critical', 'Critical', 50)
) as severities(severity_code, severity_label, severity_sort_order);
"""

DIM_RULE_COMPONENT_VIEW = """
create or replace view reporting.dim_rule_component as
select
    rcd.id as rule_component_id,
    rcd.rule_version_id,
    rv.rule_code,
    rv.version as rule_version,
    rcd.component_code,
    rcd.component_family,
    rcd.max_points
from rule_component_definitions rcd
join rule_versions rv on rv.id = rcd.rule_version_id;
"""

RPT_EXCEPTION_SUMMARY_VIEW = """
create or replace view reporting.rpt_exception_summary as
with latest_line as (
    select distinct on (polv.po_line_id)
        polv.po_line_id,
        polv.product_id,
        polv.site_id as line_site_id,
        polv.amendment_version as line_amendment_version,
        polv.ordered_quantity,
        polv.order_uom,
        polv.base_quantity,
        polv.unit_price_aud,
        polv.line_value_aud,
        polv.need_date,
        polv.requested_date,
        polv.line_status,
        polv.effective_at as line_effective_at
    from purchase_order_line_versions polv
    order by polv.po_line_id, polv.amendment_version desc, polv.effective_at desc, polv.id
),
latest_order as (
    select distinct on (pov.purchase_order_id)
        pov.purchase_order_id,
        pov.supplier_id,
        pov.amendment_version as order_amendment_version,
        pov.buyer_group,
        pov.currency_code,
        pov.order_date,
        pov.order_status,
        pov.effective_at as order_effective_at
    from purchase_order_versions pov
    order by pov.purchase_order_id, pov.amendment_version desc, pov.effective_at desc, pov.id
),
current_alias as (
    select distinct on (pola.po_line_id)
        pola.po_line_id,
        pola.source_po_number,
        pola.source_line_number
    from purchase_order_line_aliases pola
    order by pola.po_line_id, (pola.valid_to is null) desc, pola.valid_from desc, pola.id
),
receipts as (
    select
        rt.po_line_id,
        coalesce(sum(ra.allocated_base_quantity), 0)::numeric(18, 4) as received_base_quantity
    from receipt_transactions rt
    join receipt_allocations ra on ra.receipt_transaction_id = rt.id
    group by rt.po_line_id
),
state_rollup as (
    select
        eee.episode_id,
        min(eee.effective_at) filter (where ese.to_state = 'resolved') as first_resolved_at,
        count(*) filter (where ese.to_state = 'resolved')::integer as resolved_transition_count,
        count(*) filter (
            where eee.event_type = 'reopened' or ese.transition_reason = 'reopened'
        )::integer as reopen_count
    from exception_event_envelopes eee
    left join exception_state_events ese on ese.event_envelope_id = eee.id
    group by eee.episode_id
),
approval_rollup as (
    select
        ar.episode_id,
        count(distinct ar.id)::integer as approval_request_count
    from approval_requests ar
    group by ar.episode_id
),
suppression_rollup as (
    select
        sc.episode_id,
        count(*)::integer as suppression_count,
        max(sc.expires_at) as latest_suppression_expires_at
    from suppression_controls sc
    group by sc.episode_id
),
sla_rollup as (
    select
        so.episode_id,
        count(*)::integer as sla_obligation_count,
        count(*) filter (where so.satisfied_at is null and so.cancelled_at is null)::integer
            as unsatisfied_sla_obligation_count,
        min(so.original_due_at) filter (where so.satisfied_at is null and so.cancelled_at is null)
            as earliest_unsatisfied_sla_due_at
    from sla_obligations so
    group by so.episode_id
),
quantities as (
    select
        ll.*,
        coalesce(ll.base_quantity, ll.ordered_quantity) as latest_quantity,
        case
            when ll.base_quantity is not null then 'base_quantity'
            else 'ordered_quantity_fallback'
        end as quantity_basis
    from latest_line ll
)
select
    e.id as episode_id,
    e.po_line_id,
    pol.purchase_order_id,
    po.po_number,
    ca.source_po_number,
    ca.source_line_number,
    e.site_id,
    lo.supplier_id,
    q.product_id,
    e.episode_sequence,
    e.current_state,
    (e.closed_at is null) as is_not_closed,
    (e.current_state in ('open', 'assigned', 'investigating', 'action_agreed', 'monitoring', 'resolved'))
        as is_active_operational,
    (e.current_state = 'suppressed') as is_suppressed,
    (e.current_state = 'closed' and e.closed_at is not null) as is_closed,
    e.calculated_severity,
    e.effective_severity,
    e.opened_at,
    e.closed_at,
    e.current_owner_user_id,
    e.opening_candidate_id,
    e.current_candidate_id,
    e.opening_run_id,
    c.score as current_score,
    c.score_confidence as current_score_confidence,
    c.disposition as current_candidate_disposition,
    q.ordered_quantity,
    q.base_quantity,
    q.quantity_basis,
    coalesce(r.received_base_quantity, 0)::numeric(18, 4) as received_base_quantity,
    case
        when q.latest_quantity is null then null
        else greatest(q.latest_quantity - coalesce(r.received_base_quantity, 0), 0)::numeric(18, 4)
    end as residual_base_quantity,
    q.unit_price_aud,
    q.line_value_aud,
    lo.currency_code,
    case
        when q.latest_quantity is null then null
        when q.line_value_aud is not null and q.latest_quantity > 0
            then (
                q.line_value_aud
                * greatest(q.latest_quantity - coalesce(r.received_base_quantity, 0), 0)
                / q.latest_quantity
            )::numeric(18, 2)
        when q.unit_price_aud is not null
            then (
                q.unit_price_aud
                * greatest(q.latest_quantity - coalesce(r.received_base_quantity, 0), 0)
            )::numeric(18, 2)
        else null
    end as residual_value_aud,
    (
        case
            when q.latest_quantity is null then null
            when q.line_value_aud is not null and q.latest_quantity > 0
                then (
                    q.line_value_aud
                    * greatest(q.latest_quantity - coalesce(r.received_base_quantity, 0), 0)
                    / q.latest_quantity
                )
            when q.unit_price_aud is not null
                then q.unit_price_aud * greatest(q.latest_quantity - coalesce(r.received_base_quantity, 0), 0)
            else null
        end
    ) is not null as exposure_value_available,
    q.need_date,
    q.requested_date,
    lo.order_date,
    q.line_status,
    lo.order_status,
    sr.first_resolved_at,
    e.closed_at as first_closed_at,
    coalesce(sr.resolved_transition_count, 0) as resolved_transition_count,
    coalesce(sr.reopen_count, 0) as reopen_count,
    (coalesce(sr.reopen_count, 0) > 0) as has_reopened,
    coalesce(ar.approval_request_count, 0) as approval_request_count,
    coalesce(spr.suppression_count, 0) as suppression_count,
    case when e.current_state = 'suppressed' then spr.latest_suppression_expires_at else null end
        as active_suppression_expires_at,
    coalesce(sla.sla_obligation_count, 0) as sla_obligation_count,
    (coalesce(sla.sla_obligation_count, 0) > 0) as has_sla_coverage,
    coalesce(sla.unsatisfied_sla_obligation_count, 0) as unsatisfied_sla_obligation_count,
    sla.earliest_unsatisfied_sla_due_at
from exception_episodes e
join purchase_order_lines pol on pol.id = e.po_line_id
join purchase_orders po on po.id = pol.purchase_order_id
left join latest_order lo on lo.purchase_order_id = pol.purchase_order_id
left join quantities q on q.po_line_id = e.po_line_id
left join current_alias ca on ca.po_line_id = e.po_line_id
left join receipts r on r.po_line_id = e.po_line_id
left join candidate_risk_evaluations c on c.id = e.current_candidate_id
left join state_rollup sr on sr.episode_id = e.id
left join approval_rollup ar on ar.episode_id = e.id
left join suppression_rollup spr on spr.episode_id = e.id
left join sla_rollup sla on sla.episode_id = e.id;
"""

RPT_EXCEPTION_EVENTS_VIEW = """
create or replace view reporting.rpt_exception_events as
select
    eee.id as event_id,
    eee.episode_id,
    eee.event_sequence,
    eee.event_type,
    eee.effective_at,
    eee.recorded_at,
    eee.actor_user_id,
    eee.actor_type,
    ese.from_state,
    ese.to_state,
    ese.transition_reason,
    ese.authority,
    (eee.event_type = 'reopened' or ese.transition_reason = 'reopened') as is_reopen_event,
    eee.reason_code,
    eee.reason_text,
    eee.pipeline_run_id,
    eee.rule_version_id,
    eee.calendar_version_id,
    eee.correlation_id,
    eee.causation_event_id,
    (eee.before_payload is not null) as has_before_payload,
    (eee.after_payload is not null) as has_after_payload
from exception_event_envelopes eee
left join exception_state_events ese on ese.event_envelope_id = eee.id;
"""

RPT_RISK_ASSESSMENTS_VIEW = """
create or replace view reporting.rpt_risk_assessments as
with latest_line as (
    select distinct on (polv.po_line_id)
        polv.po_line_id,
        polv.product_id
    from purchase_order_line_versions polv
    order by polv.po_line_id, polv.amendment_version desc, polv.effective_at desc, polv.id
),
latest_order as (
    select distinct on (pov.purchase_order_id)
        pov.purchase_order_id,
        pov.supplier_id
    from purchase_order_versions pov
    order by pov.purchase_order_id, pov.amendment_version desc, pov.effective_at desc, pov.id
),
component_missing as (
    select
        crc.candidate_evaluation_id,
        count(*) filter (where crc.availability_status in ('unavailable', 'invalid')) > 0 as has_missing_component
    from candidate_risk_contributions crc
    group by crc.candidate_evaluation_id
)
select
    c.id as candidate_evaluation_id,
    c.pipeline_run_id,
    pr.run_reference,
    c.evaluated_at,
    c.po_line_id,
    pol.purchase_order_id,
    po.po_number,
    c.site_id,
    lo.supplier_id,
    ll.product_id,
    c.rule_version_id,
    rv.rule_code,
    rv.version as rule_version,
    c.eligibility_status,
    c.score,
    c.calculated_severity,
    c.score_confidence,
    c.disposition,
    c.linked_episode_id,
    (
        c.linked_episode_id is not null
        or c.disposition in ('opened-new-episode', 'linked-existing-active-episode')
    ) as candidate_opened_or_linked_episode,
    (c.disposition = 'opening-eligible-no-workflow' and c.linked_episode_id is null)
        as is_candidate_not_opened,
    coalesce(cm.has_missing_component, false) as has_missing_signals,
    c.explanation_summary,
    c.missing_signal_payload,
    c.input_fingerprint
from candidate_risk_evaluations c
join pipeline_runs pr on pr.id = c.pipeline_run_id
join purchase_order_lines pol on pol.id = c.po_line_id
join purchase_orders po on po.id = pol.purchase_order_id
left join latest_line ll on ll.po_line_id = c.po_line_id
left join latest_order lo on lo.purchase_order_id = pol.purchase_order_id
join rule_versions rv on rv.id = c.rule_version_id
left join component_missing cm on cm.candidate_evaluation_id = c.id;
"""

RPT_RISK_COMPONENTS_VIEW = """
create or replace view reporting.rpt_risk_components as
select
    crc.id as risk_component_contribution_id,
    crc.candidate_evaluation_id,
    c.pipeline_run_id,
    c.evaluated_at,
    crc.rule_component_id,
    crc.component_code,
    crc.component_family,
    crc.availability_status,
    crc.triggered,
    crc.observed_value,
    crc.comparator,
    crc.threshold_value,
    crc.gross_points,
    crc.cap_adjustment,
    crc.applied_points,
    crc.missing_signal_reason,
    (crc.availability_status in ('unavailable', 'invalid')) as is_missing_signal,
    crc.explanation_code
from candidate_risk_contributions crc
join candidate_risk_evaluations c on c.id = crc.candidate_evaluation_id;
"""

RPT_APPROVALS_VIEW = """
create or replace view reporting.rpt_approvals as
select
    ar.id as approval_request_id,
    ad.id as approval_decision_id,
    ar.episode_id,
    ar.request_reference,
    ar.request_type,
    ar.requester_user_id,
    ar.recorded_at as requested_at,
    ar.expires_at,
    ar.reason,
    ad.decision_role,
    ad.approver_user_id,
    ad.recorded_at as decision_recorded_at,
    ad.outcome,
    ad.conditions,
    ad.independence_check_passed,
    case
        when ad.id is null then null
        else ar.requester_user_id = ad.approver_user_id
    end as requester_equals_approver,
    coalesce(ar.requester_user_id = ad.approver_user_id, false) as is_self_approval_violation,
    case
        when ad.id is not null then 'decided'
        when ar.expires_at is not null and ar.expires_at <= current_timestamp then 'expired_without_decision'
        else 'pending'
    end as request_status,
    (ad.id is null) as is_pending,
    case when ad.id is null then 0 else 1 end as decision_count
from approval_requests ar
left join approval_decisions ad on ad.approval_request_id = ar.id;
"""

RPT_SUPPRESSIONS_VIEW = """
create or replace view reporting.rpt_suppressions as
select
    sc.id as suppression_control_id,
    sc.episode_id,
    sc.approval_request_id,
    sc.prior_state,
    sc.reason_code,
    sc.starts_at,
    sc.expires_at,
    sc.review_at,
    sc.sla_consumed_minutes_at_pause,
    sc.recurrence_criteria,
    (e.current_state = 'suppressed') as is_current_episode_state_suppressed,
    (extract(epoch from (sc.expires_at - sc.starts_at)) / 3600)::numeric(18, 2)
        as suppression_duration_hours,
    (sc.starts_at <= current_timestamp and sc.expires_at > current_timestamp) as is_currently_effective,
    (sc.expires_at <= current_timestamp) as is_expired,
    (sc.expires_at > current_timestamp and sc.expires_at <= current_timestamp + interval '7 days')
        as expires_within_7_days
from suppression_controls sc
join exception_episodes e on e.id = sc.episode_id;
"""

RPT_PIPELINE_RUNS_VIEW = """
create or replace view reporting.rpt_pipeline_runs as
with source_load_rollup as (
    select
        pipeline_run_id,
        count(*)::integer as source_load_count
    from source_loads
    group by pipeline_run_id
),
step_rollup as (
    select
        pipeline_run_id,
        count(*)::integer as step_count,
        count(*) filter (where status = 'success')::integer as successful_step_count,
        count(*) filter (where status = 'failed')::integer as failed_step_count
    from pipeline_step_results
    group by pipeline_run_id
),
reconciliation_rollup as (
    select
        pipeline_run_id,
        count(*) filter (where is_blocking)::integer as blocking_reconciliation_count,
        coalesce(sum(difference_count), 0)::integer as reconciliation_difference_count
    from reconciliation_results
    group by pipeline_run_id
),
rejected_rollup as (
    select
        pipeline_run_id,
        count(*)::integer as rejected_record_count
    from rejected_records
    where pipeline_run_id is not null
    group by pipeline_run_id
),
publication_rollup as (
    select
        pipeline_run_id,
        count(*)::integer as publication_count
    from analytics_publications
    group by pipeline_run_id
)
select
    pr.id as pipeline_run_id,
    pr.run_reference,
    pr.run_type,
    pr.trigger_type,
    pr.status,
    pr.started_at,
    pr.finished_at,
    case
        when pr.finished_at is null then null
        else extract(epoch from (pr.finished_at - pr.started_at))::numeric(18, 2)
    end as duration_seconds,
    pr.release_version,
    pr.configuration_hash,
    pr.is_publication_eligible,
    pr.bundle_reference,
    pr.manifest_hash,
    pr.bundle_fingerprint,
    pr.upstream_generator_version,
    pr.source_row_count,
    pr.accepted_row_count,
    pr.rejected_row_count,
    pr.failure_reason,
    coalesce(sl.source_load_count, 0) as source_load_count,
    coalesce(sr.step_count, 0) as step_count,
    coalesce(sr.successful_step_count, 0) as successful_step_count,
    coalesce(sr.failed_step_count, 0) as failed_step_count,
    coalesce(rr.blocking_reconciliation_count, 0) as blocking_reconciliation_count,
    coalesce(rr.reconciliation_difference_count, 0) as reconciliation_difference_count,
    coalesce(rej.rejected_record_count, 0) as rejected_record_count,
    coalesce(pub.publication_count, 0) as publication_count,
    (pr.status = 'success') as is_success,
    (pr.status = 'failed') as is_failed
from pipeline_runs pr
left join source_load_rollup sl on sl.pipeline_run_id = pr.id
left join step_rollup sr on sr.pipeline_run_id = pr.id
left join reconciliation_rollup rr on rr.pipeline_run_id = pr.id
left join rejected_rollup rej on rej.pipeline_run_id = pr.id
left join publication_rollup pub on pub.pipeline_run_id = pr.id;
"""
