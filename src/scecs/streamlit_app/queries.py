"""Read/query service for the Streamlit operational MVP."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Engine, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.elements import TextClause

from scecs.streamlit_app.view_models import (
    ApprovalRow,
    AuditEventRow,
    CandidateRow,
    ControlTowerSummary,
    DetailActionRow,
    DistributionRow,
    ExceptionDetail,
    ExceptionQueueRow,
    OwnershipHistoryRow,
    PipelineStatus,
    RiskContributionRow,
    SuppressionRow,
    UserOption,
)

HIGH_PRIORITY_BANDS = {"critical", "high"}
ACTIVE_STATES = {"open", "assigned", "investigating", "action_agreed", "monitoring", "resolved", "suppressed"}


class OperationalReadService:
    """Read-side service for Streamlit pages."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def active_users(self, as_of: datetime | None = None) -> tuple[UserOption, ...]:
        """Return active human users for simulation-only actor switching."""

        timestamp = _utc(as_of)
        statement = text(
            """
            select id, user_code, display_name, role_classification
            from users
            where actor_type = 'human'
              and active_from <= :as_of
              and (active_to is null or active_to > :as_of)
            order by user_code
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"as_of": timestamp}).mappings().all()
        return tuple(
            UserOption(
                user_id=_uuid(row["id"]),
                user_code=str(row["user_code"]),
                display_name=str(row["display_name"]),
                role_classification=str(row["role_classification"]),
            )
            for row in rows
        )

    def control_tower_summary(
        self,
        *,
        site_codes: Sequence[str] = (),
        supplier_names: Sequence[str] = (),
        as_of: datetime | None = None,
    ) -> ControlTowerSummary:
        """Return KPI and chart data for the control tower."""

        queue_rows = self.exception_queue(site_codes=site_codes, supplier_names=supplier_names, as_of=as_of)
        candidates = self.opening_eligible_candidates(site_codes=site_codes, supplier_names=supplier_names)
        active_rows = tuple(row for row in queue_rows if row.state in ACTIVE_STATES)
        state_distribution = _distribution(tuple(row.state for row in queue_rows))
        risk_distribution = _distribution(tuple(row.band or "unknown" for row in queue_rows))
        highest_priority = tuple(
            sorted(
                active_rows,
                key=lambda row: (row.score or Decimal("0"), row.residual_value or Decimal("0")),
                reverse=True,
            )[:10]
        )
        return ControlTowerSummary(
            active_exceptions=len(active_rows),
            critical_high_exceptions=sum(1 for row in active_rows if (row.band or "").lower() in HIGH_PRIORITY_BANDS),
            unassigned_exceptions=sum(1 for row in active_rows if row.owner_user_id is None),
            sla_breached_conditions=sum(1 for row in active_rows if row.sla_status == "breached"),
            opening_eligible_candidates=len(candidates),
            state_distribution=state_distribution,
            risk_band_distribution=risk_distribution,
            highest_priority=highest_priority,
            pipeline_status=self.pipeline_status(),
        )

    def filter_options(self) -> dict[str, tuple[str, ...]]:
        """Return queue/control-tower filter option values."""

        rows = self.exception_queue()
        candidates = self.opening_eligible_candidates()
        site_codes = sorted({row.site_code for row in rows} | {row.site_code for row in candidates})
        supplier_names = sorted({row.supplier_name for row in rows} | {row.supplier_name for row in candidates})
        owner_names = sorted({row.owner for row in rows if row.owner})
        states = sorted({row.state for row in rows})
        bands = sorted({row.band for row in rows if row.band})
        return {
            "sites": tuple(site_codes),
            "suppliers": tuple(supplier_names),
            "owners": tuple(owner_names),
            "states": tuple(states),
            "bands": tuple(bands),
        }

    def exception_queue(
        self,
        *,
        states: Sequence[str] = (),
        risk_bands: Sequence[str] = (),
        site_codes: Sequence[str] = (),
        supplier_names: Sequence[str] = (),
        owner_names: Sequence[str] = (),
        unassigned_only: bool = False,
        sla_statuses: Sequence[str] = (),
        search_text: str = "",
        as_of: datetime | None = None,
    ) -> tuple[ExceptionQueueRow, ...]:
        """Return filterable exception queue rows."""

        params = {
            "as_of": _utc(as_of),
        }
        with self._engine.connect() as connection:
            rows = connection.execute(_queue_statement(), params).mappings().all()
        queue_rows = tuple(_queue_row(row) for row in rows)
        return tuple(
            row
            for row in queue_rows
            if _matches_exception_filters(
                row,
                states=states,
                risk_bands=risk_bands,
                site_codes=site_codes,
                supplier_names=supplier_names,
                owner_names=owner_names,
                unassigned_only=unassigned_only,
                sla_statuses=sla_statuses,
                search_text=search_text,
            )
        )

    def opening_eligible_candidates(
        self,
        *,
        site_codes: Sequence[str] = (),
        supplier_names: Sequence[str] = (),
        search_text: str = "",
    ) -> tuple[CandidateRow, ...]:
        """Return candidates that can still be opened into workflow."""

        with self._engine.connect() as connection:
            rows = connection.execute(_candidate_statement()).mappings().all()
        candidates = tuple(_candidate_row(row) for row in rows)
        return tuple(
            row
            for row in candidates
            if _matches_candidate_filters(
                row,
                site_codes=site_codes,
                supplier_names=supplier_names,
                search_text=search_text,
            )
        )

    def exception_detail(self, episode_id: uuid.UUID, *, as_of: datetime | None = None) -> ExceptionDetail | None:
        """Return complete detail data for one episode."""

        rows = self.exception_queue(as_of=as_of)
        summary = next((row for row in rows if row.episode_id == episode_id), None)
        if summary is None:
            return None
        params = {"episode_id": episode_id}
        with self._engine.connect() as connection:
            missing = connection.execute(_missing_signal_statement(), params).mappings().first()
            contributions = connection.execute(_contribution_statement(), params).mappings().all()
            ownership = connection.execute(_ownership_statement(), params).mappings().all()
            actions = connection.execute(_action_statement(), params).mappings().all()
            approvals = connection.execute(_approval_statement(), params).mappings().all()
            suppressions = connection.execute(_suppression_statement(), params).mappings().all()
            audit = connection.execute(_audit_statement(), params).mappings().all()
        return ExceptionDetail(
            summary=summary,
            missing_signals=_mapping_or_empty(missing["missing_signal_payload"] if missing else None),
            risk_contributions=tuple(_contribution_row(row) for row in contributions),
            ownership_history=tuple(_ownership_row(row) for row in ownership),
            actions=tuple(_action_row(row) for row in actions),
            approvals=tuple(_approval_row(row) for row in approvals),
            suppressions=tuple(_suppression_row(row) for row in suppressions),
            audit_events=tuple(_audit_row(row) for row in audit),
        )

    def latest_action_agreement_id(self, episode_id: uuid.UUID) -> uuid.UUID | None:
        """Return latest action agreement id for update commands."""

        statement = text(
            """
            select id
            from exception_actions
            where episode_id = :episode_id
              and action_category = 'action_agreement'
            order by action_sequence desc
            limit 1
            """
        )
        with self._engine.connect() as connection:
            value = connection.execute(statement, {"episode_id": episode_id}).scalar_one_or_none()
        return _uuid(value) if value is not None else None

    def pipeline_status(self) -> PipelineStatus:
        """Return latest pipeline and latest successful/current publication status."""

        pipeline_statement = text(
            """
            select run_reference, run_type, status, finished_at
            from pipeline_runs
            order by started_at desc
            limit 1
            """
        )
        publication_statement = text(
            """
            select publication_reference, status, published_at
            from analytics_publications
            where is_current_success = true or status = 'success'
            order by published_at desc nulls last, recorded_at desc
            limit 1
            """
        )
        with self._engine.connect() as connection:
            pipeline = connection.execute(pipeline_statement).mappings().first()
            publication = connection.execute(publication_statement).mappings().first()
        return PipelineStatus(
            latest_pipeline_reference=str(pipeline["run_reference"]) if pipeline else None,
            latest_pipeline_type=str(pipeline["run_type"]) if pipeline else None,
            latest_pipeline_status=str(pipeline["status"]) if pipeline else None,
            latest_pipeline_finished_at=_datetime_or_none(pipeline["finished_at"]) if pipeline else None,
            latest_publication_reference=str(publication["publication_reference"]) if publication else None,
            latest_publication_status=str(publication["status"]) if publication else None,
            latest_publication_at=_datetime_or_none(publication["published_at"]) if publication else None,
        )


def _queue_statement() -> TextClause:
    return text(
        """
        with latest_line as (
            select distinct on (po_line_id)
                po_line_id, product_id, site_id, need_date, base_quantity,
                ordered_quantity, line_value_aud, unit_price_aud
            from purchase_order_line_versions
            order by po_line_id, amendment_version desc
        ),
        latest_order as (
            select distinct on (purchase_order_id)
                purchase_order_id, supplier_id
            from purchase_order_versions
            order by purchase_order_id, amendment_version desc
        ),
        latest_product as (
            select distinct on (product_id)
                product_id, description
            from product_versions
            order by product_id, effective_from desc
        ),
        latest_supplier as (
            select distinct on (supplier_id)
                supplier_id, display_name
            from supplier_versions
            order by supplier_id, effective_from desc
        ),
        receipts as (
            select rt.po_line_id, coalesce(sum(ra.allocated_base_quantity), 0) as received_quantity
            from receipt_transactions rt
            join receipt_allocations ra on ra.receipt_transaction_id = rt.id
            group by rt.po_line_id
        ),
        sla as (
            select episode_id,
                case
                    when count(*) filter (
                        where satisfied_at is null
                          and cancelled_at is null
                          and original_due_at < :as_of
                    ) > 0 then 'breached'
                    when count(*) filter (
                        where satisfied_at is null
                          and cancelled_at is null
                    ) > 0 then 'active'
                    else 'not_tracked'
                end as sla_status
            from sla_obligations
            group by episode_id
        )
        select
            e.id as episode_id,
            ('EX-' || e.episode_sequence::text || '-' || left(e.id::text, 8)) as exception_reference,
            s.site_code,
            coalesce(sv.display_name, sup.supplier_code) as supplier_name,
            pol.canonical_line_key as po_line,
            coalesce(pv.description, p.sku) as product,
            e.current_state as state,
            owner.display_name as owner,
            e.current_owner_user_id as owner_user_id,
            c.score,
            c.calculated_severity as band,
            greatest(coalesce(ll.base_quantity, ll.ordered_quantity, 0) - coalesce(r.received_quantity, 0), 0)
                as residual_quantity,
            case
                when ll.line_value_aud is not null
                  and coalesce(ll.base_quantity, ll.ordered_quantity, 0) > 0
                    then ll.line_value_aud
                       * greatest(
                            coalesce(ll.base_quantity, ll.ordered_quantity, 0)
                            - coalesce(r.received_quantity, 0),
                            0
                       )
                       / coalesce(ll.base_quantity, ll.ordered_quantity, 1)
                when ll.unit_price_aud is not null
                    then ll.unit_price_aud
                       * greatest(
                            coalesce(ll.base_quantity, ll.ordered_quantity, 0)
                            - coalesce(r.received_quantity, 0),
                            0
                       )
                else null
            end as residual_value,
            ll.need_date,
            e.opened_at,
            coalesce(sla.sla_status, 'not_tracked') as sla_status
        from exception_episodes e
        join purchase_order_lines pol on pol.id = e.po_line_id
        join purchase_orders po on po.id = pol.purchase_order_id
        join latest_order lo on lo.purchase_order_id = po.id
        join suppliers sup on sup.id = lo.supplier_id
        left join latest_supplier sv on sv.supplier_id = sup.id
        join latest_line ll on ll.po_line_id = pol.id
        join sites s on s.id = e.site_id
        join products p on p.id = ll.product_id
        left join latest_product pv on pv.product_id = p.id
        left join candidate_risk_evaluations c on c.id = e.current_candidate_id
        left join users owner on owner.id = e.current_owner_user_id
        left join receipts r on r.po_line_id = pol.id
        left join sla on sla.episode_id = e.id
        order by c.score desc nulls last, e.opened_at desc
        """
    )


def _candidate_statement() -> TextClause:
    return text(
        """
        with latest_line as (
            select distinct on (po_line_id)
                po_line_id, product_id, site_id, need_date, base_quantity,
                ordered_quantity, line_value_aud, unit_price_aud
            from purchase_order_line_versions
            order by po_line_id, amendment_version desc
        ),
        latest_order as (
            select distinct on (purchase_order_id)
                purchase_order_id, supplier_id
            from purchase_order_versions
            order by purchase_order_id, amendment_version desc
        ),
        latest_product as (
            select distinct on (product_id)
                product_id, description
            from product_versions
            order by product_id, effective_from desc
        ),
        latest_supplier as (
            select distinct on (supplier_id)
                supplier_id, display_name
            from supplier_versions
            order by supplier_id, effective_from desc
        ),
        receipts as (
            select rt.po_line_id, coalesce(sum(ra.allocated_base_quantity), 0) as received_quantity
            from receipt_transactions rt
            join receipt_allocations ra on ra.receipt_transaction_id = rt.id
            group by rt.po_line_id
        )
        select
            c.id as candidate_id,
            s.site_code,
            coalesce(sv.display_name, sup.supplier_code) as supplier_name,
            pol.canonical_line_key as po_line,
            coalesce(pv.description, p.sku) as product,
            c.score,
            c.calculated_severity as band,
            greatest(coalesce(ll.base_quantity, ll.ordered_quantity, 0) - coalesce(r.received_quantity, 0), 0)
                as residual_quantity,
            case
                when ll.line_value_aud is not null
                  and coalesce(ll.base_quantity, ll.ordered_quantity, 0) > 0
                    then ll.line_value_aud
                       * greatest(
                            coalesce(ll.base_quantity, ll.ordered_quantity, 0)
                            - coalesce(r.received_quantity, 0),
                            0
                       )
                       / coalesce(ll.base_quantity, ll.ordered_quantity, 1)
                when ll.unit_price_aud is not null
                    then ll.unit_price_aud
                       * greatest(
                            coalesce(ll.base_quantity, ll.ordered_quantity, 0)
                            - coalesce(r.received_quantity, 0),
                            0
                       )
                else null
            end as residual_value,
            ll.need_date
        from candidate_risk_evaluations c
        join purchase_order_lines pol on pol.id = c.po_line_id
        join purchase_orders po on po.id = pol.purchase_order_id
        join latest_order lo on lo.purchase_order_id = po.id
        join suppliers sup on sup.id = lo.supplier_id
        left join latest_supplier sv on sv.supplier_id = sup.id
        join latest_line ll on ll.po_line_id = pol.id
        join sites s on s.id = c.site_id
        join products p on p.id = ll.product_id
        left join latest_product pv on pv.product_id = p.id
        left join receipts r on r.po_line_id = pol.id
        where c.disposition = 'opening-eligible-no-workflow'
          and c.linked_episode_id is null
        order by c.score desc, c.evaluated_at desc
        """
    )


def _missing_signal_statement() -> TextClause:
    return text(
        """
        select c.missing_signal_payload
        from exception_episodes e
        join candidate_risk_evaluations c on c.id = e.current_candidate_id
        where e.id = :episode_id
        """
    )


def _contribution_statement() -> TextClause:
    return text(
        """
        select rc.component_code, rc.component_family, rc.availability_status,
               rc.observed_value, rc.threshold_value, rc.gross_points, rc.cap_adjustment,
               rc.applied_points, rc.missing_signal_reason, rc.explanation_code
        from exception_episodes e
        join candidate_risk_contributions rc on rc.candidate_evaluation_id = e.current_candidate_id
        where e.id = :episode_id
        order by rc.component_family, rc.component_code
        """
    )


def _ownership_statement() -> TextClause:
    return text(
        """
        select oe.ownership_sequence,
               previous_user.display_name as previous_owner,
               new_user.display_name as new_owner,
               oe.effective_from
        from ownership_events oe
        left join users previous_user on previous_user.id = oe.previous_owner_user_id
        left join users new_user on new_user.id = oe.new_owner_user_id
        where oe.episode_id = :episode_id
        order by oe.ownership_sequence
        """
    )


def _action_statement() -> TextClause:
    return text(
        """
        select ea.action_sequence, ea.action_category, ea.action_status,
               owner.display_name as owner, ea.action_payload
        from exception_actions ea
        left join users owner on owner.id = ea.action_owner_user_id
        where ea.episode_id = :episode_id
        order by ea.action_sequence
        """
    )


def _approval_statement() -> TextClause:
    return text(
        """
        select ar.request_type, requester.display_name as requester,
               approver.display_name as approver, ad.outcome, ar.reason, ar.expires_at
        from approval_requests ar
        join users requester on requester.id = ar.requester_user_id
        left join approval_decisions ad on ad.approval_request_id = ar.id
        left join users approver on approver.id = ad.approver_user_id
        where ar.episode_id = :episode_id
        order by ar.recorded_at
        """
    )


def _suppression_statement() -> TextClause:
    return text(
        """
        select sc.reason_code, sc.prior_state, sc.starts_at, sc.expires_at,
               er.external_reference as evidence_reference
        from suppression_controls sc
        left join evidence_links el
          on el.target_type = 'suppression_control'
         and el.target_id = sc.id
        left join evidence_references er on er.id = el.evidence_reference_id
        where sc.episode_id = :episode_id
        order by sc.starts_at
        """
    )


def _audit_statement() -> TextClause:
    return text(
        """
        select ev.event_sequence, ev.event_type, ev.effective_at, actor.display_name as actor,
               ev.reason_code, ev.reason_text, ev.before_payload, ev.after_payload
        from exception_event_envelopes ev
        left join users actor on actor.id = ev.actor_user_id
        where ev.episode_id = :episode_id
        order by ev.event_sequence
        """
    )


def _queue_row(row: RowMapping) -> ExceptionQueueRow:
    opened_at = _datetime(row["opened_at"])
    age_days = max(0, (_utc().date() - opened_at.date()).days)
    return ExceptionQueueRow(
        episode_id=_uuid(row["episode_id"]),
        exception_reference=str(row["exception_reference"]),
        site_code=str(row["site_code"]),
        supplier_name=str(row["supplier_name"]),
        po_line=str(row["po_line"]),
        product=str(row["product"]),
        state=str(row["state"]),
        owner=str(row["owner"]) if row["owner"] is not None else None,
        owner_user_id=_uuid(row["owner_user_id"]) if row["owner_user_id"] is not None else None,
        score=_decimal_or_none(row["score"]),
        band=str(row["band"]) if row["band"] is not None else None,
        residual_quantity=_decimal_or_none(row["residual_quantity"]),
        residual_value=_decimal_or_none(row["residual_value"]),
        need_date=_date_or_none(row["need_date"]),
        opened_at=opened_at,
        age_days=age_days,
        sla_status=str(row["sla_status"]),
    )


def _candidate_row(row: RowMapping) -> CandidateRow:
    return CandidateRow(
        candidate_id=_uuid(row["candidate_id"]),
        site_code=str(row["site_code"]),
        supplier_name=str(row["supplier_name"]),
        po_line=str(row["po_line"]),
        product=str(row["product"]),
        score=_decimal(row["score"]),
        band=str(row["band"]),
        residual_quantity=_decimal_or_none(row["residual_quantity"]),
        residual_value=_decimal_or_none(row["residual_value"]),
        need_date=_date_or_none(row["need_date"]),
    )


def _contribution_row(row: RowMapping) -> RiskContributionRow:
    return RiskContributionRow(
        component_code=str(row["component_code"]),
        component_family=str(row["component_family"]),
        availability_status=str(row["availability_status"]),
        observed_value=str(row["observed_value"]) if row["observed_value"] is not None else None,
        threshold_value=str(row["threshold_value"]) if row["threshold_value"] is not None else None,
        gross_points=_decimal(row["gross_points"]),
        cap_adjustment=_decimal(row["cap_adjustment"]),
        applied_points=_decimal(row["applied_points"]),
        missing_signal_reason=str(row["missing_signal_reason"]) if row["missing_signal_reason"] is not None else None,
        explanation_code=str(row["explanation_code"]),
    )


def _ownership_row(row: RowMapping) -> OwnershipHistoryRow:
    return OwnershipHistoryRow(
        sequence=int(str(row["ownership_sequence"])),
        previous_owner=str(row["previous_owner"]) if row["previous_owner"] is not None else None,
        new_owner=str(row["new_owner"]) if row["new_owner"] is not None else None,
        effective_from=_datetime(row["effective_from"]),
    )


def _action_row(row: RowMapping) -> DetailActionRow:
    return DetailActionRow(
        sequence=int(str(row["action_sequence"])),
        category=str(row["action_category"]),
        status=str(row["action_status"]),
        owner=str(row["owner"]) if row["owner"] is not None else None,
        payload=_mapping_or_empty(row["action_payload"]),
    )


def _approval_row(row: RowMapping) -> ApprovalRow:
    return ApprovalRow(
        request_type=str(row["request_type"]),
        requester=str(row["requester"]),
        approver=str(row["approver"]) if row["approver"] is not None else None,
        outcome=str(row["outcome"]) if row["outcome"] is not None else None,
        reason=str(row["reason"]),
        expires_at=_datetime_or_none(row["expires_at"]),
    )


def _suppression_row(row: RowMapping) -> SuppressionRow:
    return SuppressionRow(
        reason_code=str(row["reason_code"]),
        prior_state=str(row["prior_state"]),
        starts_at=_datetime(row["starts_at"]),
        expires_at=_datetime(row["expires_at"]),
        evidence_reference=str(row["evidence_reference"]) if row["evidence_reference"] is not None else None,
    )


def _audit_row(row: RowMapping) -> AuditEventRow:
    return AuditEventRow(
        sequence=int(str(row["event_sequence"])),
        event_type=str(row["event_type"]),
        effective_at=_datetime(row["effective_at"]),
        actor=str(row["actor"]) if row["actor"] is not None else None,
        reason_code=str(row["reason_code"]) if row["reason_code"] is not None else None,
        reason_text=str(row["reason_text"]) if row["reason_text"] is not None else None,
        before_payload=_mapping_or_none(row["before_payload"]),
        after_payload=_mapping_or_none(row["after_payload"]),
    )


def _distribution(labels: Iterable[str]) -> tuple[DistributionRow, ...]:
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return tuple(DistributionRow(label=label, count=count) for label, count in sorted(counts.items()))


def _matches_exception_filters(
    row: ExceptionQueueRow,
    *,
    states: Sequence[str],
    risk_bands: Sequence[str],
    site_codes: Sequence[str],
    supplier_names: Sequence[str],
    owner_names: Sequence[str],
    unassigned_only: bool,
    sla_statuses: Sequence[str],
    search_text: str,
) -> bool:
    if states and row.state not in states:
        return False
    if risk_bands and row.band not in risk_bands:
        return False
    if site_codes and row.site_code not in site_codes:
        return False
    if supplier_names and row.supplier_name not in supplier_names:
        return False
    if owner_names and row.owner not in owner_names:
        return False
    if unassigned_only and row.owner_user_id is not None:
        return False
    if sla_statuses and row.sla_status not in sla_statuses:
        return False
    return _matches_search(
        search_text,
        row.exception_reference,
        row.site_code,
        row.supplier_name,
        row.po_line,
        row.product,
    )


def _matches_candidate_filters(
    row: CandidateRow,
    *,
    site_codes: Sequence[str],
    supplier_names: Sequence[str],
    search_text: str,
) -> bool:
    if site_codes and row.site_code not in site_codes:
        return False
    if supplier_names and row.supplier_name not in supplier_names:
        return False
    return _matches_search(search_text, row.site_code, row.supplier_name, row.po_line, row.product)


def _matches_search(search_text: str, *values: str) -> bool:
    cleaned = search_text.strip().lower()
    if cleaned == "":
        return True
    return any(cleaned in value.lower() for value in values)


def _uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else _decimal(value)


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value)).astimezone(UTC)


def _datetime_or_none(value: object) -> datetime | None:
    return None if value is None else _datetime(value)


def _date_or_none(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _utc(value: datetime | None = None) -> datetime:
    timestamp = value or datetime.now(UTC)
    return timestamp.astimezone(UTC) if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)


def _mapping_or_empty(value: object) -> dict[str, object]:
    return _mapping_or_none(value) or {}


def _mapping_or_none(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {"value": str(value)}
