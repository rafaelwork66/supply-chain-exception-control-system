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
| `loaders.py` | PostgreSQL transactional inserts with idempotent `ON CONFLICT DO NOTHING`. |
| `reconciliation.py` | Dataset-level source, accepted, inserted, existing and target counts. |
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

For valid data, operational rows load inside one PostgreSQL transaction. Reconciliation rows and publication are created in the same transaction. The current-success publication pointer is replaced only after reconciliation passes. A failed run does not delete previous successful pipeline evidence and does not replace the current successful publication.

## Idempotency

Reruns use:

- the manifest hash and configuration hash as the bundle fingerprint;
- stable source UUIDs from the deterministic generator;
- source natural keys and database uniqueness constraints;
- PostgreSQL `ON CONFLICT DO NOTHING`.

The first valid load inserts records. A second identical load creates a new ingestion run but reports existing domain rows instead of duplicating them. A changed bundle has a different manifest hash and creates a distinct run. Blocking failures remain unpublished.

