# Data Quality and Rejection Codes

The ingestion pipeline applies two validation stages.

Stage A validates the bundle, manifest and each record contract. Stage B validates cross-dataset and database-oriented controls before publication.

## Classifications

| Classification | Meaning |
| --- | --- |
| `bundle-blocking` | The whole bundle is unsafe to load or publish. |
| `dataset-blocking` | One dataset has a structural or relationship defect that blocks publication. |
| `record-rejectable` | One row has an invalid value. The row is not accepted. |
| `warning-only` | The issue is visible but does not block operational validation. |

## Current Rejection Codes

| Code | Classification | Meaning |
| --- | --- | --- |
| `BUNDLE_NOT_FOUND` | Bundle-blocking | Input path is missing or is not a directory. |
| `MISSING_CONTROL_FILE` | Bundle-blocking | Required control file is missing. |
| `INVALID_MANIFEST_ROW` | Bundle-blocking | Manifest row cannot be parsed. |
| `UNDECLARED_FILE` | Bundle-blocking or warning | A CSV exists outside the manifest. Evaluation-only files are warning-only. |
| `UNAPPROVED_DATASET` | Bundle-blocking | Manifest references a dataset outside governed scope. |
| `GENERATOR_VERSION_MISMATCH` | Bundle-blocking | Generator version differs from the approved version. |
| `SCHEMA_VERSION_MISMATCH` | Bundle-blocking | Schema version differs from `synthetic-source-v1`. |
| `PATH_TRAVERSAL` | Bundle-blocking | Manifest file name resolves outside the selected bundle path. |
| `MISSING_DATASET_FILE` | Bundle-blocking | Manifest declares a missing CSV. |
| `FILE_HASH_MISMATCH` | Bundle-blocking | CSV hash differs from manifest. |
| `ROW_COUNT_MISMATCH` | Bundle-blocking | Actual CSV rows differ from manifest. |
| `INCONSISTENT_MANIFEST_METADATA` | Bundle-blocking | Manifest rows disagree on generator, schema, config or as-of metadata. |
| `MISSING_OPERATIONAL_DATASET` | Bundle-blocking | Required operational dataset is absent. |
| `NON_OPERATIONAL_FILE_SKIPPED` | Warning-only | Evaluation-only or non-operational evidence is detected and skipped by operational ingestion. |
| `MISSING_REQUIRED_COLUMN` | Dataset-blocking | A required source column is absent. |
| `UNDECLARED_COLUMN` | Dataset-blocking | A source column is not in the contract. |
| `INVALID_FIELD_VALUE` | Record-rejectable | Value fails UUID, date, timestamp, decimal, integer, boolean, JSON or allowed-code parsing. |
| `FOREIGN_KEY_MISSING` | Dataset-blocking | A child row references a missing parent row. |
| `POST_AS_OF_OPERATIONAL_TIMESTAMP` | Dataset-blocking | Operational observation timestamp is after the configured as-of timestamp. |
| `MULTI_SUPPLIER_PO` | Dataset-blocking | A PO has more than one supplier. |
| `SCHEDULE_LINE_QUANTITY_MISMATCH` | Dataset-blocking | Schedules do not reconcile to final PO-line base quantity. |
| `LINE_RESIDUAL_HAS_SCHEDULE` | Dataset-blocking | Line-residual receipt allocation incorrectly references a schedule. |
| `SCHEDULE_BUCKET_MISSING_SCHEDULE` | Dataset-blocking | Schedule receipt allocation has no schedule. |
| `RECEIPT_SCHEDULE_LINE_MISMATCH` | Dataset-blocking | Receipt and schedule belong to different PO lines. |
| `RECEIPT_ALLOCATION_MISMATCH` | Dataset-blocking | Receipt allocations do not reconcile to absolute receipt quantity. |
| `COMMITMENT_SCHEDULE_LINE_MISMATCH` | Dataset-blocking | Commitment and schedule belong to different PO lines. |

Rejected values are represented safely. The governed database table stores rejection metadata, not credentials, secrets or binary payloads.

