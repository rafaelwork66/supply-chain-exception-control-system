# Source-to-Target Mapping

The normal operational ingestion command maps only governed physical columns. Synthetic evidence columns are not silently discarded: each is listed as intentionally excluded from operational persistence because the current physical schema has no approved metadata column for it.

Use this command to print the live mapping from code:

```powershell
python -m scecs.ingestion.cli mapping
```

## Operational Tables

| Source dataset | Target table | Evidence columns excluded from operational tables |
| --- | --- | --- |
| `source_systems` | `source_systems` | None |
| `source_loads` | `source_loads` | None |
| `sites` | `sites` | `synthetic_data_flag` |
| `suppliers` | `suppliers` | `synthetic_data_flag` |
| `supplier_versions` | `supplier_versions` | `synthetic_data_flag` |
| `products` | `products` | `synthetic_data_flag` |
| `product_versions` | `product_versions` | `abc_class`, `xyz_class`, `synthetic_data_flag` |
| `uom_conversions` | `uom_conversions` | None |
| `product_site_inventory_policies` | `product_site_inventory_policies` | None |
| `users` | `users` | `synthetic_data_flag` |
| `ownership_mappings` | `ownership_mappings` | `synthetic_data_flag` |
| `calendar_versions` | `calendar_versions` | None |
| `rule_versions` | `rule_versions` | None |
| `purchase_orders` | `purchase_orders` | `synthetic_data_flag` |
| `purchase_order_versions` | `purchase_order_versions` | None |
| `purchase_order_lines` | `purchase_order_lines` | `synthetic_data_flag` |
| `purchase_order_line_aliases` | `purchase_order_line_aliases` | None |
| `purchase_order_line_versions` | `purchase_order_line_versions` | `po_supplier_id`, `scenario_ids`, `scenario_types`, `critical_order_flag` |
| `delivery_schedules` | `delivery_schedules` | `scenario_ids`, `scenario_types` |
| `supplier_commitment_observations` | `supplier_commitment_observations` | `scenario_ids`, `scenario_types` |
| `receipt_transactions` | `receipt_transactions` | `late_receipt_flag`, `scenario_ids`, `scenario_types` |
| `receipt_allocations` | `receipt_allocations` | `po_line_id_for_validation`, `corrected_receipt_id`, `scenario_ids`, `scenario_types` |
| `inventory_snapshots` | `inventory_snapshots` | `missing_signal_flag`, `scenario_ids`, `scenario_types` |
| `demand_requirements` | `demand_requirements` | `demand_class`, `product_category`, `demand_shock_flag`, `scenario_ids`, `scenario_types` |
| `supplier_performance_snapshots` | `supplier_performance_snapshots` | None |

## Upstream Metadata

`pipeline_runs.csv` describes the upstream synthetic generation run. It is verified as bundle evidence but is not used as proof of ingestion success. The actual ingestion attempt is recorded by a new `pipeline_runs` row with `run_type = 'ingestion'`.

`source_loads.csv` provides upstream dataset object metadata. During each ingestion attempt, the loader creates new internal `source_loads` rows linked to the current ingestion `pipeline_runs` row. The upstream source-load ID, upstream pipeline-run ID, manifest dataset name, file name and file hash are preserved on the internal row. Downstream operational rows are remapped in memory to the current attempt source-load IDs before insert.

`criticality`, `unit_price_aud` and `line_value_aud` are governed operational risk inputs. Scenario IDs, scenario types and hidden evaluation labels remain excluded from operational persistence.

