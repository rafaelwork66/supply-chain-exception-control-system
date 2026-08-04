# Power BI Reporting Layer Design

## Status

Design only. No SQL implementation is authorised yet.

Repository commit inspected: `c4eb503e191c61984421f11c13756c4b819a53a4`.

## Scope

This document designs a read-only PostgreSQL reporting layer for the Power BI management report.

The reporting layer must not modify:

- Streamlit application behavior
- operational lifecycle rules
- risk scoring rules
- ingestion logic
- approval controls
- suppression controls
- existing operational table contracts

All reporting objects should be created in a dedicated PostgreSQL schema:

```text
reporting
```

Example object names:

```text
reporting.rpt_exception_summary
reporting.rpt_exception_events
reporting.dim_supplier
```

## Governing Definitions

### Active Operational Exceptions

For management workload reporting, Active Operational Exceptions are only episodes in these states:

- `open`
- `assigned`
- `investigating`
- `action_agreed`
- `monitoring`
- `resolved`

Excluded from Active Operational Exceptions:

- `closed`
- `suppressed`

The reporting layer must expose separate flags:

| Flag | Definition |
|---|---|
| `is_not_closed` | `closed_at IS NULL` |
| `is_active_operational` | `current_state IN ('open','assigned','investigating','action_agreed','monitoring','resolved')` |
| `is_suppressed` | `current_state = 'suppressed'` |
| `is_closed` | `current_state = 'closed' AND closed_at IS NOT NULL` |

Important: `resolved` remains active until `closed`. `suppressed` remains separate from `closed`.

### Candidate Risk

Candidate Risk is analytical. It is not a workflow state.

Candidate reporting must use governed fields from `candidate_risk_evaluations`:

- `eligibility_status`
- `disposition`
- `linked_episode_id`
- `score`
- `calculated_severity`
- `score_confidence`

A High or Critical score must not automatically be treated as workflow eligibility.

### Events and Conditions

These are not states:

- reopened
- escalation
- SLA breach

Reopened is currently derivable from `exception_event_envelopes.event_type = 'reopened'` or `exception_state_events.transition_reason = 'reopened'`.

Formal SLA breach event reporting is not available in the MVP because `sla_events.sla_event_type` is a free string with no governed enum/check constraint in the inspected schema. MVP SLA reporting should therefore use:

- SLA obligation coverage
- overdue unsatisfied obligations
- known SLA event counts by stored `sla_event_type`

No wildcard matching such as `ILIKE '%breach%'` should be used.

## 1. Source-Schema Assessment

| Area | Existing tables | Grain | Keys | Timestamps |
|---|---|---|---|---|
| Exception episodes | `exception_episodes` | One exception episode per PO line, site, episode sequence | `id`, `po_line_id`, `site_id`, `episode_sequence` | `opened_at`, `closed_at` |
| Lifecycle events | `exception_event_envelopes`, `exception_state_events` | One event envelope; optional typed state event | `id`, `episode_id`, `event_sequence`, `event_envelope_id` | `effective_at`, `recorded_at` |
| Ownership | `ownership_events` | One assignment/reassignment event | `id`, `episode_id`, `ownership_sequence` | `effective_from`, `effective_to` |
| Actions | `exception_actions` | One operational action/note/agreement | `id`, `episode_id`, `action_sequence` | `due_at` |
| SLA | `sla_obligations`, `sla_events` | One SLA obligation; one SLA event per obligation sequence | `id`, `episode_id`, `sla_type`, `obligation_sequence` | `starts_at`, `original_due_at`, `satisfied_at`, `cancelled_at`, `event_at` |
| Approvals | `approval_requests`, `approval_decisions` | One request; zero or more decision rows | `id`, `approval_request_id`, `decision_role` | `recorded_at`, `expires_at` |
| Suppressions | `suppression_controls` | One approved suppression interval | `id`, `episode_id`, `approval_request_id` | `starts_at`, `expires_at`, `review_at` |
| Resolution | `resolution_records` | One resolution assertion per episode sequence | `id`, `episode_id`, `resolution_sequence` | `recorded_at`, `outcome_date`, `withdrawn_at` |
| Candidate risk | `candidate_risk_evaluations` | One candidate evaluation per run, PO line, site | `id`, `pipeline_run_id`, `po_line_id`, `site_id` | `evaluated_at` |
| Risk components | `candidate_risk_contributions` | One score component per candidate evaluation | `id`, `candidate_evaluation_id`, `component_code` | Inherits candidate timestamp |
| Purchase orders | `purchase_orders`, `purchase_order_versions`, `purchase_order_lines`, `purchase_order_line_versions`, `purchase_order_line_aliases` | Durable PO/line identity with versioned facts | `purchase_order_id`, `po_line_id` | `order_date`, `need_date`, `effective_at` |
| Supply observations | `delivery_schedules`, `supplier_commitment_observations`, `receipt_transactions`, `receipt_allocations` | Schedule, commitment, receipt, allocation | PO line, schedule and receipt IDs | `expected_date`, `confirmed_date`, `committed_date`, `posted_at`, `observed_at` |
| Inventory/demand | `inventory_snapshots`, `demand_requirements`, `product_site_inventory_policies` | Product-site observations and policies | `product_id`, `site_id` | `snapshot_at`, `required_date`, `effective_from` |
| Supplier performance | `supplier_performance_snapshots` | Supplier/site measurement window | `supplier_id`, `site_id`, date window | `window_start`, `window_end`, `as_of_date` |
| Pipeline control | `pipeline_runs`, `source_loads`, `pipeline_step_results`, `reconciliation_results`, `rejected_records`, `analytics_publications` | Run, load, step, reconciliation, rejection, publication | Pipeline and source load IDs | `started_at`, `finished_at`, `rejected_at`, `published_at` |
| Reference data | `sites`, `suppliers`, `supplier_versions`, `products`, `product_versions`, `users`, `rule_versions`, `rule_component_definitions`, `calendar_versions`, `source_systems` | Durable or effective-dated dimensions | Durable IDs | `active_from`, `active_to`, `effective_from`, `effective_to` |

