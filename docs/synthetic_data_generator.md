# Synthetic Data Generator

The synthetic generator creates deterministic, portfolio-safe source datasets for the Supply Chain Exception Control System. It prepares realistic operational inputs for a later ingestion pipeline, but it does not load operational database tables and does not implement risk scoring, exception creation, workflow services, notifications, Streamlit, Power BI or AI.

## Governing Boundary

The generator follows the governing documents under `docs/governing/`, especially the Logical Data Model and Data Contracts, Risk-Priority and Synthetic Data Specification, Frozen Operating Model, and Test and Evidence Strategy.

It preserves these portfolio baselines:

- simulated Australian mid-sized distributor/manufacturer;
- two receiving sites using Australia/Melbourne business context;
- synthetic suppliers, products, users and operational records only;
- base UOM `EA`; purchase UOM `EA`, `CASE` or `PALLET`;
- positive whole-number UOM conversion factors;
- four-decimal quantity compatibility and two-decimal AUD money compatibility;
- deterministic source data and independent hidden outcomes.

## Architecture

The package lives under `src/scecs/synthetic/`.

| Module | Purpose |
| --- | --- |
| `config.py` | Typed generator profiles, seed, dates, volumes, rates and version. |
| `random_context.py` | Named deterministic random streams for master, PO, receipt, demand, outcome and scenario domains. |
| `organisation.py` | Sites, users, ownership mappings, calendar and rule metadata references. |
| `master_data.py` | Suppliers, product versions, inventory policies and UOM conversions. |
| `purchase_orders.py` | PO headers, line identities, aliases, line versions and delivery schedules. |
| `receipts.py` | Supplier commitments, as-of-visible receipts, future receipt realisations and allocations. |
| `inventory.py` | Product-site inventory snapshots. |
| `demand.py` | Dated firm and forecast demand requirements. |
| `supplier_performance.py` | Historical supplier OTIF observations. |
| `outcomes.py` | Independent hidden synthetic outcome labels. |
| `scenarios.py` | Controlled scenario registry and line assignments. |
| `validation.py` | Key, reconciliation, allocation, correction, scenario and synthetic-safety checks. |
| `export.py` | Deterministic CSV, manifest and summary export. |
| `cli.py` | `generate`, `validate` and `summarise` commands. |

## Source-Data Hardening Controls

Scenario traceability uses registry identifiers, not labels. Operational datasets store actual scenario UUIDs in `scenario_ids` and readable labels in `scenario_types`. `scenario_registry.csv` remains the source of scenario type, affected entity, affected key, start date and end date.

The generator applies observable effects for each mandatory scenario:

- `overdue_critical_order`: open critical line, need date before as-of date and positive residual quantity.
- `partial_receipt_remaining_exposure`: receipts below final line quantity with residual exposure.
- `supplier_commitment_breach`: supplier commitment followed by a later actual receipt.
- `demand_shock`: increased demand for the affected product/site.
- `receipt_correction`: correction transaction linked to an original receipt.
- `receipt_reversal`: reversal transaction linked to an original receipt.
- `split_schedule`: two or more schedules reconciling to final line quantity.
- `supplier_deterioration`: late delivery behaviour for the affected supplier context.
- `inventory_reallocation_opportunity`: shortage at the affected site and surplus at the other site.
- `false_positive_source_data_correction`: initial exposure-like inventory observation followed by a correcting observation.
- `missing_supplier_signal`: no supplier commitment observation for the affected line.
- `missing_inventory_signal`: stale scenario-tagged evidence and no valid current inventory observation for the affected product/site.

Purchase orders now choose the supplier at PO-header creation. Every line version under that PO carries the same `po_supplier_id`, and the PO header status is reconciled against final line statuses.

For every line version, `base_quantity = ordered_quantity x conversion_factor`; amendments recompute ordered quantity, base quantity, need date and line value while preserving earlier versions.

Every receipt, correction and reversal has allocation rows. Allocation quantities remain non-negative and reconcile to `ABS(receipt_transactions.base_quantity)`. The sign is represented by the receipt transaction, not by the allocation quantity. Schedule allocations are capped on a net signed basis; excess goes to `line_residual`.

Demand and inventory are generated at product-site grain. When several PO-line scenarios share a product-site, those rows aggregate the relevant scenario UUIDs so each scenario remains traceable. Missing-inventory scenarios conflict with current inventory correction and reallocation scenarios at this grain, so incompatible missing-inventory assignments are removed before downstream generation.

## As-Of Visibility Boundary

The operational as-of timestamp is `2026-06-30T18:00:00+10:00` for the governed portfolio profile. Operational input files contain only information observable on or before that timestamp:

- `receipt_transactions.posted_at` is at or before as-of.
- `supplier_commitment_observations.observed_at` is at or before as-of.
- PO header, PO-line and source-alias effective timestamps are at or before as-of.
- `source_loads.extracted_at` and `source_loads.received_at` are at or before as-of.
- `inventory_snapshots.snapshot_at` is at or before as-of.
- `supplier_performance_snapshots` are calculated from operational receipts visible at as-of.

Future planned business dates remain allowed when the information itself was known by as-of. Examples include need dates, expected delivery dates, requested dates, committed delivery dates, demand requirement dates and delivery schedule dates.

Post-as-of receipt realisations are written to `future_receipt_outcomes.csv`. This file is evaluation-only, has no operational `source_load_id`, and is not included in the receipts source-load hash or row count. `synthetic_outcome_observations.csv` references those future receipt outcome IDs for open-line outcome evaluation.

## Commands

Use the CI-sized profile for fast local checks:

```powershell
python -m scecs.synthetic.cli generate --profile ci --output data/sample/synthetic_ci
python -m scecs.synthetic.cli validate --profile ci --output data/sample/synthetic_ci
python -m scecs.synthetic.cli summarise --profile ci --output data/sample/synthetic_ci
```

Use the full portfolio profile for evidence runs:

```powershell
python -m scecs.synthetic.cli generate --profile portfolio --output data/generated/portfolio_baseline
python -m scecs.synthetic.cli validate --profile portfolio --output data/generated/portfolio_baseline
python -m scecs.synthetic.cli summarise --profile portfolio --output data/generated/portfolio_baseline --write-doc docs/synthetic_quality_report.md
```

`data/generated/` is ignored by Git. The repository commits only the small sample fixture under `data/sample/synthetic_ci/` and the summary evidence.

## Determinism

The generator uses stable UUIDv5 identifiers and named random streams derived from:

- generator version;
- seed;
- configuration;
- as-of date;
- stream domain.

The generation timestamp written to manifests is deterministic and derived from the as-of date. Repeating the same profile and seed produces identical CSV file hashes. Changing the seed changes generated records while preserving schema and configured volumes.

## Independent Outcomes

Outcome generation uses hidden supplier factors, demand shocks, logistics disruption, site effects, seasonality and random noise. It does not accept or read risk score, severity, rule points, candidate disposition, lifecycle state or exception action fields. Outcome records contain opportunity classes for later evaluation:

- `true_positive_opportunity`;
- `false_positive_opportunity`;
- `true_negative_opportunity`;
- `false_negative_opportunity`.

These are synthetic evaluation labels only. They are not operational exceptions.
