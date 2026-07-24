"""PostgreSQL service for deterministic candidate risk evaluation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from scecs.database import create_database_engine, create_session_factory, session_scope
from scecs.models.master_data import ProductSiteInventoryPolicy, RuleComponentDefinition, RuleVersion
from scecs.models.procurement import (
    DeliverySchedule,
    DemandRequirement,
    InventorySnapshot,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderLineVersion,
    PurchaseOrderVersion,
    ReceiptAllocation,
    ReceiptTransaction,
    SupplierCommitmentObservation,
    SupplierPerformanceSnapshot,
)
from scecs.models.scoring import CandidateRiskContribution, CandidateRiskEvaluation
from scecs.models.source_control import PipelineRun
from scecs.models.workflow import ExceptionEpisode
from scecs.risk.rules import RULE_CODE, RULE_VERSION, RULE_VERSION_IDENTIFIER, RiskInput, ScoreResult, score_candidate


@dataclass(frozen=True)
class ScoringRunResult:
    """Summary of one scoring run."""

    run_reference: str
    evaluated_count: int
    inserted_count: int
    existing_count: int
    candidate_ids: tuple[uuid.UUID, ...]


def score_operational_candidates(
    *,
    as_of: datetime | None = None,
    run_reference: str | None = None,
) -> ScoringRunResult:
    """Score all eligible open operational PO-line/site candidates from PostgreSQL."""

    engine = create_database_engine()
    session_factory = create_session_factory(engine)
    evaluated_at = (as_of or datetime.now(UTC)).astimezone(UTC)
    with session_scope(session_factory) as session:
        run = _get_or_create_scoring_run(session, evaluated_at, run_reference)
        rule_version = _ensure_rule_version(session, evaluated_at)
        candidates = collect_candidate_inputs(session, evaluated_at)
        inserted = 0
        existing = 0
        candidate_ids: list[uuid.UUID] = []
        component_ids = _ensure_rule_components(session, rule_version)
        for risk_input in candidates:
            active_episode_id = _active_episode_id(session, risk_input)
            result = score_candidate(risk_input, linked_active_episode=active_episode_id is not None)
            candidate_id, was_inserted = _persist_candidate(
                session,
                run,
                rule_version,
                result,
                risk_input,
                active_episode_id,
                component_ids,
                evaluated_at,
            )
            inserted += int(was_inserted)
            existing += int(not was_inserted)
            candidate_ids.append(candidate_id)
        run.status = "success"
        run.finished_at = datetime.now(UTC)
        run.accepted_row_count = len(candidates)
        run.rejected_row_count = 0
        run.is_publication_eligible = False
        return ScoringRunResult(run.run_reference, len(candidates), inserted, existing, tuple(candidate_ids))


def collect_candidate_inputs(session: Session, as_of: datetime) -> list[RiskInput]:
    """Collect eligible open PO-line/site scoring inputs from operational tables."""

    as_of_date = as_of.date()
    rows = session.execute(_latest_open_line_statement()).all()
    candidates: list[RiskInput] = []
    for line, line_version, order_version in rows:
        residual_quantity = _residual_quantity(
            session, line.id, line_version.base_quantity or line_version.ordered_quantity
        )
        if residual_quantity <= 0:
            continue
        expected_date = _expected_receipt_date(session, line.id)
        confirmed_date = _confirmed_date(session, line.id)
        inventory_available, inventory_stale = _latest_inventory(
            session, line_version.product_id, line_version.site_id, as_of
        )
        demand_until_receipt, demand_unavailable = _demand_until_receipt(
            session, line_version.product_id, line_version.site_id, as_of_date, expected_date or line_version.need_date
        )
        safety_stock, criticality = _inventory_policy(session, line_version.product_id, line_version.site_id, as_of)
        supplier_otif, supplier_count = _supplier_otif(
            session, order_version.supplier_id, line_version.site_id, as_of_date
        )
        recent_otif, recent_count, prior_otif, prior_count = _supplier_trend(
            session, order_version.supplier_id, line_version.site_id, as_of_date
        )
        line_value = _decimal(line_version.line_value_aud)
        base_quantity = _decimal(line_version.base_quantity or line_version.ordered_quantity)
        residual_value = None
        if line_value is not None and base_quantity > 0:
            residual_value = (line_value * residual_quantity / base_quantity).quantize(Decimal("0.01"))
        elif line_version.unit_price_aud is not None:
            residual_value = (_decimal(line_version.unit_price_aud) * residual_quantity).quantize(Decimal("0.01"))
        candidates.append(
            RiskInput(
                po_line_id=str(line.id),
                site_id=str(line_version.site_id),
                supplier_id=str(order_version.supplier_id),
                product_id=str(line_version.product_id),
                as_of_date=as_of_date,
                order_date=order_version.order_date,
                need_date=line_version.need_date,
                confirmed_date=confirmed_date,
                expected_receipt_date=expected_date,
                residual_quantity=residual_quantity,
                base_quantity=base_quantity,
                residual_value_aud=residual_value,
                criticality=criticality,
                inventory_available_quantity=inventory_available,
                safety_stock_quantity=safety_stock,
                demand_until_receipt=demand_until_receipt,
                inventory_stale=inventory_stale,
                demand_unavailable=demand_unavailable,
                supplier_otif_rate=supplier_otif,
                supplier_observation_count=supplier_count,
                recent_otif_rate=recent_otif,
                recent_observation_count=recent_count,
                prior_otif_rate=prior_otif,
                prior_observation_count=prior_count,
                lead_time_baseline_days=None,
            )
        )
    return candidates


def _latest_open_line_statement() -> Select[tuple[PurchaseOrderLine, PurchaseOrderLineVersion, PurchaseOrderVersion]]:
    latest_line = (
        select(
            PurchaseOrderLineVersion.po_line_id,
            func.max(PurchaseOrderLineVersion.amendment_version).label("amendment_version"),
        )
        .group_by(PurchaseOrderLineVersion.po_line_id)
        .subquery()
    )
    latest_order = (
        select(
            PurchaseOrderVersion.purchase_order_id,
            func.max(PurchaseOrderVersion.amendment_version).label("amendment_version"),
        )
        .group_by(PurchaseOrderVersion.purchase_order_id)
        .subquery()
    )
    return (
        select(PurchaseOrderLine, PurchaseOrderLineVersion, PurchaseOrderVersion)
        .join(PurchaseOrderLineVersion, PurchaseOrderLineVersion.po_line_id == PurchaseOrderLine.id)
        .join(
            latest_line,
            and_(
                latest_line.c.po_line_id == PurchaseOrderLineVersion.po_line_id,
                latest_line.c.amendment_version == PurchaseOrderLineVersion.amendment_version,
            ),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .join(PurchaseOrderVersion, PurchaseOrderVersion.purchase_order_id == PurchaseOrder.id)
        .join(
            latest_order,
            and_(
                latest_order.c.purchase_order_id == PurchaseOrderVersion.purchase_order_id,
                latest_order.c.amendment_version == PurchaseOrderVersion.amendment_version,
            ),
        )
        .where(PurchaseOrderLineVersion.line_status.in_(("open", "on_hold")))
        .where(PurchaseOrderVersion.order_status.in_(("open", "on_hold")))
        .order_by(PurchaseOrderLine.canonical_line_key)
    )


def _get_or_create_scoring_run(session: Session, evaluated_at: datetime, run_reference: str | None) -> PipelineRun:
    reference = run_reference or f"RISK-{evaluated_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    existing = session.execute(select(PipelineRun).where(PipelineRun.run_reference == reference)).scalar_one_or_none()
    if existing is not None:
        return existing
    run = PipelineRun(
        run_reference=reference,
        run_type="risk_scoring",
        trigger_type="manual",
        status="running",
        started_at=evaluated_at,
        release_version=RULE_VERSION_IDENTIFIER,
        configuration_hash=RULE_VERSION_IDENTIFIER,
        is_publication_eligible=False,
    )
    session.add(run)
    session.flush()
    return run


def _ensure_rule_version(session: Session, evaluated_at: datetime) -> RuleVersion:
    existing = session.execute(
        select(RuleVersion).where(RuleVersion.rule_code == RULE_CODE, RuleVersion.version == RULE_VERSION)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    rule_version = RuleVersion(
        id=uuid.uuid5(uuid.NAMESPACE_URL, RULE_VERSION_IDENTIFIER),
        rule_code=RULE_CODE,
        version=RULE_VERSION,
        status="approved",
        owner="Synthetic Governance",
        rationale="Frozen deterministic risk-priority score specification v1.0.",
        approved_at=evaluated_at,
        effective_from=evaluated_at,
    )
    session.add(rule_version)
    session.flush()
    return rule_version


def _ensure_rule_components(session: Session, rule_version: RuleVersion) -> dict[str, uuid.UUID]:
    components = {
        "RPR-DLY-01": ("delivery", Decimal("30")),
        "RPR-DLY-02": ("delivery", Decimal("20")),
        "RPR-DLY-03": ("delivery", Decimal("10")),
        "RPR-INV-01": ("inventory", Decimal("25")),
        "RPR-INV-02": ("inventory", Decimal("5")),
        "RPR-VIS-01": ("visibility_data", Decimal("15")),
        "RPR-DAT-01": ("visibility_data", Decimal("15")),
        "RPR-SUP-01": ("supplier", Decimal("15")),
        "RPR-SUP-02": ("supplier", Decimal("5")),
        "RPR-CON-01": ("consequence", Decimal("5")),
        "RPR-CON-02": ("consequence", Decimal("10")),
        "RPR-MIT-01": ("mitigation", Decimal("-15")),
    }
    existing = {
        row.component_code: row.id
        for row in session.execute(
            select(RuleComponentDefinition).where(RuleComponentDefinition.rule_version_id == rule_version.id)
        ).scalars()
    }
    for code, (family, max_points) in components.items():
        if code in existing:
            continue
        component = RuleComponentDefinition(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"{RULE_VERSION_IDENTIFIER}:{code}"),
            rule_version_id=rule_version.id,
            component_code=code,
            component_family=family,
            max_points=max_points,
            metadata_json={"rule_version": RULE_VERSION_IDENTIFIER},
        )
        session.add(component)
        existing[code] = component.id
    session.flush()
    return existing


def _persist_candidate(
    session: Session,
    run: PipelineRun,
    rule_version: RuleVersion,
    result: ScoreResult,
    risk_input: RiskInput,
    active_episode_id: uuid.UUID | None,
    component_ids: dict[str, uuid.UUID],
    evaluated_at: datetime,
) -> tuple[uuid.UUID, bool]:
    existing = session.execute(
        select(CandidateRiskEvaluation).where(
            CandidateRiskEvaluation.pipeline_run_id == run.id,
            CandidateRiskEvaluation.po_line_id == uuid.UUID(risk_input.po_line_id),
            CandidateRiskEvaluation.site_id == uuid.UUID(risk_input.site_id),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id, False
    candidate = CandidateRiskEvaluation(
        pipeline_run_id=run.id,
        po_line_id=uuid.UUID(risk_input.po_line_id),
        site_id=uuid.UUID(risk_input.site_id),
        rule_version_id=rule_version.id,
        evaluated_at=evaluated_at,
        input_fingerprint=result.input_fingerprint,
        eligibility_status="eligible" if result.opening_eligible else "not_opening_eligible",
        score=result.score,
        calculated_severity=result.band,
        score_confidence=result.score_confidence,
        disposition=result.primary_disposition,
        linked_episode_id=active_episode_id,
        explanation_summary=_explanation_summary(result),
        missing_signal_payload={
            "missing_signals": list(result.missing_signals),
            "opening_eligible": result.opening_eligible,
            "opening_basis": result.opening_basis,
            "rule_version": RULE_VERSION_IDENTIFIER,
        },
    )
    session.add(candidate)
    session.flush()
    for contribution in result.contributions:
        session.add(
            CandidateRiskContribution(
                candidate_evaluation_id=candidate.id,
                rule_component_id=component_ids.get(contribution.component_code),
                component_code=contribution.component_code,
                component_family=contribution.component_family,
                availability_status=contribution.availability_status,
                observed_value=contribution.observed_value,
                comparator=contribution.comparator,
                threshold_value=contribution.threshold_value,
                triggered=contribution.triggered,
                gross_points=contribution.gross_points,
                cap_adjustment=contribution.cap_adjustment,
                applied_points=contribution.applied_points,
                missing_signal_reason=contribution.missing_signal_reason,
                explanation_code=contribution.explanation_code,
                input_lineage=contribution.input_lineage,
            )
        )
    return candidate.id, True


def _explanation_summary(result: ScoreResult) -> str:
    return (
        f"{result.band} score {result.score}; "
        f"opening_eligible={result.opening_eligible}; "
        f"basis={result.opening_basis or 'none'}; "
        f"confidence={result.score_confidence}"
    )


def _active_episode_id(session: Session, risk_input: RiskInput) -> uuid.UUID | None:
    return session.execute(
        select(ExceptionEpisode.id).where(
            ExceptionEpisode.po_line_id == uuid.UUID(risk_input.po_line_id),
            ExceptionEpisode.site_id == uuid.UUID(risk_input.site_id),
            ExceptionEpisode.closed_at.is_(None),
        )
    ).scalar_one_or_none()


def _residual_quantity(session: Session, po_line_id: uuid.UUID, ordered_quantity: object) -> Decimal:
    received = session.execute(
        select(func.coalesce(func.sum(ReceiptAllocation.allocated_base_quantity), 0))
        .join(ReceiptTransaction, ReceiptTransaction.id == ReceiptAllocation.receipt_transaction_id)
        .where(ReceiptTransaction.po_line_id == po_line_id)
    ).scalar_one()
    residual = _decimal(ordered_quantity) - _decimal(received)
    return max(Decimal("0"), residual)


def _expected_receipt_date(session: Session, po_line_id: uuid.UUID) -> date | None:
    return session.execute(
        select(func.min(DeliverySchedule.expected_date)).where(
            DeliverySchedule.po_line_id == po_line_id,
            DeliverySchedule.expected_date.is_not(None),
        )
    ).scalar_one_or_none()


def _confirmed_date(session: Session, po_line_id: uuid.UUID) -> date | None:
    schedule_date = session.execute(
        select(func.max(DeliverySchedule.confirmed_date)).where(
            DeliverySchedule.po_line_id == po_line_id,
            DeliverySchedule.confirmed_date.is_not(None),
        )
    ).scalar_one_or_none()
    if schedule_date is not None:
        return schedule_date
    return session.execute(
        select(func.max(SupplierCommitmentObservation.committed_date)).where(
            SupplierCommitmentObservation.po_line_id == po_line_id,
            SupplierCommitmentObservation.committed_date.is_not(None),
        )
    ).scalar_one_or_none()


def _latest_inventory(
    session: Session, product_id: uuid.UUID, site_id: uuid.UUID, as_of: datetime
) -> tuple[Decimal | None, bool]:
    snapshot = session.execute(
        select(InventorySnapshot)
        .where(
            InventorySnapshot.product_id == product_id,
            InventorySnapshot.site_id == site_id,
            InventorySnapshot.snapshot_at <= as_of,
        )
        .order_by(InventorySnapshot.snapshot_at.desc(), InventorySnapshot.snapshot_version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if snapshot is None:
        return None, True
    stale = snapshot.snapshot_at < as_of - timedelta(hours=26)
    return _decimal(snapshot.available_quantity), stale


def _demand_until_receipt(
    session: Session, product_id: uuid.UUID, site_id: uuid.UUID, as_of_date: date, receipt_date: date
) -> tuple[Decimal | None, bool]:
    demand = session.execute(
        select(func.coalesce(func.sum(DemandRequirement.required_quantity), 0)).where(
            DemandRequirement.product_id == product_id,
            DemandRequirement.site_id == site_id,
            DemandRequirement.required_date >= as_of_date,
            DemandRequirement.required_date <= receipt_date,
        )
    ).scalar_one()
    exists = session.execute(
        select(DemandRequirement.id)
        .where(DemandRequirement.product_id == product_id, DemandRequirement.site_id == site_id)
        .limit(1)
    ).scalar_one_or_none()
    return _decimal(demand), exists is None


def _inventory_policy(
    session: Session, product_id: uuid.UUID, site_id: uuid.UUID, as_of: datetime
) -> tuple[Decimal | None, str | None]:
    policy = session.execute(
        select(ProductSiteInventoryPolicy)
        .where(
            ProductSiteInventoryPolicy.product_id == product_id,
            ProductSiteInventoryPolicy.site_id == site_id,
            ProductSiteInventoryPolicy.effective_from <= as_of,
            or_(ProductSiteInventoryPolicy.effective_to.is_(None), ProductSiteInventoryPolicy.effective_to > as_of),
        )
        .order_by(ProductSiteInventoryPolicy.effective_from.desc())
        .limit(1)
    ).scalar_one_or_none()
    if policy is None:
        return None, None
    return _decimal(policy.safety_stock_quantity), policy.criticality


def _supplier_otif(
    session: Session, supplier_id: uuid.UUID, site_id: uuid.UUID, as_of_date: date
) -> tuple[Decimal | None, int | None]:
    start = as_of_date - timedelta(days=365)
    row = session.execute(
        select(
            func.sum(SupplierPerformanceSnapshot.numerator_count),
            func.sum(SupplierPerformanceSnapshot.denominator_count),
        ).where(
            SupplierPerformanceSnapshot.supplier_id == supplier_id,
            or_(SupplierPerformanceSnapshot.site_id == site_id, SupplierPerformanceSnapshot.site_id.is_(None)),
            SupplierPerformanceSnapshot.window_start >= start,
            SupplierPerformanceSnapshot.window_end <= as_of_date,
        )
    ).one()
    denominator = int(row[1] or 0)
    if denominator == 0:
        return None, None
    return (Decimal(int(row[0] or 0)) / Decimal(denominator)).quantize(Decimal("0.0001")), denominator


def _supplier_trend(
    session: Session, supplier_id: uuid.UUID, site_id: uuid.UUID, as_of_date: date
) -> tuple[Decimal | None, int | None, Decimal | None, int | None]:
    recent = _supplier_window(session, supplier_id, site_id, as_of_date - timedelta(days=90), as_of_date)
    prior = _supplier_window(
        session, supplier_id, site_id, as_of_date - timedelta(days=365), as_of_date - timedelta(days=91)
    )
    return (*recent, *prior)


def _supplier_window(
    session: Session, supplier_id: uuid.UUID, site_id: uuid.UUID, start: date, end: date
) -> tuple[Decimal | None, int | None]:
    row = session.execute(
        select(
            func.sum(SupplierPerformanceSnapshot.numerator_count),
            func.sum(SupplierPerformanceSnapshot.denominator_count),
        ).where(
            SupplierPerformanceSnapshot.supplier_id == supplier_id,
            or_(SupplierPerformanceSnapshot.site_id == site_id, SupplierPerformanceSnapshot.site_id.is_(None)),
            SupplierPerformanceSnapshot.window_start >= start,
            SupplierPerformanceSnapshot.window_end <= end,
        )
    ).one()
    denominator = int(row[1] or 0)
    if denominator == 0:
        return None, None
    return (Decimal(int(row[0] or 0)) / Decimal(denominator)).quantize(Decimal("0.0001")), denominator


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))