## Financial Exposure Source Verification

The following fields do exist in the inspected schema:

| Field | Source table | Source column | Meaning |
|---|---|---|---|
| Unit price | `purchase_order_line_versions` | `unit_price_aud` | Unit price in AUD |
| Line value | `purchase_order_line_versions` | `line_value_aud` | Line value in AUD |
| Header currency | `purchase_order_versions` | `currency_code` | PO header currency code |
| Ordered quantity | `purchase_order_line_versions` | `ordered_quantity` | Quantity in order UOM |
| Base quantity | `purchase_order_line_versions` | `base_quantity` | Quantity converted to product base UOM where available |
| Order UOM | `purchase_order_line_versions` | `order_uom` | Source order unit of measure |
| Received quantity | `receipt_allocations` joined to `receipt_transactions` | `allocated_base_quantity` | Allocated receipt quantity in base UOM |

MVP residual exposure calculation:

```text
latest_quantity =
COALESCE(purchase_order_line_versions.base_quantity,
         purchase_order_line_versions.ordered_quantity)

received_base_quantity =
SUM(receipt_allocations.allocated_base_quantity)
joined through receipt_transactions by po_line_id

residual_base_quantity =
GREATEST(latest_quantity - COALESCE(received_base_quantity, 0), 0)

residual_value_aud =
CASE
  WHEN line_value_aud IS NOT NULL AND latest_quantity > 0
    THEN line_value_aud * residual_base_quantity / latest_quantity
  WHEN unit_price_aud IS NOT NULL
    THEN unit_price_aud * residual_base_quantity
  ELSE NULL
END
```

Currency treatment:

- `unit_price_aud` and `line_value_aud` are explicitly AUD fields.
- `purchase_order_versions.currency_code` should still be exposed for transparency.
- No currency conversion is implemented in the MVP reporting layer.

UOM treatment:

- Prefer `base_quantity` when available.
- Fall back to `ordered_quantity` only where base quantity is NULL.
- `receipt_allocations.allocated_base_quantity` is already base quantity.
- If quantity basis is mixed because `base_quantity` is missing, expose `quantity_basis = 'ordered_quantity_fallback'`.

Null behavior:

- Missing `unit_price_aud` and `line_value_aud` means `residual_value_aud` is NULL.
- NULL exposure must not be converted to zero.
- Expose `exposure_value_available`.

## Current/Latest Version Handling

For the MVP, reporting views use current/latest descriptors:

- latest `purchase_order_versions` by highest `amendment_version`
- latest `purchase_order_line_versions` by highest `amendment_version`
- latest/current `supplier_versions` by effective interval, falling back to latest `effective_from`
- latest/current `product_versions` by effective interval, falling back to latest `effective_from`

This supports current-state management reporting.

Limitation: historical trends will use current/latest descriptors, not fully as-of event-time attributes. As-of-event descriptive reporting is a future enhancement.

## 2. Metric Catalogue

| Metric | MVP definition | Notes |
|---|---|---|
| Active Operational Exceptions | Count episodes where `current_state IN ('open','assigned','investigating','action_agreed','monitoring','resolved')` | Excludes Closed and Suppressed |
| Not Closed Exceptions | Count episodes where `closed_at IS NULL` | Includes Suppressed |
| Critical Exceptions | Count episodes where `effective_severity = 'critical'` | Usually filtered to active operational |
| Active Exposure | Sum `residual_value_aud` for active operational exceptions | NULL values excluded from sum and counted separately |
| Unassigned Exceptions | Active operational exceptions where `current_owner_user_id IS NULL` | Suppressed excluded |
| Exception Age | Refresh-time or DAX calculation from `opened_at` to refresh/as-of timestamp | Avoid stale hidden `NOW()` values |
| Resolution Time | First resolved transition timestamp minus `opened_at` | Resolution is not closure |
| Closure Time | `closed_at - opened_at` | Closed episodes only |
| Reopened Exceptions | Episodes with reopened event/transition | Event, not state |
| Reopen Rate | Reopened episodes / episodes resolved at least once | Use distinct episode counts |
| Suppressed Exceptions | Episodes where `current_state = 'suppressed'` plus suppression interval facts | Separate KPI |
| Approval Requests | Distinct `approval_request_id` count | Avoid decision duplication |
| Approval Decisions | Distinct `approval_decision_id` count | Decision grain |
| Pending Approval Requests | Requests with no decision rows | Derived in `rpt_approvals` |
| Self-Approval Violations | Requester equals approver | Expected zero |
| Candidate Risks Not Opened | `disposition = 'opening-eligible-no-workflow' AND linked_episode_id IS NULL` | Do not infer from severity |
| Risk Contributions | Sum/average `gross_points`, `cap_adjustment`, `applied_points` | Preserve missing signal status |
| Pipeline Success | Runs where `status = 'success'` / all completed runs | Keep failed/cancelled visible |
| SLA Coverage | Episodes with one or more SLA obligations | No obligation means not tracked |
| Overdue Unsatisfied SLA | Obligations where `satisfied_at IS NULL`, `cancelled_at IS NULL`, and `original_due_at < report_as_of` | Condition, not formal breach event |
| Formal SLA Breach Events | Not available in MVP | No governed breach event code exists |

