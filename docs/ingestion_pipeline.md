# Ingestion Pipeline

This document describes the governed operational ingestion pipeline for the synthetic source bundle.

## Scope

The pipeline loads operational source datasets only. It does not implement risk scoring, candidate-risk evaluation, exception creation, lifecycle services, Streamlit, notifications, Power BI, AI, or scheduled GitHub Actions processing.

Default commands:

```powershell
python -m scecs.ingestion.cli inspect --input data/sample/synthetic_ci
python -m scecs.ingestion.cli validate --input data/sample/synthetic_ci
python -m scecs.ingestion.cli load --input data/sample/synthetic_ci
python -m scecs.ingestion.cli reconcile --run-reference <run>
python -m scecs.ingestion.cli status --run-reference <run>
```

## Modules

| Module | Purpose |
| --- | --- |
| `config.py` | Operational dataset scope, expected schema/generator versions, load order and evaluation-only exclusions. |
| `contracts.py` | Typed dataset contracts, parsing rules and rejection classifications. |
| `manifest.py` | Bundle discovery, manifest hash checks, row-count checks and path-safety checks. |
| `readers.py` | CSV reading, row fingerprints and natural-key labels. |
| `parsers.py` | Stage A record parsing and contract validation. |
| `validators.py` | Stage B cross-dataset validation and as-of controls. |
| `mappings.py` | Explicit source-to-target table mappings and excluded evidence columns. |
| `loaders.py` | PostgreSQL bounded-batch loading, per-attempt source-load lineage and conflict-aware idempotency. |
| `reconciliation.py` | Dataset-level source, accepted, inserted, existing, conflicting, rejected, matched and total-table counts. |
| `publication.py` | Atomic current-success publication pointer update. |
| `service.py` | End-to-end inspect, validate, load, status and reconciliation orchestration. |
| `cli.py` | Command-line entry point. |

## Load Order

The dependency-safe load order is:

1. Source systems and source-load metadata.
2. Sites, suppliers, supplier versions, products and product versions.
3. UOM conversions, product-site policies, users, ownership mappings, calendar versions and rule versions.
4. Purchase orders, PO versions, PO lines, aliases and line versions.
5. Delivery schedules, supplier commitments, receipt transactions and receipt allocations.
6. Inventory snapshots, demand requirements and supplier-performance snapshots.

## Transaction and Publication Design

`load` validates the bundle before any operational load. If blocking validation exists, the actual ingestion run is recorded as failed and no publication is created.

Every ingestion attempt first creates a durable `pipeline_runs` control row with bundle reference, manifest hash, bundle fingerprint, upstream generator version and source row count. Operational rows then load inside one PostgreSQL transaction. Reconciliation rows and publication are created in that same operational transaction. The current-success publication pointer is replaced only after reconciliation passes.

If validation blocks before loading, the run is marked failed and all rejections are persisted, even on an empty database. If PostgreSQL fails after loading starts, domain rows, source-load rows, reconciliation rows and publication changes from that attempt are rolled back; the durable run is then marked failed with safe rejection/error evidence. Previous current-success publication remains unchanged.

## Idempotency

The loader does not use blind `ON CONFLICT DO NOTHING`. For each mapped row, the governed source identity is checked against the existing target row:

- absent identity = inserted;
- identical existing mapped content = existing/idempotent;
- same identity with different mapped content = `SOURCE_IDENTITY_CONFLICT`, failed run and no publication.

Source-load lineage is per attempt. The loader creates new internal `source_loads` rows for each ingestion run, preserves upstream source-load identity and manifest metadata on those rows, and remaps downstream `source_load_id` values in memory before insert. Existing accepted domain rows may remain linked to the original successful attempt source load; identical reruns create new source-load evidence but do not duplicate domain rows.

Rows load in configurable bounded batches. The default batch size is 1,000 records, preserving deterministic load order and one atomic operational publication transaction.

## Publication Rule for Rejections

Warning-only exclusions and record-rejectable rows are persisted. Record-rejectable rows may continue only when no blocking relationship or control fails. Dataset-blocking, bundle-blocking and identity-conflict rejections prohibit publication.

