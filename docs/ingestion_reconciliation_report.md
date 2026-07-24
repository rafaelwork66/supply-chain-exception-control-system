# Ingestion Reconciliation Report

## CI Fixture Validation

Command:

```powershell
python -m scecs.ingestion.cli validate --input data/sample/synthetic_ci
```

Result: passed.

Operational row counts accepted by validation:

| Dataset | Rows |
| --- | ---: |
| `calendar_versions` | 1 |
| `delivery_schedules` | 363 |
| `demand_requirements` | 320 |
| `inventory_snapshots` | 81 |
| `ownership_mappings` | 8 |
| `product_site_inventory_policies` | 80 |
| `product_versions` | 40 |
| `products` | 40 |
| `purchase_order_line_aliases` | 260 |
| `purchase_order_line_versions` | 282 |
| `purchase_order_lines` | 260 |
| `purchase_order_versions` | 103 |
| `purchase_orders` | 103 |
| `receipt_allocations` | 432 |
| `receipt_transactions` | 339 |
| `rule_versions` | 1 |
| `sites` | 2 |
| `source_loads` | 6 |
| `source_systems` | 1 |
| `supplier_commitment_observations` | 227 |
| `supplier_performance_snapshots` | 24 |
| `supplier_versions` | 12 |
| `suppliers` | 12 |
| `uom_conversions` | 120 |
| `users` | 21 |

Skipped warning-only non-operational files:

- `future_receipt_outcomes`
- `synthetic_outcome_observations`
- `pipeline_runs`
- `scenario_registry`
- `scenario_assignments`

## Database Reconciliation

When PostgreSQL integration settings are enabled, `load` writes dataset-level reconciliation rows to `reconciliation_results`.

Each dataset reconciliation contains:

- source rows;
- accepted rows;
- inserted rows;
- existing/idempotent rows;
- conflicting rows;
- rejected rows;
- matched target rows;
- target table rows;
- total table rows;
- difference;
- status;
- explanation.

Local PostgreSQL integration tests are present in `tests/integration/test_ingestion_pipeline_postgresql.py`. They are skipped unless `SCECS_RUN_INTEGRATION_TESTS=1` and database environment variables are set. CI also runs `tests/integration/test_ingestion_full_profile_postgresql.py` with `SCECS_RUN_FULL_PROFILE_TESTS=1` to generate and load the full portfolio profile without committing generated CSV files.

## Full Portfolio Validation Evidence

Command:

```powershell
python -m scecs.synthetic.cli generate --profile portfolio --output data/generated/portfolio_baseline
python -m scecs.synthetic.cli validate --profile portfolio --output data/generated/portfolio_baseline
python -m scecs.ingestion.cli inspect --input data/generated/portfolio_baseline
python -m scecs.ingestion.cli validate --input data/generated/portfolio_baseline
```

Result:

- Generator runtime: 20.3382 seconds.
- Generated PO lines: 62,000.
- Synthetic validation: passed in 8.6399 seconds.
- Ingestion manifest inspection: passed.
- Ingestion operational validation: passed.
- Manifest hash: `4bd8fdb37adab066cfc28f337dd2afd5c39efb768c219077884dd095f658f98f`.

Operational full-profile row counts accepted by validation:

| Dataset | Rows |
| --- | ---: |
| `calendar_versions` | 1 |
| `delivery_schedules` | 88,186 |
| `demand_requirements` | 8,000 |
| `inventory_snapshots` | 2,001 |
| `ownership_mappings` | 8 |
| `product_site_inventory_policies` | 2,000 |
| `product_versions` | 1,000 |
| `products` | 1,000 |
| `purchase_order_line_aliases` | 62,000 |
| `purchase_order_line_versions` | 66,871 |
| `purchase_order_lines` | 62,000 |
| `purchase_order_versions` | 24,018 |
| `purchase_orders` | 24,018 |
| `receipt_allocations` | 110,010 |
| `receipt_transactions` | 83,816 |
| `rule_versions` | 1 |
| `sites` | 2 |
| `source_loads` | 6 |
| `source_systems` | 1 |
| `supplier_commitment_observations` | 54,547 |
| `supplier_performance_snapshots` | 240 |
| `supplier_versions` | 120 |
| `suppliers` | 120 |
| `uom_conversions` | 3,000 |
| `users` | 21 |

PostgreSQL ingestion of the full profile was not run in this local session because the required database environment variables were not configured. `python -m alembic upgrade head` and `python -m alembic current` both failed before connection with `Missing required environment variable: SCECS_DB_NAME`.