## 3. Proposed Reporting Views

## `reporting.rpt_exception_summary`

Grain: one row per exception episode.

Purpose: episode-level accumulating snapshot and primary anchor for Power BI exception reporting.

Mapping:

| Reporting column | Source table | Source column/expression | Derivation | Null handling |
|---|---|---|---|---|
| `episode_id` | `exception_episodes` | `id` | Direct | Not null |
| `po_line_id` | `exception_episodes` | `po_line_id` | Direct | Not null |
| `purchase_order_id` | `purchase_order_lines` | `purchase_order_id` | Join from PO line | Not null |
| `po_number` | `purchase_orders` | `po_number` | Join from PO | Not null |
| `source_po_number` | `purchase_order_line_aliases` | current alias | Use active alias where `valid_to IS NULL` | NULL if no alias |
| `source_line_number` | `purchase_order_line_aliases` | current alias | Use active alias where `valid_to IS NULL` | NULL if no alias |
| `site_id` | `exception_episodes` | `site_id` | Direct | Not null |
| `supplier_id` | latest `purchase_order_versions` | `supplier_id` | Latest header version | Not null if version exists |
| `product_id` | latest `purchase_order_line_versions` | `product_id` | Latest line version | Not null if version exists |
| `current_state` | `exception_episodes` | `current_state` | Direct | Not null |
| `is_not_closed` | `exception_episodes` | `closed_at IS NULL` | Boolean | Not null |
| `is_active_operational` | `exception_episodes` | state list | Open through Resolved only | Not null |
| `is_suppressed` | `exception_episodes` | `current_state = 'suppressed'` | Boolean | Not null |
| `is_closed` | `exception_episodes` | `current_state = 'closed' AND closed_at IS NOT NULL` | Boolean | Not null |
| `calculated_severity` | `exception_episodes` | `calculated_severity` | Direct | Not null |
| `effective_severity` | `exception_episodes` | `effective_severity` | Direct | Not null |
| `opened_at` | `exception_episodes` | `opened_at` | Direct | Not null |
| `closed_at` | `exception_episodes` | `closed_at` | Direct | NULL unless Closed |
| `current_owner_user_id` | `exception_episodes` | `current_owner_user_id` | Direct | NULL means unassigned |
| `opening_candidate_id` | `exception_episodes` | `opening_candidate_id` | Direct | Not null |
| `current_candidate_id` | `exception_episodes` | `current_candidate_id` | Direct | NULL if no current candidate |
| `opening_run_id` | `exception_episodes` | `opening_run_id` | Direct | Not null |
| `current_score` | `candidate_risk_evaluations` | `score` | Join to current candidate | NULL if no current candidate |
| `current_score_confidence` | `candidate_risk_evaluations` | `score_confidence` | Join to current candidate | NULL if no current candidate |
| `current_candidate_disposition` | `candidate_risk_evaluations` | `disposition` | Join to current candidate | NULL if no current candidate |
| `ordered_quantity` | latest `purchase_order_line_versions` | `ordered_quantity` | Latest line version | NULL if no version |
| `base_quantity` | latest `purchase_order_line_versions` | `base_quantity` | Latest line version | NULL allowed |
| `quantity_basis` | expression | base vs ordered fallback | `base_quantity` or `ordered_quantity_fallback` | Not null if line version exists |
| `received_base_quantity` | receipts aggregate | `SUM(allocated_base_quantity)` | By PO line | Zero if no receipts |
| `residual_base_quantity` | expression | see exposure formula | Non-negative | NULL if no quantity source |
| `unit_price_aud` | latest `purchase_order_line_versions` | `unit_price_aud` | Direct | NULL allowed |
| `line_value_aud` | latest `purchase_order_line_versions` | `line_value_aud` | Direct | NULL allowed |
| `currency_code` | latest `purchase_order_versions` | `currency_code` | Direct | NULL if no version |
| `residual_value_aud` | expression | see exposure formula | AUD only | NULL if no value source |
| `exposure_value_available` | expression | `residual_value_aud IS NOT NULL` | Boolean | Not null |
| `need_date` | latest `purchase_order_line_versions` | `need_date` | Direct | NULL if no version |
| `order_date` | latest `purchase_order_versions` | `order_date` | Direct | NULL if no version |
| `line_status` | latest `purchase_order_line_versions` | `line_status` | Direct | NULL if no version |
| `order_status` | latest `purchase_order_versions` | `order_status` | Direct | NULL if no version |
| `first_resolved_at` | state events aggregate | earliest `to_state = 'resolved'` event | Pre-aggregate by episode | NULL if never resolved |
| `first_closed_at` | `exception_episodes` | `closed_at` | Direct | NULL unless Closed |
| `resolved_transition_count` | state events aggregate | count `to_state = 'resolved'` | Pre-aggregate | Zero if none |
| `reopen_count` | event aggregate | count reopened event/transition | Pre-aggregate | Zero if none |
| `has_reopened` | event aggregate | `reopen_count > 0` | Boolean | Not null |
| `approval_request_count` | approvals aggregate | distinct requests | Pre-aggregate | Zero if none |
| `suppression_count` | suppressions aggregate | count controls | Pre-aggregate | Zero if none |
| `active_suppression_expires_at` | suppression aggregate | max current interval expiry | Based on report refresh/as-of | NULL if none |
| `sla_obligation_count` | SLA aggregate | count obligations | Pre-aggregate | Zero if none |
| `has_sla_coverage` | SLA aggregate | count > 0 | Boolean | Not null |
| `overdue_unsatisfied_sla_count` | SLA aggregate | due before report as-of and unsatisfied | No formal breach code | Zero if none |

