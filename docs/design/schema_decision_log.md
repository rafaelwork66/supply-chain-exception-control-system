# Schema Decision Log

## SDL-001: Active Episode Definition

Decision: active episode uniqueness is enforced by `closed_at IS NULL`, not by `current_state <> 'closed'`.

Reason: `current_state` and `closed_at` are rebuildable projections from immutable state-event history. `closed_at IS NULL` is the clearer database predicate for the active unique index.

Database control: `uq_exception_episodes_active_line_site` and `closed_state_projection_consistency`.

## SDL-002: Candidate Contribution Arithmetic

Decision: `candidate_risk_contributions` stores `gross_points`, `cap_adjustment`, and `applied_points`.

Reason: the database can preserve contribution arithmetic without implementing the scoring engine.

Database control: `applied_points = gross_points + cap_adjustment`.

## SDL-003: UOM Conversion Factors

Decision: `uom_conversions.conversion_factor` is a positive numeric value that must be mathematically integral.

Reason: the synthetic MVP contract uses whole-number EA, CASE, and PALLET conversions. PostgreSQL can coerce fractional input before an integer column check sees it, so the schema uses a numeric column with an explicit integrality check to reject zero, negative, and fractional factors reliably.

Database control: `conversion_factor > 0 and conversion_factor = trunc(conversion_factor)`.

## SDL-004: Material Approval Independence

Decision: material approval self-approval is blocked by a PostgreSQL constraint trigger.

Material request types: `suppression`, `resolution`, `severity_override`, `material_recurrence`, and `closure`.

Reason: requester and approver are stored in separate tables, so a row-level check constraint is insufficient.

Database control: `trg_material_approval_independence`.

## SDL-005: Material Recurrence Successors

Decision: a material-recurrence successor requires a predecessor episode that is formally Closed and has `closed_at` populated.

Reason: recurrence must not be used to bypass the active-episode lifecycle.

Database controls: `trg_successor_predecessor_closed`, `trg_material_relationship_predecessor_closed`, and non-self relationship checks.

## SDL-006: Notification Structure

Decision: `notification_events` is included as an inactive audit structure.

Reason: the physical schema should preserve the future notification event shape without implementing sending, providers, routing, or notification business logic.

Database control: structural columns, delivery-status check, attempt-number check, and idempotency uniqueness.

## SDL-007: Event Idempotency

Decision: immutable event envelopes carry explicit `idempotency_key` values unique within each episode.

Reason: `correlation_id` is trace metadata and must not be overloaded as an idempotency control.

Database control: unique constraint on `(episode_id, idempotency_key)`.
