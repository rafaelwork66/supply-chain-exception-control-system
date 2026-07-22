# Synthetic Data Dictionary

All generated datasets are synthetic and portfolio-safe. CSV files are exported with deterministic field ordering and a manifest containing row counts and SHA-256 file hashes.

| Dataset | Grain | Notes |
| --- | --- | --- |
| `source_systems.csv` | One simulated source system | No credentials or connection secrets. |
| `pipeline_runs.csv` | One synthetic generation run | Records generator version, seed and configuration hash. |
| `source_loads.csv` | One source dataset object per run | Lineage anchor for later ingestion. |
| `sites.csv` | One receiving site | Two Victorian/Australia-Melbourne sites. |
| `suppliers.csv` | One durable supplier identity | Synthetic supplier codes only. |
| `supplier_versions.csv` | One effective-dated supplier version | Display names are synthetic. |
| `products.csv` | One durable SKU | Synthetic SKU codes only. |
| `product_versions.csv` | One effective-dated SKU version | Category, ABC/XYZ class and base UOM. |
| `product_site_inventory_policies.csv` | One product-site policy version | Safety stock, criticality and substitution group. |
| `uom_conversions.csv` | One product/UOM conversion | Positive integer conversion to base `EA`. |
| `users.csv` | One simulated actor or queue | No authentication or real personal identifiers. |
| `ownership_mappings.csv` | One owner mapping rule | Reference data only. |
| `calendar_versions.csv` | One business-calendar reference | Australia/Melbourne business semantics. |
| `rule_versions.csv` | Rule metadata reference | Reference only; no scoring implemented. |
| `purchase_orders.csv` | One PO header identity | Durable source PO number. |
| `purchase_order_versions.csv` | One PO header version | Supplier, buyer group, order status and currency. |
| `purchase_order_lines.csv` | One stable PO-line identity | Canonical line key for later ingestion. |
| `purchase_order_line_aliases.csv` | One source-key alias | Preserves source PO/line references. |
| `purchase_order_line_versions.csv` | One PO-line amendment/version | Quantity, UOM, site, product, need date and status. |
| `delivery_schedules.csv` | One delivery schedule component | Split schedules reconcile to PO-line base quantity. |
| `supplier_commitment_observations.csv` | One supplier promise observation | May reference a delivery schedule from the same PO line. |
| `receipt_transactions.csv` | One as-of-visible receipt, correction or reversal | Operational source input only; `posted_at` is at or before as-of. |
| `receipt_allocations.csv` | One receipt allocation | Schedule allocations are line-consistent; line residual allocations have no schedule. |
| `future_receipt_outcomes.csv` | One post-as-of receipt realisation | Evaluation-only future evidence; not linked to an operational source load. |
| `inventory_snapshots.csv` | One product-site inventory snapshot | On-hand, allocated, available and in-transit quantities. |
| `demand_requirements.csv` | One dated demand requirement | Firm and forecast demand with demand class evidence. |
| `supplier_performance_snapshots.csv` | One supplier/site performance window | OTIF observations with sample sufficiency. |
| `scenario_registry.csv` | One controlled scenario instance | Scenario ID, type, affected line and evidence purpose. |
| `scenario_assignments.csv` | One line-to-scenario assignment | Traceability bridge for source datasets. |
| `synthetic_outcome_observations.csv` | One hidden outcome per PO line | Independent from risk scoring and lifecycle code. |
| `manifest.csv` | One exported file | Row count, schema version, file hash, seed and config hash. |

## Scenario Types

The generator includes at least one instance of each mandatory scenario type:

- overdue critical order;
- partial receipt with remaining exposure;
- supplier commitment followed by breach;
- demand shock;
- receipt correction;
- receipt reversal;
- split schedule;
- supplier deterioration;
- inventory reallocation opportunity;
- false-positive source-data correction;
- missing supplier signal;
- missing inventory signal.

## Numeric Conventions

- Quantities are exported to four decimal places.
- Money-like fields are exported to two decimal places.
- Reporting currency is `AUD`.
- Base UOM is `EA`.
- Purchase UOM values are `EA`, `CASE` or `PALLET`.

## Important Field Notes

- `scenario_ids` contains semicolon-delimited UUIDs from `scenario_registry.csv`.
- `scenario_types` contains semicolon-delimited readable scenario labels for review.
- Product-site facts such as `demand_requirements` and `inventory_snapshots` may aggregate multiple scenario UUIDs because they are not PO-line-grain datasets.
- Missing-inventory scenarios are not emitted where they would conflict with a current correction or reallocation scenario for the same product-site.
- `purchase_order_line_versions.po_supplier_id` repeats the governed PO-header supplier for validation and source-data traceability.
- `purchase_order_line_versions.unit_price_aud` and `line_value_aud` reconcile to the final or historical version quantity.
- `purchase_order_line_versions.critical_order_flag` identifies the synthetic controlled critical-order scenario and is not a risk score.
- `receipt_allocations.corrected_receipt_id` records inherited or explicit allocation target lineage for corrections and reversals.
- `receipt_allocations.allocated_base_quantity` is always non-negative; the signed transaction effect comes from `receipt_transactions.base_quantity`.
- `inventory_snapshots.corrects_snapshot_id` is populated for source-data correction scenarios.
- Future business dates can appear in planning fields such as need date, expected date, committed date, schedule date and demand requirement date.
- Observation timestamps such as receipt `posted_at`, commitment `observed_at`, inventory `snapshot_at`, source-load timestamps and effective timestamps are capped at the configured as-of timestamp.
- `future_receipt_outcomes.csv` contains post-as-of realised receipts for evaluation and uses `evaluation_only_flag = true`.
- `synthetic_outcome_observations.future_receipt_outcome_ids` links open-line outcomes to hidden future receipt realisations without adding those receipts to operational inputs.