Time-relative fields:

- `age_days`, `age_hours`, `is_currently_suppressed`, and overdue SLA should be calculated using a Power BI refresh timestamp or DAX report-as-of measure.
- PostgreSQL views may expose raw timestamps and due dates.
- Avoid hidden `NOW()` logic unless a controlled `report_as_of` parameter/table is introduced.

Duplicate prevention:

- Aggregate events, receipts, approvals, suppressions and SLA before joining.
- Latest version subqueries must return one row per durable key.
- Validate one row per `episode_id`.

Validation tests:

- Row count equals `exception_episodes`.
- No duplicate `episode_id`.
- Active operational count excludes `suppressed` and `closed`.
- Suppressed count equals episodes with `current_state = 'suppressed'`.
- Residual quantity is never negative.
- Exposure NULL count is reported.

## `reporting.rpt_exception_events`

Grain: one row per event envelope.

Mapping:

| Reporting column | Source table | Source column/expression | Derivation | Null handling |
|---|---|---|---|---|
| `event_id` | `exception_event_envelopes` | `id` | Direct | Not null |
| `episode_id` | `exception_event_envelopes` | `episode_id` | Direct | Not null |
| `event_sequence` | `exception_event_envelopes` | `event_sequence` | Direct | Not null |
| `event_type` | `exception_event_envelopes` | `event_type` | Direct | Not null |
| `effective_at` | `exception_event_envelopes` | `effective_at` | Direct | Not null |
| `recorded_at` | `exception_event_envelopes` | `recorded_at` | From mixin | Not null |
| `actor_user_id` | `exception_event_envelopes` | `actor_user_id` | Direct | NULL for system/unknown |
| `actor_type` | `exception_event_envelopes` | `actor_type` | Direct | Not null |
| `from_state` | `exception_state_events` | `from_state` | Left join | NULL for non-state events |
| `to_state` | `exception_state_events` | `to_state` | Left join | NULL for non-state events |
| `transition_reason` | `exception_state_events` | `transition_reason` | Left join | NULL for non-state events |
| `authority` | `exception_state_events` | `authority` | Left join | NULL for non-state events |
| `is_reopen_event` | expression | event or transition reason | Exact equality only | Not null |
| `reason_code` | `exception_event_envelopes` | `reason_code` | Direct | NULL allowed |
| `reason_text` | `exception_event_envelopes` | `reason_text` | Direct | NULL allowed |
| `pipeline_run_id` | `exception_event_envelopes` | `pipeline_run_id` | Direct | NULL allowed |
| `rule_version_id` | `exception_event_envelopes` | `rule_version_id` | Direct | NULL allowed |
| `calendar_version_id` | `exception_event_envelopes` | `calendar_version_id` | Direct | NULL allowed |
| `correlation_id` | `exception_event_envelopes` | `correlation_id` | Direct | NULL allowed |
| `causation_event_id` | `exception_event_envelopes` | `causation_event_id` | Direct | NULL allowed |
| `has_before_payload` | `exception_event_envelopes` | `before_payload IS NOT NULL` | Boolean only | Not null |
| `has_after_payload` | `exception_event_envelopes` | `after_payload IS NOT NULL` | Boolean only | Not null |

MVP exclusion:

- Do not expose full `before_payload` or `after_payload` to Power BI unless specifically required for drill-through governance. Use presence flags by default.

Validation tests:

- Row count equals `exception_event_envelopes`.
- No duplicate `event_id`.
- `(episode_id, event_sequence)` is unique.
- Reopen count matches exact governed event values only.

## `reporting.rpt_risk_assessments`

Grain: one row per candidate risk evaluation.

Mapping:

