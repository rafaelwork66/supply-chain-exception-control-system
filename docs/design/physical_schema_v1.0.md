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
- PostgreSQL partial unique index for active episode uniqueness
- PostgreSQL exclusion constraints for non-overlapping effective-dated reference intervals

Deferred:

- Domain rule execution
- Exception lifecycle services
- Risk scoring logic
- Streamlit pages
- Notifications
- AI recommendations
- Power BI semantic model

## Key PostgreSQL Controls

- `gen_random_uuid()` from `pgcrypto` creates database-side UUID defaults.
- `btree_gist` supports exclusion constraints for effective-dated intervals.
- `uq_exception_episodes_active_line_site` enforces one non-Closed episode per canonical PO line and receiving site.
- Check constraints enforce controlled states, severities, dispositions, statuses, score ranges, positive quantities, and non-self episode relationships.
- `JSONB` is used only for safe metadata, payload snapshots, and controlled representation fields.

## Known Design Risks

- Governing Appendix G still contains open questions about exact recurrence thresholds, evidence catalogues, approval routes, freshness thresholds, and Power BI delivery path.
- The schema enforces structural integrity, not unresolved business-rule logic.
- Generic evidence links are constrained by target type but cannot enforce every target foreign key physically without separate typed link tables.
- Notifications are intentionally omitted from this migration because notification implementation is outside the requested scope.
