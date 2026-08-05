# Power BI Reporting Layer Implementation

## Purpose

This guide explains how to apply and use the PostgreSQL reporting layer created for the read-only Power BI management report.

The approved design remains in `docs/reporting/power-bi-reporting-layer-design.md`.

## Migration

Apply all governed migrations:

```powershell
python -m alembic upgrade head
```

The reporting layer is implemented by migration:

```text
20260805_0005_power_bi_reporting_layer.py
```

It creates the dedicated PostgreSQL schema:

```text
reporting
```

The migration creates views only. It does not modify Streamlit, operational lifecycle behavior, risk rules, ingestion behavior, approval controls, suppression controls, or Power BI files.

## Reporting Objects

Dimensions:

- `reporting.dim_date`
- `reporting.dim_exception`
- `reporting.dim_site`
- `reporting.dim_supplier`
- `reporting.dim_product`
- `reporting.dim_user`
- `reporting.dim_exception_state`
- `reporting.dim_severity`
- `reporting.dim_rule_component`

Facts and accumulating snapshots:

- `reporting.rpt_exception_summary`
- `reporting.rpt_exception_events`
- `reporting.rpt_risk_assessments`
- `reporting.rpt_risk_components`
- `reporting.rpt_approvals`
- `reporting.rpt_suppressions`
- `reporting.rpt_pipeline_runs`

## Query Examples

Executive active operational workload:

```sql
select
    effective_severity,
    count(*) as active_operational_exceptions,
    sum(residual_value_aud) as residual_exposure_aud,
    count(*) filter (where residual_value_aud is null) as missing_exposure_count
from reporting.rpt_exception_summary
where is_active_operational
group by effective_severity
order by active_operational_exceptions desc;
```

Candidate risks not opened:

```sql
select
    calculated_severity,
    score_confidence,
    count(*) as candidate_risks_not_opened
from reporting.rpt_risk_assessments
where is_candidate_not_opened
group by calculated_severity, score_confidence;
```

Risk-component contribution and missing signals:

```sql
select
    component_family,
    component_code,
    availability_status,
    sum(applied_points) as applied_points,
    count(*) filter (where is_missing_signal) as missing_signal_count
from reporting.rpt_risk_components
group by component_family, component_code, availability_status
order by component_family, component_code;
```

Approval governance:

```sql
select
    request_type,
    request_status,
    count(distinct approval_request_id) as approval_requests,
    count(distinct approval_decision_id) as approval_decisions,
    count(*) filter (where is_self_approval_violation) as self_approval_violations
from reporting.rpt_approvals
group by request_type, request_status;
```

Pipeline health:

```sql
select
    run_type,
    status,
    count(*) as run_count,
    sum(source_load_count) as source_load_count,
    sum(rejected_record_count) as rejected_record_count
from reporting.rpt_pipeline_runs
group by run_type, status;
```

## Intended Power BI Relationships

Use single-direction relationships from dimensions to facts.

Recommended relationships:

| From | To |
|---|---|
| `dim_exception[episode_id]` | `rpt_exception_summary[episode_id]` |
| `dim_exception[episode_id]` | `rpt_exception_events[episode_id]` |
| `dim_exception[episode_id]` | `rpt_approvals[episode_id]` |
| `dim_exception[episode_id]` | `rpt_suppressions[episode_id]` |
| `dim_site[site_id]` | `rpt_exception_summary[site_id]` |
| `dim_supplier[supplier_id]` | `rpt_exception_summary[supplier_id]` |
| `dim_product[product_id]` | `rpt_exception_summary[product_id]` |
| `dim_user[user_id]` | `rpt_exception_summary[current_owner_user_id]` |
| `dim_exception_state[state_code]` | `rpt_exception_summary[current_state]` |
| `dim_severity[severity_code]` | `rpt_exception_summary[effective_severity]` |
| `rpt_risk_assessments[candidate_evaluation_id]` | `rpt_risk_components[candidate_evaluation_id]` |
| `rpt_pipeline_runs[pipeline_run_id]` | `rpt_risk_assessments[pipeline_run_id]` |
| `dim_rule_component[rule_component_id]` | `rpt_risk_components[rule_component_id]` |

Avoid bidirectional filtering and direct many-to-many fact relationships.

## Read-Only Access Model

Power BI should connect with a dedicated database role, for example:

```text
powerbi_reporting_reader
```

The migration grants `USAGE` on `reporting` and `SELECT` on reporting views if that role already exists. It does not create the role, because role creation is environment-specific and may require elevated database privileges.

Recommended production permissions:

- `USAGE` on schema `reporting`
- `SELECT` on all views in schema `reporting`
- no write access to operational tables
- no workflow command/function execution permissions
- no direct operational schema access unless separately approved for validation

## Known Limitations

- Active Operational Exceptions exclude `closed` and `suppressed`.
- `resolved` remains active until `closed`.
- Candidate Risk remains analytical and is not a workflow state.
- High or Critical score does not automatically imply workflow opening eligibility.
- Formal SLA breach event reporting is unavailable in the MVP because no governed SLA breach event code exists.
- SLA views expose obligation coverage and unsatisfied due timestamps for Power BI as-of measures.
- Financial exposure is AUD-only and remains NULL where value source fields are missing.
- Risk components preserve missing-signal status separately from zero applied points.
- Supplier, product, PO header, and PO line descriptors use current/latest versions; historical as-of descriptors are a future enhancement.
- Full operational JSON payloads are not exposed in the MVP reporting views.
- Power BI must remain read-only and must not operate workflow actions.