| Reporting column | Source table | Source column/expression | Derivation | Null handling |
|---|---|---|---|---|
| `candidate_evaluation_id` | `candidate_risk_evaluations` | `id` | Direct | Not null |
| `pipeline_run_id` | `candidate_risk_evaluations` | `pipeline_run_id` | Direct | Not null |
| `run_reference` | `pipeline_runs` | `run_reference` | Join | Not null if run exists |
| `evaluated_at` | `candidate_risk_evaluations` | `evaluated_at` | Direct | Not null |
| `po_line_id` | `candidate_risk_evaluations` | `po_line_id` | Direct | Not null |
| `site_id` | `candidate_risk_evaluations` | `site_id` | Direct | Not null |
| `rule_version_id` | `candidate_risk_evaluations` | `rule_version_id` | Direct | Not null |
| `eligibility_status` | `candidate_risk_evaluations` | `eligibility_status` | Direct | Not null |
| `score` | `candidate_risk_evaluations` | `score` | Direct | Not null |
| `calculated_severity` | `candidate_risk_evaluations` | `calculated_severity` | Direct | Not null |
| `score_confidence` | `candidate_risk_evaluations` | `score_confidence` | Direct | Not null |
| `disposition` | `candidate_risk_evaluations` | `disposition` | Direct | Not null |
| `linked_episode_id` | `candidate_risk_evaluations` | `linked_episode_id` | Direct | NULL if not linked |
| `candidate_opened_or_linked_episode` | expression | linked episode or opened/linked disposition | Boolean | Not null |
| `is_candidate_not_opened` | expression | `disposition = 'opening-eligible-no-workflow' AND linked_episode_id IS NULL` | Controlled list | Not null |
| `has_missing_signals` | expression | missing payload/component aggregate | Boolean | Not null |
| `explanation_summary` | `candidate_risk_evaluations` | `explanation_summary` | Direct | NULL allowed |
| `missing_signal_payload` | `candidate_risk_evaluations` | `missing_signal_payload` | Optional controlled JSON | Empty JSON allowed |
| `input_fingerprint` | `candidate_risk_evaluations` | `input_fingerprint` | Direct | Not null |

Permitted candidate dispositions:

- `below-opening-threshold`
- `opened-new-episode`
- `linked-existing-active-episode`
- `opening-eligible-no-workflow`
- `suppressed-by-existing-control`
- `ineligible-after-validation`
- `manual-review-data-insufficient`
- `scoring-error`

Validation tests:

- Row count equals `candidate_risk_evaluations`.
- Unique `(pipeline_run_id, po_line_id, site_id)`.
- Candidate-not-opened uses disposition and linked episode only, not severity.

## `reporting.rpt_risk_components`

Grain: one row per candidate risk contribution.

Mapping:

| Reporting column | Source table | Source column/expression | Derivation | Null handling |
|---|---|---|---|---|
| `risk_component_contribution_id` | `candidate_risk_contributions` | `id` | Direct | Not null |
| `candidate_evaluation_id` | `candidate_risk_contributions` | `candidate_evaluation_id` | Direct | Not null |
| `pipeline_run_id` | `candidate_risk_evaluations` | `pipeline_run_id` | Join | Not null |
| `evaluated_at` | `candidate_risk_evaluations` | `evaluated_at` | Join | Not null |
| `rule_component_id` | `candidate_risk_contributions` | `rule_component_id` | Direct | NULL allowed |
| `component_code` | `candidate_risk_contributions` | `component_code` | Direct | Not null |
| `component_family` | `candidate_risk_contributions` | `component_family` | Direct | Not null |
| `availability_status` | `candidate_risk_contributions` | `availability_status` | Direct | Not null |
| `triggered` | `candidate_risk_contributions` | `triggered` | Direct | Not null |
| `observed_value` | `candidate_risk_contributions` | `observed_value` | Direct | NULL allowed |
| `comparator` | `candidate_risk_contributions` | `comparator` | Direct | NULL allowed |
| `threshold_value` | `candidate_risk_contributions` | `threshold_value` | Direct | NULL allowed |
| `gross_points` | `candidate_risk_contributions` | `gross_points` | Direct | Not null |
| `cap_adjustment` | `candidate_risk_contributions` | `cap_adjustment` | Direct | Not null |
| `applied_points` | `candidate_risk_contributions` | `applied_points` | Direct | Not null |
| `missing_signal_reason` | `candidate_risk_contributions` | `missing_signal_reason` | Direct | NULL unless unavailable/invalid |
| `is_missing_signal` | expression | availability in `('unavailable','invalid')` | Boolean | Not null |
| `explanation_code` | `candidate_risk_contributions` | `explanation_code` | Direct | Not null |

Default JSON handling:

- Do not expose `input_lineage` in the MVP Power BI dataset unless required for hidden drill-through.
- If exposed later, restrict to read-only governance users.

Validation tests:

- No duplicate `(candidate_evaluation_id, component_code)`.
- `applied_points = gross_points + cap_adjustment`.
- Missing signals are counted from `availability_status`, not from zero points.

## `reporting.rpt_approvals`

Grain: one row per approval request-decision combination, including one request-only row when no decision exists.

This means:

- request counts must use distinct `approval_request_id`
- decision counts must use distinct non-null `approval_decision_id`
- pending requests are rows where `approval_decision_id IS NULL`

