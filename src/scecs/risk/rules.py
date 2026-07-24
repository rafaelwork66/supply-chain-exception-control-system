"""Pure deterministic risk-priority rules.

The functions in this module do not read lifecycle outcomes or synthetic labels.
They convert operational inputs into explainable rule contributions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Final, Literal

RULE_CODE: Final = "RPR"
RULE_VERSION: Final = "1.0.0"
RULE_VERSION_IDENTIFIER: Final = "RPR-1.0.0"

AvailabilityStatus = Literal["available-not-triggered", "triggered", "unavailable", "invalid"]
ScoreConfidence = Literal["complete", "qualified", "not_scorable"]


@dataclass(frozen=True)
class RiskInput:
    """Operational facts for one PO-line/site score."""

    po_line_id: str
    site_id: str
    supplier_id: str
    product_id: str
    as_of_date: date
    order_date: date
    need_date: date
    confirmed_date: date | None
    expected_receipt_date: date | None
    residual_quantity: Decimal
    base_quantity: Decimal
    residual_value_aud: Decimal | None
    criticality: str | None
    inventory_available_quantity: Decimal | None
    safety_stock_quantity: Decimal | None
    demand_until_receipt: Decimal | None
    inventory_stale: bool
    demand_unavailable: bool
    supplier_otif_rate: Decimal | None
    supplier_observation_count: int | None
    recent_otif_rate: Decimal | None
    recent_observation_count: int | None
    prior_otif_rate: Decimal | None
    prior_observation_count: int | None
    lead_time_baseline_days: Decimal | None
    mitigation_fully_approved: bool = False


@dataclass(frozen=True)
class ComponentResult:
    """One preserved rule result before persistence."""

    component_code: str
    component_family: str
    availability_status: AvailabilityStatus
    observed_value: str | None
    comparator: str | None
    threshold_value: str | None
    triggered: bool
    gross_points: Decimal
    cap_adjustment: Decimal
    applied_points: Decimal
    missing_signal_reason: str | None
    explanation_code: str
    input_lineage: dict[str, object]


@dataclass(frozen=True)
class ScoreResult:
    """Complete risk-priority score result."""

    score: Decimal
    band: Literal["monitor", "medium", "high", "critical"]
    score_confidence: ScoreConfidence
    opening_eligible: bool
    opening_basis: str | None
    primary_disposition: str
    missing_signals: tuple[str, ...]
    contributions: tuple[ComponentResult, ...]
    input_fingerprint: str


FAMILY_CAPS: Final[dict[str, Decimal]] = {
    "delivery": Decimal("40"),
    "inventory": Decimal("30"),
    "visibility_data": Decimal("15"),
    "supplier": Decimal("15"),
    "consequence": Decimal("15"),
}


def score_candidate(risk_input: RiskInput, *, linked_active_episode: bool = False) -> ScoreResult:
    """Calculate the governed 0-100 risk-priority score for one candidate."""

    components = [
        _rpr_dly_01(risk_input),
        _rpr_dly_02(risk_input),
        _rpr_dly_03(risk_input),
        *_inventory_rules(risk_input),
        _rpr_vis_01(risk_input),
        _rpr_dat_01(risk_input),
        _rpr_sup_01(risk_input),
        _rpr_sup_02(risk_input),
        _rpr_con_01(risk_input),
        _rpr_con_02(risk_input),
        _rpr_mit_01(risk_input),
    ]
    capped_components = _apply_family_caps(components)
    raw_total = sum((component.applied_points for component in capped_components), Decimal("0"))
    score = min(Decimal("100"), max(Decimal("0"), raw_total)).quantize(Decimal("0.01"))
    missing_signals = tuple(
        component.explanation_code
        for component in capped_components
        if component.availability_status in {"unavailable", "invalid"}
    )
    confidence: ScoreConfidence = "qualified" if missing_signals else "complete"
    band = score_band(score)
    opening_basis = _opening_basis(risk_input, score, missing_signals)
    opening_eligible = opening_basis is not None
    if linked_active_episode:
        disposition = "linked-existing-active-episode"
    elif opening_eligible:
        disposition = "opening-eligible-no-workflow"
    else:
        disposition = "below-opening-threshold"
    return ScoreResult(
        score=score,
        band=band,
        score_confidence=confidence,
        opening_eligible=opening_eligible,
        opening_basis=opening_basis,
        primary_disposition=disposition,
        missing_signals=missing_signals,
        contributions=tuple(capped_components),
        input_fingerprint=input_fingerprint(risk_input),
    )


def score_band(score: Decimal) -> Literal["monitor", "medium", "high", "critical"]:
    """Return the governed inclusive score band."""

    if score < Decimal("30"):
        return "monitor"
    if score < Decimal("50"):
        return "medium"
    if score < Decimal("70"):
        return "high"
    return "critical"


def input_fingerprint(risk_input: RiskInput) -> str:
    """Return a deterministic input fingerprint for audit/idempotency evidence."""

    payload = {
        field: _json_value(value)
        for field, value in sorted(risk_input.__dict__.items())
        if field != "mitigation_fully_approved"
    }
    payload["rule_version"] = RULE_VERSION_IDENTIFIER
    payload["mitigation_fully_approved"] = risk_input.mitigation_fully_approved
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _component(
    code: str,
    family: str,
    availability: AvailabilityStatus,
    observed: object | None,
    comparator: str | None,
    threshold: str | None,
    triggered: bool,
    gross: str,
    missing: str | None,
    explanation: str,
    lineage: dict[str, object] | None = None,
) -> ComponentResult:
    gross_points = Decimal(gross)
    return ComponentResult(
        component_code=code,
        component_family=family,
        availability_status=availability,
        observed_value=None if observed is None else str(observed),
        comparator=comparator,
        threshold_value=threshold,
        triggered=triggered,
        gross_points=gross_points,
        cap_adjustment=Decimal("0"),
        applied_points=gross_points,
        missing_signal_reason=missing,
        explanation_code=explanation,
        input_lineage=lineage or {},
    )


def _rpr_dly_01(risk_input: RiskInput) -> ComponentResult:
    if risk_input.confirmed_date is None:
        return _component(
            "RPR-DLY-01",
            "delivery",
            "unavailable",
            None,
            ">",
            "latest accepted confirmed delivery date",
            False,
            "0",
            "confirmed date unavailable",
            "DLY_OVERDUE",
        )
    triggered = risk_input.residual_quantity > 0 and risk_input.as_of_date > risk_input.confirmed_date
    return _component(
        "RPR-DLY-01",
        "delivery",
        "triggered" if triggered else "available-not-triggered",
        risk_input.confirmed_date,
        ">",
        str(risk_input.as_of_date),
        triggered,
        "30" if triggered else "0",
        None,
        "DLY_OVERDUE",
    )


def _rpr_dly_02(risk_input: RiskInput) -> ComponentResult:
    if risk_input.expected_receipt_date is None:
        return _component(
            "RPR-DLY-02",
            "delivery",
            "unavailable",
            None,
            ">",
            str(risk_input.need_date),
            False,
            "0",
            "expected receipt date unavailable",
            "DLY_ETA_AFTER_NEED_4PLUS",
        )
    days_after_need = (risk_input.expected_receipt_date - risk_input.need_date).days
    points = Decimal("0")
    explanation = "DLY_ETA_AFTER_NEED_1_3"
    if 1 <= days_after_need <= 3:
        points = Decimal("10")
    elif days_after_need >= 4:
        points = Decimal("20")
        explanation = "DLY_ETA_AFTER_NEED_4PLUS"
    return _component(
        "RPR-DLY-02",
        "delivery",
        "triggered" if points > 0 else "available-not-triggered",
        days_after_need,
        ">",
        "0 days after need",
        points > 0,
        str(points),
        None,
        explanation,
    )


def _rpr_dly_03(risk_input: RiskInput) -> ComponentResult:
    if risk_input.lead_time_baseline_days is None:
        return _component(
            "RPR-DLY-03",
            "delivery",
            "unavailable",
            None,
            ">",
            "120% baseline",
            False,
            "0",
            "lead-time baseline unavailable or insufficient",
            "SIG_LT_BASELINE_UNAVAILABLE",
        )
    expected_date = risk_input.expected_receipt_date or risk_input.confirmed_date
    if expected_date is None:
        return _component(
            "RPR-DLY-03",
            "delivery",
            "unavailable",
            None,
            ">",
            "120% baseline",
            False,
            "0",
            "expected receipt date unavailable",
            "SIG_LT_BASELINE_UNAVAILABLE",
        )
    expected_lead_time = Decimal((expected_date - risk_input.order_date).days)
    ratio = expected_lead_time / risk_input.lead_time_baseline_days if risk_input.lead_time_baseline_days > 0 else None
    triggered = ratio is not None and ratio > Decimal("1.20")
    return _component(
        "RPR-DLY-03",
        "delivery",
        "triggered" if triggered else "available-not-triggered",
        None if ratio is None else ratio.quantize(Decimal("0.0001")),
        ">",
        "1.20",
        triggered,
        "10" if triggered else "0",
        None,
        "DLY_LT_VARIANCE_HIGH",
    )


def _inventory_rules(risk_input: RiskInput) -> list[ComponentResult]:
    if (
        risk_input.inventory_available_quantity is None
        or risk_input.safety_stock_quantity is None
        or risk_input.demand_until_receipt is None
        or risk_input.inventory_stale
        or risk_input.demand_unavailable
    ):
        unavailable = _component(
            "RPR-INV-01",
            "inventory",
            "unavailable",
            None,
            "<",
            "0 before focal receipt",
            False,
            "0",
            "inventory or demand coverage unavailable",
            "INV_STOCKOUT_BEFORE_RECEIPT",
        )
        inherited = _component(
            "RPR-INV-02",
            "inventory",
            "unavailable",
            None,
            ">=",
            "25% residual quantity",
            False,
            "0",
            "inherits unavailable INV-01 inputs",
            "INV_SHORTFALL_MATERIAL",
        )
        return [unavailable, inherited]
    minimum_pab = (
        risk_input.inventory_available_quantity
        - risk_input.safety_stock_quantity
        - risk_input.demand_until_receipt
    )
    stockout = minimum_pab < 0
    shortfall_ratio = abs(minimum_pab) / max(risk_input.residual_quantity, Decimal("1")) if stockout else Decimal("0")
    material = stockout and shortfall_ratio >= Decimal("0.25")
    return [
        _component(
            "RPR-INV-01",
            "inventory",
            "triggered" if stockout else "available-not-triggered",
            minimum_pab.quantize(Decimal("0.0001")),
            "<",
            "0",
            stockout,
            "25" if stockout else "0",
            None,
            "INV_STOCKOUT_BEFORE_RECEIPT",
        ),
        _component(
            "RPR-INV-02",
            "inventory",
            "triggered" if material else "available-not-triggered",
            shortfall_ratio.quantize(Decimal("0.0001")),
            ">=",
            "0.25",
            material,
            "5" if material else "0",
            None,
            "INV_SHORTFALL_MATERIAL",
        ),
    ]


def _rpr_vis_01(risk_input: RiskInput) -> ComponentResult:
    days_to_need = (risk_input.need_date - risk_input.as_of_date).days
    near_need = 0 <= days_to_need <= 7
    missing_confirmation = risk_input.confirmed_date is None and risk_input.expected_receipt_date is None
    triggered = risk_input.residual_quantity > 0 and near_need and missing_confirmation
    return _component(
        "RPR-VIS-01",
        "visibility_data",
        "triggered" if triggered else "available-not-triggered",
        days_to_need,
        "<=",
        "7 days and no confirmation/ETA",
        triggered,
        "15" if triggered else "0",
        None,
        "VIS_CONFIRMATION_MISSING_NEAR_NEED",
    )


def _rpr_dat_01(risk_input: RiskInput) -> ComponentResult:
    unavailable = (
        risk_input.inventory_stale
        or risk_input.demand_unavailable
        or risk_input.inventory_available_quantity is None
    )
    urgent = 0 <= (risk_input.need_date - risk_input.as_of_date).days <= 7
    points = Decimal("15") if unavailable and urgent else Decimal("5") if unavailable else Decimal("0")
    return _component(
        "RPR-DAT-01",
        "visibility_data",
        "triggered" if unavailable else "available-not-triggered",
        {"inventory_stale": risk_input.inventory_stale, "demand_unavailable": risk_input.demand_unavailable},
        "is",
        "unavailable/stale",
        unavailable,
        str(points),
        "core inventory or demand evidence unavailable" if unavailable else None,
        "DAT_CORE_COVERAGE_UNAVAILABLE",
    )


def _rpr_sup_01(risk_input: RiskInput) -> ComponentResult:
    if risk_input.supplier_otif_rate is None or risk_input.supplier_observation_count is None:
        return _supplier_unavailable("RPR-SUP-01")
    if risk_input.supplier_observation_count < 20:
        return _supplier_unavailable("RPR-SUP-01", risk_input.supplier_observation_count)
    triggered = risk_input.supplier_otif_rate < Decimal("0.85")
    return _component(
        "RPR-SUP-01",
        "supplier",
        "triggered" if triggered else "available-not-triggered",
        risk_input.supplier_otif_rate,
        "<",
        "0.85 with n>=20",
        triggered,
        "15" if triggered else "0",
        None,
        "SUP_OTIF_BELOW_85",
    )


def _rpr_sup_02(risk_input: RiskInput) -> ComponentResult:
    if (
        risk_input.recent_otif_rate is None
        or risk_input.recent_observation_count is None
        or risk_input.prior_otif_rate is None
        or risk_input.prior_observation_count is None
        or risk_input.recent_observation_count < 8
        or risk_input.prior_observation_count < 12
    ):
        return _supplier_unavailable("RPR-SUP-02")
    deterioration = risk_input.prior_otif_rate - risk_input.recent_otif_rate
    triggered = deterioration >= Decimal("0.10") and risk_input.recent_otif_rate < Decimal("0.90")
    return _component(
        "RPR-SUP-02",
        "supplier",
        "triggered" if triggered else "available-not-triggered",
        deterioration,
        ">=",
        "0.10 and recent OTIF <0.90",
        triggered,
        "5" if triggered else "0",
        None,
        "SUP_OTIF_DETERIORATING",
    )


def _supplier_unavailable(component_code: str, observed: object | None = None) -> ComponentResult:
    explanation = "SUP_OTIF_BELOW_85" if component_code == "RPR-SUP-01" else "SUP_OTIF_DETERIORATING"
    return _component(
        component_code,
        "supplier",
        "unavailable",
        observed,
        ">=",
        "minimum supplier history",
        False,
        "0",
        "supplier history below approved observation threshold",
        explanation,
    )


def _rpr_con_01(risk_input: RiskInput) -> ComponentResult:
    if risk_input.criticality is None:
        return _component(
            "RPR-CON-01",
            "consequence",
            "invalid",
            None,
            "in",
            "service-critical, production-critical",
            False,
            "0",
            "criticality missing",
            "CON_ITEM_CRITICAL",
        )
    normalized = risk_input.criticality.lower().replace("_", "-")
    triggered = normalized in {"service-critical", "production-critical"}
    return _component(
        "RPR-CON-01",
        "consequence",
        "triggered" if triggered else "available-not-triggered",
        risk_input.criticality,
        "in",
        "service-critical, production-critical",
        triggered,
        "5" if triggered else "0",
        None,
        "CON_ITEM_CRITICAL",
    )


def _rpr_con_02(risk_input: RiskInput) -> ComponentResult:
    if risk_input.residual_value_aud is None:
        return _component(
            "RPR-CON-02",
            "consequence",
            "invalid",
            None,
            ">=",
            "AUD 50000",
            False,
            "0",
            "residual value unavailable",
            "CON_VALUE_HIGH",
        )
    points = Decimal("0")
    explanation = "CON_VALUE_HIGH"
    if Decimal("50000") <= risk_input.residual_value_aud < Decimal("150000"):
        points = Decimal("5")
    elif risk_input.residual_value_aud >= Decimal("150000"):
        points = Decimal("10")
        explanation = "CON_VALUE_VERY_HIGH"
    return _component(
        "RPR-CON-02",
        "consequence",
        "triggered" if points > 0 else "available-not-triggered",
        risk_input.residual_value_aud,
        ">=",
        "AUD 50000 / AUD 150000",
        points > 0,
        str(points),
        None,
        explanation,
    )


def _rpr_mit_01(risk_input: RiskInput) -> ComponentResult:
    return _component(
        "RPR-MIT-01",
        "mitigation",
        "triggered" if risk_input.mitigation_fully_approved else "available-not-triggered",
        risk_input.mitigation_fully_approved,
        "is",
        "approved full coverage",
        risk_input.mitigation_fully_approved,
        "-15" if risk_input.mitigation_fully_approved else "0",
        None,
        "MIT_FULL_COVERAGE_APPROVED",
    )


def _apply_family_caps(components: list[ComponentResult]) -> list[ComponentResult]:
    capped = list(components)
    for family, cap in FAMILY_CAPS.items():
        indexes = [index for index, component in enumerate(capped) if component.component_family == family]
        gross_total = sum((capped[index].gross_points for index in indexes), Decimal("0"))
        if gross_total <= cap:
            continue
        excess = gross_total - cap
        remaining_excess = excess
        for index in reversed(indexes):
            component = capped[index]
            if component.gross_points <= 0:
                continue
            adjustment = -min(remaining_excess, component.gross_points)
            capped[index] = ComponentResult(
                component.component_code,
                component.component_family,
                component.availability_status,
                component.observed_value,
                component.comparator,
                component.threshold_value,
                component.triggered,
                component.gross_points,
                adjustment,
                component.gross_points + adjustment,
                component.missing_signal_reason,
                _cap_code(family),
                component.input_lineage,
            )
            remaining_excess += adjustment
            if remaining_excess == 0:
                break
    return capped


def _cap_code(family: str) -> str:
    return {
        "delivery": "CAP_DELIVERY_40",
        "inventory": "CAP_INVENTORY_30",
        "visibility_data": "CAP_VISIBILITY_DATA_15",
        "supplier": "CAP_SUPPLIER_15",
        "consequence": "CAP_CONSEQUENCE_15",
    }[family]


def _opening_basis(risk_input: RiskInput, score: Decimal, missing_signals: tuple[str, ...]) -> str | None:
    days_to_need = (risk_input.need_date - risk_input.as_of_date).days
    controlled_order = _is_controlled_order(risk_input)
    if score >= Decimal("50"):
        return "OPEN_SCORE"
    if 0 <= days_to_need <= 7 and controlled_order and missing_signals:
        return "OPEN_CRITICAL_DATA_GAP"
    if Decimal("30") <= score < Decimal("50") and 0 <= days_to_need <= 14 and controlled_order:
        return "OPEN_CONTROLLED_ORDER"
    return None


def _is_controlled_order(risk_input: RiskInput) -> bool:
    criticality = (risk_input.criticality or "").lower().replace("_", "-")
    high_value = risk_input.residual_value_aud is not None and risk_input.residual_value_aud >= Decimal("100000")
    return criticality in {"service-critical", "production-critical"} or high_value


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
