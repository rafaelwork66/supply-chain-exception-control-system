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
- Supplier performance is generated from hidden archetypes and observed samples, not recalculated from every receipt event.
- Scenario injection changes operational facts and observations but does not prescribe future score or exception labels.
- The full-profile evidence is generated locally and stored as summary documentation; bulk CSVs remain ignored.