Mapping:

| Reporting column | Source table | Source column/expression | Derivation | Null handling |
|---|---|---|---|---|
| `approval_request_id` | `approval_requests` | `id` | Direct | Not null |
| `approval_decision_id` | `approval_decisions` | `id` | Left join | NULL for pending |
| `episode_id` | `approval_requests` | `episode_id` | Direct | Not null |
| `request_reference` | `approval_requests` | `request_reference` | Direct | Not null |
| `request_type` | `approval_requests` | `request_type` | Direct | Not null |
| `requester_user_id` | `approval_requests` | `requester_user_id` | Direct | Not null |
| `requested_at` | `approval_requests` | `recorded_at` | From mixin | Not null |
| `expires_at` | `approval_requests` | `expires_at` | Direct | NULL allowed |
| `reason` | `approval_requests` | `reason` | Direct | Not null |
| `decision_role` | `approval_decisions` | `decision_role` | Left join | NULL for pending |
| `approver_user_id` | `approval_decisions` | `approver_user_id` | Left join | NULL for pending |
| `decision_recorded_at` | `approval_decisions` | `recorded_at` | Left join | NULL for pending |
| `outcome` | `approval_decisions` | `outcome` | Left join | NULL for pending |
| `conditions` | `approval_decisions` | `conditions` | Left join | NULL allowed |
| `independence_check_passed` | `approval_decisions` | `independence_check_passed` | Left join | NULL for pending |
| `requester_equals_approver` | expression | requester = approver | Boolean when decision exists | False or NULL for pending |
| `is_self_approval_violation` | expression | requester = approver | Expected zero | False for pending |
| `request_status` | expression | pending/decided/expired | Based on decision and expiry | Not null |
| `is_pending` | expression | no decision row | Boolean | Not null |
| `decision_count` | expression | decision ID present | 1/0 | Not null |
| `decision_required_role_count` | N/A | Not derivable in MVP | Future enhancement | N/A |

MVP limitation:

- Required approval route/role count is not derivable from current schema because no approval policy table exists.

Validation tests:

- Distinct request count equals `approval_requests`.
- Non-null decision count equals `approval_decisions`.
- Self-approval violation count should be zero.
- Pending requests are not double counted.

## `reporting.rpt_suppressions`

Grain: one row per suppression control.

Mapping:

| Reporting column | Source table | Source column/expression | Derivation | Null handling |
|---|---|---|---|---|
| `suppression_control_id` | `suppression_controls` | `id` | Direct | Not null |
| `episode_id` | `suppression_controls` | `episode_id` | Direct | Not null |
| `approval_request_id` | `suppression_controls` | `approval_request_id` | Direct | Not null |
| `prior_state` | `suppression_controls` | `prior_state` | Direct | Not null |
| `reason_code` | `suppression_controls` | `reason_code` | Direct | Not null |
| `starts_at` | `suppression_controls` | `starts_at` | Direct | Not null |
| `expires_at` | `suppression_controls` | `expires_at` | Direct | Not null |
| `review_at` | `suppression_controls` | `review_at` | Direct | NULL allowed |
| `sla_consumed_minutes_at_pause` | `suppression_controls` | `sla_consumed_minutes_at_pause` | Direct | NULL allowed |
| `recurrence_criteria` | `suppression_controls` | `recurrence_criteria` | Optional JSON | Empty JSON allowed |
| `is_current_episode_state_suppressed` | `exception_episodes` | `current_state = 'suppressed'` | Join | Not null |
| `suppression_duration_hours` | expression | `expires_at - starts_at` | Static | Not null |
| `is_currently_effective` | DAX/refresh-time expression | report as-of between start and expiry | Time-relative | Not null |
| `is_expired` | DAX/refresh-time expression | expiry before report as-of | Time-relative | Not null |
| `expires_within_7_days` | DAX/refresh-time expression | expiry within 7 days of report as-of | Time-relative | Not null |

Validation tests:

- Row count equals `suppression_controls`.
- `expires_at > starts_at`.
- Historical suppression rows do not force current state.

## `reporting.rpt_pipeline_runs`

Grain: one row per pipeline run.

Mapping:

