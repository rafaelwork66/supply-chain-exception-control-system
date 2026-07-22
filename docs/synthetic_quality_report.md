# Synthetic Data Quality Report

This report describes generated synthetic portfolio data only. It does not represent a real company.

## Control Result

- Passed: `True`
- Profile: `portfolio`
- Open line count: `1500`
- Split-schedule rate: `0.2107`
- Partial-receipt rate: `0.1866`
- Late-receipt rate: `0.49`
- Correction/reversal rate: `0.012`
- Missing supplier signals: `3827`
- Missing inventory signals: `1458`
- Combined missing-signal rate: `0.0852`

## Target Comparison

| Control | Governed target or expected range | Actual | Result |
| --- | --- | --- | --- |
| Sites | 2 exact | 2 | Pass |
| Suppliers | 120 exact for portfolio profile | 120 | Reported |
| SKUs | 1,000 exact for portfolio profile | 1000 | Reported |
| PO lines | at least 50,000 for portfolio profile | 62000 | Reported |
| Open lines at snapshot | configured target | 1500 | Pass |
| Split-schedule lines | 18-25% | 21.07% | Reported |
| Lines with partial receipts | 15-25% | 18.66% | Reported |
| Receipt corrections/reversals | 0.5-1.5% of receipt events | 1.20% | Reported |
| Outcome opportunity classes | TP, FP, TN and FN opportunities present | all present | Pass |
| Late receipt rate | measured source-data evidence, no hard target in this work package | 49.00% | Reported |

## Performance Evidence

| Measure | Value |
| --- | --- |
| Generation duration | 19.417 seconds |
| Output size | 145459970 bytes |
| Output path | `data\generated\portfolio_baseline` |
| PO-line count | 62000 |

Performance values are simulated-project evidence from this local development machine, not production benchmarks.

## Row Counts

- `calendar_versions`: 1
- `delivery_schedules`: 88186
- `demand_requirements`: 8000
- `future_receipt_outcomes`: 1804
- `inventory_snapshots`: 2001
- `ownership_mappings`: 8
- `pipeline_runs`: 1
- `product_site_inventory_policies`: 2000
- `product_versions`: 1000
- `products`: 1000
- `purchase_order_line_aliases`: 62000
- `purchase_order_line_versions`: 66871
- `purchase_order_lines`: 62000
- `purchase_order_versions`: 24018
- `purchase_orders`: 24018
- `receipt_allocations`: 110010
- `receipt_transactions`: 83816
- `rule_versions`: 1
- `scenario_assignments`: 23610
- `scenario_registry`: 23610
- `sites`: 2
- `source_loads`: 6
- `source_systems`: 1
- `supplier_commitment_observations`: 54547
- `supplier_performance_snapshots`: 240
- `supplier_versions`: 120
- `suppliers`: 120
- `synthetic_outcome_observations`: 62000
- `uom_conversions`: 3000
- `users`: 21

## Scenario Counts

- `demand_shock`: 2457
- `false_positive_source_data_correction`: 1
- `inventory_reallocation_opportunity`: 1
- `missing_inventory_signal`: 2458
- `missing_supplier_signal`: 3827
- `overdue_critical_order`: 1
- `partial_receipt_remaining_exposure`: 1
- `receipt_correction`: 1
- `receipt_reversal`: 1
- `split_schedule`: 13062
- `supplier_commitment_breach`: 1
- `supplier_deterioration`: 1799

## Outcome Opportunity Counts

- `false_negative_opportunity`: 4515
- `false_positive_opportunity`: 7932
- `true_negative_opportunity`: 41144
- `true_positive_opportunity`: 8409
