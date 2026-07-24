"""Read-side view models for the Streamlit operational MVP."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class UserOption:
    """Active simulated user option."""

    user_id: uuid.UUID
    user_code: str
    display_name: str
    role_classification: str

    @property
    def label(self) -> str:
        """Human-friendly label for simulated role switching."""

        return f"{self.user_code} - {self.display_name} ({self.role_classification})"


@dataclass(frozen=True)
class ExceptionQueueRow:
    """Operational exception row for queue and control-tower lists."""

    episode_id: uuid.UUID
    exception_reference: str
    site_code: str
    supplier_name: str
    po_line: str
    product: str
    state: str
    owner: str | None
    owner_user_id: uuid.UUID | None
    score: Decimal | None
    band: str | None
    residual_quantity: Decimal | None
    residual_value: Decimal | None
    need_date: date | None
    opened_at: datetime
    age_days: int
    sla_status: str


@dataclass(frozen=True)
class CandidateRow:
    """Opening-eligible analytical candidate row."""

    candidate_id: uuid.UUID
    site_code: str
    supplier_name: str
    po_line: str
    product: str
    score: Decimal
    band: str
    residual_quantity: Decimal | None
    residual_value: Decimal | None
    need_date: date | None


@dataclass(frozen=True)
class DistributionRow:
    """Name/count pair for compact dashboard charts."""

    label: str
    count: int


@dataclass(frozen=True)
class PipelineStatus:
    """Latest pipeline and publication status."""

    latest_pipeline_reference: str | None
    latest_pipeline_type: str | None
    latest_pipeline_status: str | None
    latest_pipeline_finished_at: datetime | None
    latest_publication_reference: str | None
    latest_publication_status: str | None
    latest_publication_at: datetime | None


@dataclass(frozen=True)
class ControlTowerSummary:
    """KPI and chart data for the control tower."""

    active_exceptions: int
    critical_high_exceptions: int
    unassigned_exceptions: int
    sla_breached_conditions: int
    opening_eligible_candidates: int
    state_distribution: tuple[DistributionRow, ...]
    risk_band_distribution: tuple[DistributionRow, ...]
    highest_priority: tuple[ExceptionQueueRow, ...]
    pipeline_status: PipelineStatus


@dataclass(frozen=True)
class RiskContributionRow:
    """Risk component contribution displayed in exception detail."""

    component_code: str
    component_family: str
    availability_status: str
    observed_value: str | None
    threshold_value: str | None
    gross_points: Decimal
    cap_adjustment: Decimal
    applied_points: Decimal
    missing_signal_reason: str | None
    explanation_code: str


@dataclass(frozen=True)
class AuditEventRow:
    """Immutable workflow event displayed in audit history."""

    sequence: int
    event_type: str
    effective_at: datetime
    actor: str | None
    reason_code: str | None
    reason_text: str | None
    before_payload: dict[str, object] | None
    after_payload: dict[str, object] | None


@dataclass(frozen=True)
class DetailActionRow:
    """Action, note, or monitoring evidence displayed in detail."""

    sequence: int
    category: str
    status: str
    owner: str | None
    payload: dict[str, object]


@dataclass(frozen=True)
class OwnershipHistoryRow:
    """Assignment or reassignment event displayed in detail."""

    sequence: int
    previous_owner: str | None
    new_owner: str | None
    effective_from: datetime


@dataclass(frozen=True)
class ApprovalRow:
    """Approval request and decision display row."""

    request_type: str
    requester: str
    approver: str | None
    outcome: str | None
    reason: str
    expires_at: datetime | None


@dataclass(frozen=True)
class SuppressionRow:
    """Approved suppression display row."""

    reason_code: str
    prior_state: str
    starts_at: datetime
    expires_at: datetime
    evidence_reference: str | None


@dataclass(frozen=True)
class ExceptionDetail:
    """Full detail view for one exception episode."""

    summary: ExceptionQueueRow
    missing_signals: dict[str, object]
    risk_contributions: tuple[RiskContributionRow, ...]
    ownership_history: tuple[OwnershipHistoryRow, ...]
    actions: tuple[DetailActionRow, ...]
    approvals: tuple[ApprovalRow, ...]
    suppressions: tuple[SuppressionRow, ...]
    audit_events: tuple[AuditEventRow, ...]


ViewModelRow = (
    DistributionRow
    | RiskContributionRow
    | OwnershipHistoryRow
    | DetailActionRow
    | ApprovalRow
    | SuppressionRow
    | AuditEventRow
)


def rows_to_records(rows: tuple[ViewModelRow, ...]) -> list[dict[str, object]]:
    """Convert dataclass rows into Streamlit-friendly records."""

    records: list[dict[str, object]] = []
    for row in rows:
        records.append(asdict(row))
    return records