| Reporting column | Source table | Source column/expression | Derivation | Null handling |
|---|---|---|---|---|
| `pipeline_run_id` | `pipeline_runs` | `id` | Direct | Not null |
| `run_reference` | `pipeline_runs` | `run_reference` | Direct | Not null |
| `run_type` | `pipeline_runs` | `run_type` | Direct | Not null |
| `trigger_type` | `pipeline_runs` | `trigger_type` | Direct | Not null |
| `status` | `pipeline_runs` | `status` | Direct | Not null |
| `started_at` | `pipeline_runs` | `started_at` | Direct | Not null |
| `finished_at` | `pipeline_runs` | `finished_at` | Direct | NULL for unfinished |
| `duration_seconds` | expression | finished minus started | Static when finished | NULL for unfinished |
| `release_version` | `pipeline_runs` | `release_version` | Direct | NULL allowed |
| `configuration_hash` | `pipeline_runs` | `configuration_hash` | Direct | NULL allowed |
| `is_publication_eligible` | `pipeline_runs` | `is_publication_eligible` | Direct | Not null |
| `bundle_reference` | `pipeline_runs` | `bundle_reference` | Direct | NULL allowed |
| `manifest_hash` | `pipeline_runs` | `manifest_hash` | Direct | NULL allowed |
| `bundle_fingerprint` | `pipeline_runs` | `bundle_fingerprint` | Direct | NULL allowed |
| `upstream_generator_version` | `pipeline_runs` | `upstream_generator_version` | Direct | NULL allowed |
| `source_row_count` | `pipeline_runs` | `source_row_count` | Direct | NULL allowed |
| `accepted_row_count` | `pipeline_runs` | `accepted_row_count` | Direct | NULL allowed |
| `rejected_row_count` | `pipeline_runs` | `rejected_row_count` | Direct | NULL allowed |
| `failure_reason` | `pipeline_runs` | `failure_reason` | Direct | NULL unless failed |
| `source_load_count` | `source_loads` | count by run | Pre-aggregate | Zero if none |
| `step_count` | `pipeline_step_results` | count by run | Pre-aggregate | Zero if none |
| `successful_step_count` | `pipeline_step_results` | status success count | Pre-aggregate | Zero if none |
| `failed_step_count` | `pipeline_step_results` | status failed count | Pre-aggregate | Zero if none |
| `blocking_reconciliation_count` | `reconciliation_results` | blocking count | Pre-aggregate | Zero if none |
| `reconciliation_difference_count` | `reconciliation_results` | sum difference count | Pre-aggregate | Zero if none |
| `rejected_record_count` | `rejected_records` | count by run | Pre-aggregate | Zero if none |
| `publication_count` | `analytics_publications` | count by run | Pre-aggregate | Zero if none |
| `is_success` | expression | `status = 'success'` | Boolean | Not null |
| `is_failed` | expression | `status = 'failed'` | Boolean | Not null |

Validation tests:

- Row count equals `pipeline_runs`.
- No duplicate `pipeline_run_id`.
- Aggregated child counts reconcile to source tables.

## `reporting.dim_exception`

Recommended thin dimension to avoid ambiguous fact-to-fact paths.

Grain: one row per exception episode.

Columns:

| Column | Source |
|---|---|
| `episode_id` | `exception_episodes.id` |
| `exception_reference` | expression from sequence and ID |
| `po_line_id` | `exception_episodes.po_line_id` |
| `site_id` | `exception_episodes.site_id` |
| `opened_at` | `exception_episodes.opened_at` |
| `closed_at` | `exception_episodes.closed_at` |
| `current_state` | `exception_episodes.current_state` |

Power BI can still use `rpt_exception_summary` as an accumulating snapshot fact, but relationships from detail facts should filter through `dim_exception`.

## Necessary Dimensions

Create:

- `reporting.dim_date`
- `reporting.dim_exception`
- `reporting.dim_site`
- `reporting.dim_supplier`
- `reporting.dim_product`
- `reporting.dim_user`
- `reporting.dim_exception_state`
- `reporting.dim_severity`
- `reporting.dim_rule_component`

Dimension handling:

- `dim_supplier` uses current/latest `supplier_versions`.
- `dim_product` uses current/latest `product_versions`.
- Historical as-of dimensions are future enhancements.

## 4. Power BI Star Schema

Use single-direction filtering from dimensions to facts.

Recommended relationships:

| From | To | Direction |
|---|---|---|
| `dim_exception[episode_id]` | `rpt_exception_summary[episode_id]` | One-to-many |
| `dim_exception[episode_id]` | `rpt_exception_events[episode_id]` | One-to-many |
| `dim_exception[episode_id]` | `rpt_approvals[episode_id]` | One-to-many |
| `dim_exception[episode_id]` | `rpt_suppressions[episode_id]` | One-to-many |
| `dim_site[site_id]` | `rpt_exception_summary[site_id]` | One-to-many |
| `dim_supplier[supplier_id]` | `rpt_exception_summary[supplier_id]` | One-to-many |
| `dim_product[product_id]` | `rpt_exception_summary[product_id]` | One-to-many |
| `dim_user[user_id]` | `rpt_exception_summary[current_owner_user_id]` | One-to-many |
| `dim_exception_state[state_code]` | `rpt_exception_summary[current_state]` | One-to-many |
| `dim_severity[severity_code]` | `rpt_exception_summary[effective_severity]` | One-to-many |
| `rpt_risk_assessments[candidate_evaluation_id]` | `rpt_risk_components[candidate_evaluation_id]` | One-to-many |
| `rpt_pipeline_runs[pipeline_run_id]` | `rpt_risk_assessments[pipeline_run_id]` | One-to-many |
| `dim_rule_component[rule_component_id]` | `rpt_risk_components[rule_component_id]` | One-to-many |

Avoid:

- bidirectional relationships
- direct many-to-many fact relationships
- multiple active filter paths between the same tables

## 5. Time-Relative Field Policy

