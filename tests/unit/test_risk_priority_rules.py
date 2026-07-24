"""Unit tests for deterministic risk-priority rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from scecs.risk.rules import RiskInput, ScoreResult, score_band, score_candidate


def test_deterministic_scoring_and_component_arithmetic() -> None:
    """Identical inputs should produce identical score evidence."""

    risk_input = _risk_input()
    first = score_candidate(risk_input)
    second = score_candidate(risk_input)

    assert first == second
    assert first.score == Decimal("100.00")
    assert first.band == "critical"
    assert first.primary_disposition == "opening-eligible-no-workflow"
    assert sum(component.applied_points for component in first.contributions) == Decimal("100")


def test_family_caps_preserve_gross_and_cap_adjustment() -> None:
    """Delivery and supplier gross points should be visible even when capped."""

    result = score_candidate(_risk_input())
    delivery = [row for row in result.contributions if row.component_family == "delivery"]
    supplier = [row for row in result.contributions if row.component_family == "supplier"]

    assert sum(row.gross_points for row in delivery) == Decimal("60")
    assert sum(row.applied_points for row in delivery) == Decimal("40")
    assert sum(row.cap_adjustment for row in delivery) == Decimal("-20")
    assert sum(row.gross_points for row in supplier) == Decimal("20")
    assert sum(row.applied_points for row in supplier) == Decimal("15")


def test_missing_data_is_qualified_not_zero_risk() -> None:
    """Unavailable core evidence should be explicit and add data uncertainty when urgent."""

    risk_input = replace(
        _risk_input(),
        as_of_date=date(2026, 6, 28),
        need_date=date(2026, 6, 30),
        confirmed_date=None,
        expected_receipt_date=None,
        inventory_available_quantity=None,
        inventory_stale=True,
        demand_unavailable=True,
        supplier_otif_rate=None,
        supplier_observation_count=None,
        recent_otif_rate=None,
        recent_observation_count=None,
        prior_otif_rate=None,
        prior_observation_count=None,
    )

    result = score_candidate(risk_input)

    assert result.score_confidence == "qualified"
    assert "INV_STOCKOUT_BEFORE_RECEIPT" in result.missing_signals
    assert result.score > Decimal("0")
    assert any(
        row.component_code == "RPR-DAT-01" and row.gross_points == Decimal("15")
        for row in result.contributions
    )
    assert result.opening_basis == "OPEN_CRITICAL_DATA_GAP"


def test_partial_receipts_reduce_residual_exposure() -> None:
    """Residual value should reduce when receipts reduce residual quantity."""

    high_residual = score_candidate(
        _value_only_input(residual_quantity=Decimal("100"), residual_value=Decimal("160000"))
    )
    low_residual = score_candidate(_value_only_input(residual_quantity=Decimal("20"), residual_value=Decimal("32000")))

    assert _points(high_residual, "RPR-CON-02") == Decimal("10")
    assert _points(low_residual, "RPR-CON-02") == Decimal("0")
    assert low_residual.score < high_residual.score


def test_score_bands_are_inclusive_at_boundaries() -> None:
    """Governed score bands should follow the frozen boundary table."""

    assert score_band(Decimal("29")) == "monitor"
    assert score_band(Decimal("30")) == "medium"
    assert score_band(Decimal("49")) == "medium"
    assert score_band(Decimal("50")) == "high"
    assert score_band(Decimal("69")) == "high"
    assert score_band(Decimal("70")) == "critical"
    assert score_band(Decimal("100")) == "critical"


def test_opening_rules_and_active_episode_linking() -> None:
    """Opening eligibility should be analytical and active episodes should be linked."""

    medium_controlled = replace(
        _risk_input(),
        as_of_date=date(2026, 6, 20),
        need_date=date(2026, 6, 30),
        confirmed_date=date(2026, 6, 30),
        expected_receipt_date=date(2026, 6, 30),
        inventory_available_quantity=Decimal("1000"),
        demand_until_receipt=Decimal("0"),
        supplier_otif_rate=Decimal("0.95"),
        supplier_observation_count=30,
        recent_otif_rate=Decimal("0.95"),
        recent_observation_count=10,
        prior_otif_rate=Decimal("0.95"),
        prior_observation_count=20,
        residual_value_aud=Decimal("120000"),
        lead_time_baseline_days=Decimal("100"),
    )
    result = score_candidate(medium_controlled)
    linked = score_candidate(medium_controlled, linked_active_episode=True)

    assert result.score == Decimal("10.00")
    assert not result.opening_eligible
    assert result.primary_disposition == "below-opening-threshold"
    assert linked.primary_disposition == "linked-existing-active-episode"


def _points(result: ScoreResult, code: str) -> Decimal:
    return next(row.applied_points for row in result.contributions if row.component_code == code)


def _risk_input(
    *,
    residual_quantity: Decimal = Decimal("100"),
    residual_value: Decimal = Decimal("175000"),
) -> RiskInput:
    return RiskInput(
        po_line_id="00000000-0000-0000-0000-000000000001",
        site_id="00000000-0000-0000-0000-000000000002",
        supplier_id="00000000-0000-0000-0000-000000000003",
        product_id="00000000-0000-0000-0000-000000000004",
        as_of_date=date(2026, 6, 30),
        order_date=date(2026, 6, 1),
        need_date=date(2026, 6, 24),
        confirmed_date=date(2026, 6, 20),
        expected_receipt_date=date(2026, 6, 30),
        residual_quantity=residual_quantity,
        base_quantity=Decimal("100"),
        residual_value_aud=residual_value,
        criticality="production-critical",
        inventory_available_quantity=Decimal("0"),
        safety_stock_quantity=Decimal("10"),
        demand_until_receipt=Decimal("20"),
        inventory_stale=False,
        demand_unavailable=False,
        supplier_otif_rate=Decimal("0.80"),
        supplier_observation_count=30,
        recent_otif_rate=Decimal("0.70"),
        recent_observation_count=10,
        prior_otif_rate=Decimal("0.85"),
        prior_observation_count=20,
        lead_time_baseline_days=Decimal("20"),
    )


def _value_only_input(*, residual_quantity: Decimal, residual_value: Decimal) -> RiskInput:
    return replace(
        _risk_input(residual_quantity=residual_quantity, residual_value=residual_value),
        confirmed_date=date(2026, 7, 1),
        expected_receipt_date=date(2026, 6, 24),
        inventory_available_quantity=Decimal("1000"),
        demand_until_receipt=Decimal("0"),
        supplier_otif_rate=Decimal("0.95"),
        supplier_observation_count=30,
        recent_otif_rate=Decimal("0.95"),
        recent_observation_count=10,
        prior_otif_rate=Decimal("0.95"),
        prior_observation_count=20,
        lead_time_baseline_days=Decimal("100"),
    )
