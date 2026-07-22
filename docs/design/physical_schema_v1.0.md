# Physical PostgreSQL Schema v1.0

This design note documents the first physical PostgreSQL schema for the Supply Chain Exception Control System.

## Source Authority

The schema is based on the governing documents under `docs/governing/`, especially:

- `04_logical_data_model_and_contracts_v1.0.pdf`
- `03_frozen_operating_model_v1.0.pdf`
- `05_risk_priority_and_synthetic_data_specification_v1.0.pdf`
- `06_test_and_evidence_strategy_v1.0.docx`

The Test and Evidence Strategy is present as a DOCX in the provided bundle, not as a PDF.

## Scope

Implemented:

- Source, pipeline, reconciliation, and publication-control tables
- Master/reference tables
- Procurement and supply observation tables
- Candidate risk evaluation and contribution tables
- Exception episode, event, action, ownership, SLA, approval, suppression, evidence, resolution, and relationship tables
- Inactive `notification_events` structure for future notification audit records
- PostgreSQL partial unique index for active episode uniqueness using `closed_at IS NULL`
- PostgreSQL exclusion constraints for non-overlapping effective-dated reference intervals

Deferred:

- Domain rule execution
- Exception lifecycle services
- Risk scoring logic
- Streamlit pages
- Notification sending and provider integration
- AI recommendations
- Power BI semantic model

## Key PostgreSQL Controls

- `gen_random_uuid()` from `pgcrypto` creates database-side UUID defaults.
- `btree_gist` supports exclusion constraints for effective-dated intervals.
- `uq_exception_episodes_active_line_site` enforces one active episode per canonical PO line and receiving site where `closed_at IS NULL`.
- A projection consistency check enforces that `current_state = 'closed'` requires `closed_at IS NOT NULL`, and non-Closed states require `closed_at IS NULL`.
- Candidate contribution rows preserve `applied_points = gross_points + cap_adjustment`.
- UOM conversion factors are positive integers for the synthetic MVP contract covering EA, CASE, and PALLET conversions.
- Constraint triggers prevent material self-approval for `suppression`, `resolution`, `severity_override`, `material_recurrence`, and `closure` approval request types.
- Constraint triggers require material-recurrence successors and relationships to reference a predecessor episode that is formally Closed and has `closed_at` populated.
- Event envelopes include an explicit `idempotency_key` unique within an episode; `correlation_id` remains separate trace metadata.
- Check constraints enforce controlled states, severities, dispositions, statuses, score ranges, positive quantities, and non-self episode relationships.
- `JSONB` is used only for safe metadata, payload snapshots, and controlled representation fields.

## Deferred Service Controls

- Ordered lifecycle transition validation remains an application-service concern.
- Risk scoring and candidate contribution calculation are not implemented; the database only stores and checks supplied values.
- Notification routing, retries, templates, provider calls, and email delivery are not implemented.
- Evidence catalogue completeness and approval routing policy details remain unresolved governing questions.

## Inactive Structures

- `notification_events` is included only to preserve future notification audit shape. It does not send notifications and does not imply provider integration.

## Downgrade Behaviour

Because this migration is still unreleased, downgrade drops the schema-owned tables and trigger functions with `CASCADE`. This supports clean development rebuilds and CI verification, not production rollback policy.

## Known Design Risks

- Governing Appendix G still contains open questions about exact recurrence thresholds, evidence catalogues, approval routes, freshness thresholds, and Power BI delivery path.
- The schema enforces structural integrity, not unresolved business-rule logic.
- Generic evidence links are constrained by target type but cannot enforce every target foreign key physically without separate typed link tables.
- Notification implementation remains outside the requested scope even though the inactive table structure is present.
