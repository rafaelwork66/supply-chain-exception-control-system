# Supply Chain Exception Control System

Technical foundation for a portfolio project that supports governed supply-chain exception monitoring, PostgreSQL storage, deterministic risk scoring, core workflow services, a Streamlit operational MVP, GitHub Actions, and later Power BI reporting.

The repository includes the development baseline, governed physical PostgreSQL schema, synthetic data generation, ingestion controls, deterministic risk scoring, core exception workflow services, and a Streamlit operational MVP. It does not implement notifications, Power BI models, real authentication, scheduled processing, deployment infrastructure, or AI features.

## Project Structure

```text
supply-chain-exception-control-system/
+-- app/
|   +-- streamlit_app.py
+-- src/scecs/
|   +-- __init__.py
|   +-- config.py
|   +-- database.py
|   +-- db_health.py
|   +-- logging_config.py
|   +-- models/
|   +-- streamlit_app/
+-- tests/
|   +-- unit/
|   +-- integration/
+-- sql/migrations/
|   +-- env.py
|   +-- script.py.mako
|   +-- versions/
+-- data/
|   +-- sample/
|   +-- rejected/
+-- docs/
|   +-- governing/
|   +-- design/
+-- powerbi/
+-- scripts/
+-- .github/workflows/
```

## What This Foundation Provides

- Python 3.12 project configuration
- Environment-variable based settings
- Structured application logging
- PostgreSQL 16 local development with Docker Compose
- SQLAlchemy 2.x engine and transaction-safe session helpers
- Alembic migration infrastructure with the first governed physical PostgreSQL schema
- Governed synthetic-source ingestion, validation, rejection, reconciliation, and publication controls
- Deterministic risk-priority scoring
- Core exception workflow services with immutable event history
- Streamlit operational MVP for control tower, queue, detail, governed actions, audit history, and pipeline health
- Pytest test setup
- Ruff linting
- Mypy type checking
- GitHub Actions CI workflow with a PostgreSQL service container
- Safe `.env.example` file without secrets
- Deterministic synthetic source-data generator with a small committed sample fixture

## Windows PowerShell Setup

From a clean checkout:

```powershell
git clone <your-github-repository-url>
cd supply-chain-exception-control-system
```

Check whether Python 3.12 is available through the Windows Python launcher:

```powershell
py -3.12 --version
```

Also check whether the ordinary `python` command is available:

```powershell
python --version
```

If `python` is not found but `py -3.12` works, use `py -3.12` to create the virtual environment. Do not change your system PATH automatically from this project.

Create and activate a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

After activation, install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env`. It is ignored because it may contain secrets in later stages.

Verify the local tooling:

```powershell
.\scripts\verify_environment.ps1
```

If PowerShell blocks local scripts because of execution policy, run the same check with a process-level bypass:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_environment.ps1
```

## PostgreSQL Local Development

Start PostgreSQL 16:

```powershell
docker compose up -d postgres
```

Check the database health from Python:

```powershell
$env:SCECS_ENVIRONMENT="development"
$env:SCECS_DB_HOST="localhost"
$env:SCECS_DB_PORT="5432"
$env:SCECS_DB_NAME="scecs_dev"
$env:SCECS_DB_USER="scecs_user"
$env:SCECS_DB_PASSWORD="scecs_password"
python -m scecs.db_health
```

Stop the local database:

```powershell
docker compose down
```

The Docker Compose password is a local development value only. Real secrets must stay outside Git.

## Governing Documents

The governing source documents are stored under `docs/governing/`. The operational application design document and physical schema note are stored under `docs/design/`.

The Test and Evidence Strategy is present as `docs/governing/06_test_and_evidence_strategy_v1.0.docx` because the provided source bundle contained a DOCX file for that document.

Physical schema support documents:

- `docs/design/physical_schema_v1.0.md`
- `docs/design/schema_decision_log.md`
- `docs/design/schema_summary.mmd`

Synthetic data support documents:

- `docs/synthetic_data_generator.md`
- `docs/synthetic_data_dictionary.md`
- `docs/synthetic_generation_decisions.md`
- `docs/synthetic_quality_report.md`