| Field | Recommended calculation location | Reason |
|---|---|---|
| Exception age | DAX or refresh timestamp | Keeps users aware of report freshness |
| Overdue unsatisfied SLA | DAX or refresh timestamp | Depends on report as-of time |
| Currently effective suppression | DAX or refresh timestamp | Changes with time |
| Suppression expiring within 7 days | DAX or refresh timestamp | Changes with time |
| Pipeline duration | PostgreSQL view | Stable once `finished_at` exists |
| Closure time | PostgreSQL view | Stable once closed |
| Resolution time | PostgreSQL view | Stable once resolved |

MVP recommendation:

- PostgreSQL views expose raw timestamps and stable durations.
- Power BI creates a visible `Report As Of` measure.
- Time-relative KPIs use that report-as-of value.

## 6. Security and Access Model

Create a dedicated read-only Power BI database role.

Recommended role:

```text
powerbi_reporting_reader
```

Permissions:

- `USAGE` on schema `reporting`
- `SELECT` on reporting views only
- no `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` on any table
- no workflow function execution permissions
- no direct operational table access unless explicitly required for validation

JSON and technical identifiers:

- Hide full operational JSON payloads by default.
- Expose boolean flags or controlled summaries instead.
- Keep technical UUIDs where needed for relationships and drill-through.
- Do not expose idempotency keys, raw rejected values, internal hashes or evidence payloads unless required for governance pages.

Authentication note:

- Existing synthetic users are simulation actors only.
- They are not production authentication or authorization controls.

## 7. Data Limitations to Disclose

Power BI must disclose:

- Active Operational Exceptions exclude Suppressed and Closed.
- Suppressed exceptions are monitored separately.
- Resolved exceptions remain active until Closed.
- Candidate Risk is analytical and not a workflow state.
- High/Critical score is not the same as workflow opening eligibility.
- Missing risk signals are not zero contribution.
- Financial exposure is AUD only where `unit_price_aud` or `line_value_aud` exists.
- No currency conversion is implemented.
- Historical reporting uses current/latest descriptors in MVP.
- Formal SLA breach event reporting is unavailable because no governed SLA breach event enum/code exists.
- Overdue SLA is a condition based on obligation due dates, not a formal breach event.
- Hidden synthetic scenario and outcome labels remain outside operational reporting.
- Power BI is read-only and must not operate workflow actions.

## 8. Future Enhancements

Move these outside the MVP reporting contract:

- Formal SLA event code dimension and governed breach/escalation codes.
- SLA policy table defining required obligations by severity/state.
- Approval policy table defining required roles/counts.
- As-of supplier/product/PO dimensions for historical reporting.
- Power BI refresh audit table.
- Persisted business calendar/date dimension in PostgreSQL.
- Controlled JSON drill-through views for audit users.
- Hidden outcome evaluation mart for model validation.
- Currency conversion support beyond AUD fields.

## 9. Recommended Implementation Sequence

1. Commit this approved design document.
2. Create the `reporting` schema.
3. Create dimensions first.
4. Create `reporting.dim_exception`.
5. Create `reporting.rpt_exception_summary`.
6. Create event, approval and suppression views.
7. Create candidate risk and risk component views.
8. Create pipeline run view.
9. Add SQL validation tests for grain, duplicates and metric reconciliation.
10. Build the Power BI model with single-direction relationships only.
11. Add DAX measures for time-relative KPIs.
12. Review exact field mappings before authorising SQL implementation.

## Report-to-Requirement Traceability

| Report page | Requirement mapping | Main reporting views used |
|---|---|---|
| Executive Control Tower | workload prioritisation and management visibility | `reporting.rpt_exception_summary`, `reporting.rpt_pipeline_runs`, `reporting.dim_exception`, `reporting.dim_site`, `reporting.dim_supplier`, `reporting.dim_product`, `reporting.dim_user`, `reporting.dim_exception_state`, `reporting.dim_severity` |
| Exception Performance | lifecycle effectiveness and bottleneck monitoring | `reporting.rpt_exception_summary`, `reporting.rpt_exception_events`, `reporting.rpt_approvals`, `reporting.dim_exception`, `reporting.dim_exception_state`, `reporting.dim_user`, `reporting.dim_date` |
| Supplier Risk and Performance | supplier exposure and recurring risk | `reporting.rpt_exception_summary`, `reporting.rpt_risk_assessments`, `reporting.rpt_risk_components`, `reporting.dim_supplier`, `reporting.dim_site`, `reporting.dim_severity`, `reporting.dim_rule_component` |
| PO and Inventory Risk | analytical risk explanation and residual exposure | `reporting.rpt_exception_summary`, `reporting.rpt_risk_assessments`, `reporting.rpt_risk_components`, `reporting.dim_product`, `reporting.dim_site`, `reporting.dim_rule_component`, `reporting.dim_severity` |
| Governance and Control | approvals, suppression, auditability, pipeline health | `reporting.rpt_approvals`, `reporting.rpt_suppressions`, `reporting.rpt_exception_events`, `reporting.rpt_pipeline_runs`, `reporting.dim_exception`, `reporting.dim_user` |
| Exception Drill-Through | detailed case-level management review | `reporting.rpt_exception_summary`, `reporting.rpt_exception_events`, `reporting.rpt_risk_assessments`, `reporting.rpt_risk_components`, `reporting.rpt_approvals`, `reporting.rpt_suppressions`, `reporting.dim_exception` |
```
