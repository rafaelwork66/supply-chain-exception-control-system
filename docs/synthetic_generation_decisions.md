# Synthetic Generation Decisions

## Decisions

| Decision | Rationale |
| --- | --- |
| Use CSV rather than Parquet for committed fixtures. | Keeps dependencies minimal and avoids adding `pyarrow` or `pandas` at this stage. |
| Use stable UUIDv5 identifiers. | Supports deterministic file hashes across repeated runs. |
| Exclude output path from the configuration hash. | Moving the same generated evidence to another folder must not change dataset identity. |
| Use named random streams. | Prevents a change in one generator domain from silently changing all downstream domains. |
| Keep latent supplier archetypes out of exported supplier master data. | Governing documents require hidden outcome factors to remain separate from scoring inputs. |
| Generate outcomes in a separate module with no score or severity inputs. | Preserves the independent outcome contract. |
| Commit only a CI-sized sample fixture. | Full portfolio data is reproducible but too large for routine Git review. |
| Treat late receipt rate as measured evidence, not a forced target. | The governing expected-distribution table specifies many control ranges but does not define a hard late-receipt event range. |
| Store scenario UUIDs in operational datasets. | Prevents ambiguous label-only traceability and allows validation against `scenario_registry.csv`. |
| Add readable `scenario_types` beside `scenario_ids`. | Keeps files reviewable without weakening UUID-based lineage. |
| Choose one supplier per PO header. | Matches purchase-order semantics and prevents mixed-supplier orders. |
| Allocate corrections and reversals. | Ensures no receipt quantity disappears and signed effects remain explicit in receipt transactions. |
| Generate supplier performance from receipt history with prior/noise. | Reconciles performance observations to generated history without making them perfectly predictive. |
| Aggregate scenario UUIDs on product-site demand and inventory rows. | Demand and inventory are not PO-line-grain facts, so shared product-site scenarios need row-level UUID aggregation to remain traceable. |
| Prune incompatible missing-inventory assignments. | Missing inventory means no current product-site inventory row, so it cannot coexist with correction or reallocation scenarios at that same product-site grain. |

## Deferred

- Risk-priority scoring.
- Candidate-risk evaluation.
- Exception creation.
- Exception lifecycle services.
- Streamlit screens.
- Notifications.
- Power BI model.
- AI recommendations.
- Database ingestion into operational tables.
- Scheduled GitHub Actions data generation.

## Known Simplifications

- Inventory is generated as an operational snapshot and short forward demand buckets, not a full daily inventory ledger.
- Product-site inventory can contain separate stale, current and correction rows when multiple scenario types collide at the same product-site.
- Supplier performance is reconciled against generated receipt history with latent priors and noise, so it is directional but not perfectly predictive.
- Scenario injection changes operational facts and observations but does not prescribe future score or exception labels.
- The full-profile evidence is generated locally and stored as summary documentation; bulk CSVs remain ignored.