Ingestion support documents:

- `docs/ingestion_pipeline.md`
- `docs/source_to_target_mapping.md`
- `docs/data_quality_and_rejection_codes.md`
- `docs/ingestion_reconciliation_report.md`
- `docs/evaluation_data_boundary.md`

## Alembic Migrations

Alembic is configured for PostgreSQL. The first migration creates the physical schema only; it does not implement business rules, lifecycle services, scoring services, notification sending, or AI.

Check the current migration state:

```powershell
python -m alembic current
```

Apply migrations to the configured local PostgreSQL database:

```powershell
python -m alembic upgrade head
```

## Development Commands

Run all local tests. PostgreSQL integration tests are skipped unless explicitly enabled:

```powershell
python -m pytest
```

Run only unit tests:

```powershell
python -m pytest tests/unit
```

Run integration tests after PostgreSQL is running and database environment variables are set:

```powershell
$env:SCECS_RUN_INTEGRATION_TESTS="1"
python -m pytest tests/integration
```

If `SCECS_RUN_INTEGRATION_TESTS` is not set to `1`, local integration tests are skipped. CI enables this variable and runs the tests against a PostgreSQL 16 service container.

Run linting:

```powershell
python -m ruff check .
```

Run type checking:

```powershell
python -m mypy src tests
```

## Synthetic Source Data

The synthetic generator creates deterministic, portfolio-safe source datasets for later ingestion work. It does not implement risk scoring, candidate-risk evaluation, exception creation, lifecycle services, Streamlit, notifications, Power BI or AI.

Generate the small CI-sized sample fixture:

```powershell
python -m scecs.synthetic.cli generate --profile ci --output data/sample/synthetic_ci
python -m scecs.synthetic.cli validate --profile ci --output data/sample/synthetic_ci
python -m scecs.synthetic.cli summarise --profile ci --output data/sample/synthetic_ci
```

Generate the full portfolio baseline locally:

```powershell
python -m scecs.synthetic.cli generate --profile portfolio --output data/generated/portfolio_baseline
python -m scecs.synthetic.cli validate --profile portfolio --output data/generated/portfolio_baseline
python -m scecs.synthetic.cli summarise --profile portfolio --output data/generated/portfolio_baseline --write-doc docs/synthetic_quality_report.md
```

`data/generated/` is ignored by Git. Do not commit full generated datasets unless explicitly approved.

## Operational Ingestion

The ingestion pipeline loads operational synthetic source datasets into governed PostgreSQL tables. It does not implement risk scoring, candidate-risk evaluation, exception creation, lifecycle services, Streamlit, notifications, Power BI, AI, or scheduled processing.

Inspect and validate the committed CI fixture without a database:

```powershell
python -m scecs.ingestion.cli inspect --input data/sample/synthetic_ci
python -m scecs.ingestion.cli validate --input data/sample/synthetic_ci
python -m scecs.ingestion.cli mapping
```

Load a validated operational bundle after PostgreSQL is running and database environment variables are set:

```powershell
python -m alembic upgrade head
python -m scecs.ingestion.cli load --input data/sample/synthetic_ci
python -m scecs.ingestion.cli status --run-reference <run>
python -m scecs.ingestion.cli reconcile --run-reference <run>
```

Default ingestion is operational-only. It detects but does not load `future_receipt_outcomes.csv`, `synthetic_outcome_observations.csv`, scenario registry files, or upstream generator `pipeline_runs.csv`.

Verify package installation from a clean checkout:

```powershell
python -m pip install .
```

For normal development, prefer `python -m pip install -r requirements.txt` because it installs the package in editable mode plus the test, lint, and type-check tools.

## Streamlit Operational MVP

The Streamlit application connects the existing PostgreSQL models, ingestion controls, risk engine, and governed workflow service into an operational MVP. It does not reimplement business rules in the UI. Lifecycle writes call `scecs.workflow.service` through the Streamlit action wrapper.

The app includes:

- Control Tower;
- Exception Queue;
- Exception Detail;
- assignment and investigation;
- action agreement and monitoring;
- resolution, closure, suppression, and approval controls;
- immutable audit history;
- pipeline health.

