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
| `receipts.py` | Supplier commitments, receipts, corrections, reversals and allocations. |
| `inventory.py` | Product-site inventory snapshots. |
| `demand.py` | Dated firm and forecast demand requirements. |
| `supplier_performance.py` | Historical supplier OTIF observations. |
| `outcomes.py` | Independent hidden synthetic outcome labels. |
| `scenarios.py` | Controlled scenario registry and line assignments. |
| `validation.py` | Key, reconciliation, allocation, correction, scenario and synthetic-safety checks. |
| `export.py` | Deterministic CSV, manifest and summary export. |
| `cli.py` | `generate`, `validate` and `summarise` commands. |

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
