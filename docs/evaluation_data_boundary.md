# Evaluation Data Boundary

Operational ingestion is intentionally separate from future and hidden evaluation evidence.

## Excluded by Default

The normal operational command does not load:

- `future_receipt_outcomes.csv`;
- `synthetic_outcome_observations.csv`;
- `scenario_registry.csv`;
- `scenario_assignments.csv`;
- upstream `pipeline_runs.csv`.

The validator detects these files and reports `NON_OPERATIONAL_FILE_SKIPPED` warnings. This proves the files are visible to the pipeline but are outside normal operational persistence.

## Why This Boundary Matters

`future_receipt_outcomes.csv` contains post-as-of receipt realisations. Loading it into operational receipt tables would leak future facts into an earlier operational run.

`synthetic_outcome_observations.csv` contains hidden outcome labels for later evaluation. Loading it into operational source tables or features would contaminate future risk-engine testing.

Scenario registry and assignment files are generation evidence. They are not operational source facts under the current physical schema.

## Current Implementation

Default behavior is operational-only:

```powershell
python -m scecs.ingestion.cli load --input <bundle>
```

There is no `load-evaluation` command in this work package. If one is later added, it must store evaluation evidence outside operational source tables and outside future risk-engine feature inputs.