Role switching is simulated for portfolio demonstration only. The app displays:

```text
Simulation only - not production authentication.
```

The simulated actor and approver lists come from active human users in PostgreSQL. This is not real authentication or authorization infrastructure.

Prepare a local database:

```powershell
docker compose up -d postgres
$env:SCECS_ENVIRONMENT="development"
$env:SCECS_DB_HOST="localhost"
$env:SCECS_DB_PORT="5432"
$env:SCECS_DB_NAME="scecs_dev"
$env:SCECS_DB_USER="scecs_user"
$env:SCECS_DB_PASSWORD="scecs_password"
python -m alembic upgrade head
```

Load the committed sample operational data:

```powershell
python -m scecs.ingestion.cli load --input data/sample/synthetic_ci
```

Score operational candidates:

```powershell
python -c "from datetime import UTC, datetime; from scecs.risk.service import score_operational_candidates; print(score_operational_candidates(as_of=datetime(2026, 6, 30, 18, 0, tzinfo=UTC), run_reference='STREAMLIT-DEMO-RISK'))"
```

If the app has no exceptions yet, use the Control Tower opening-eligible candidate section to open sample exceptions from governed candidates. The opening command calls the workflow service and records immutable event history.

Launch Streamlit:

```powershell
python -m streamlit run app/streamlit_app.py
```

Safe empty states are shown when the database has no publication, pipeline runs, candidates, or exceptions.

## GitHub Actions Setup

The CI workflow is stored in `.github/workflows/ci.yml`. GitHub Actions will run on pushes and pull requests targeting `main`.

The workflow:

- checks out the repository;
- installs Python 3.12;
- installs dependencies from `requirements.txt`;
- runs Ruff;
- runs mypy;
- runs unit tests;
- starts a PostgreSQL 16 service container;
- runs the database health check;
- runs PostgreSQL integration tests, including the migration-based schema constraint check.

The CI database uses local service-container credentials only:

```text
SCECS_ENVIRONMENT=test
SCECS_DB_HOST=localhost
SCECS_DB_PORT=5432
SCECS_DB_NAME=scecs_test
SCECS_DB_USER=scecs_user
SCECS_DB_PASSWORD=scecs_password
SCECS_RUN_INTEGRATION_TESTS=1
```

No GitHub repository secrets are required for the current foundation stage.

## Optional Makefile Commands

A `Makefile` is included for macOS, Linux, Git Bash, WSL, or developers who already use Make. Windows PowerShell users can use the commands above directly.

| Make command | PowerShell equivalent |
| --- | --- |
| `make install` | `python -m pip install -r requirements.txt` |
| `make lint` | `python -m ruff check .` |
| `make typecheck` | `python -m mypy src tests` |
| `make test-unit` | `python -m pytest tests/unit` |
| `make test-integration` | `$env:SCECS_RUN_INTEGRATION_TESTS="1"; python -m pytest tests/integration` |
| `make db-up` | `docker compose up -d postgres` |
| `make db-down` | `docker compose down` |
| `make db-health` | `python -m scecs.db_health` |

## Configuration

The application reads configuration from environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCECS_ENVIRONMENT` | `development` | Runtime environment name |
| `SCECS_LOG_LEVEL` | `INFO` | Application log level |
| `SCECS_APP_NAME` | `Supply Chain Exception Control System` | Display/application name |
| `SCECS_DB_HOST` | Required for database commands | PostgreSQL host |
| `SCECS_DB_PORT` | Required for database commands | PostgreSQL port |
| `SCECS_DB_NAME` | Required for database commands | PostgreSQL database name |
| `SCECS_DB_USER` | Required for database commands | PostgreSQL username |
| `SCECS_DB_PASSWORD` | Required for database commands | PostgreSQL password |

Database commands fail clearly when required database settings are absent. They also refuse to run when `SCECS_ENVIRONMENT` is `production` or when the database name appears to be a production database.

## Business Analyst Value

This foundation is useful because analytics projects need repeatable setup, clean configuration, test coverage, and automated quality checks before business logic is added. For a portfolio project, this shows recruiters that the project is structured like a professional analytics application, not just a notebook.
