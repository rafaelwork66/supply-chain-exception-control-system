.PHONY: install lint typecheck test test-unit test-integration db-up db-down db-health alembic-current

PYTHON ?= python

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy src tests

test:
	$(PYTHON) -m pytest

test-unit:
	$(PYTHON) -m pytest tests/unit

test-integration:
	SCECS_RUN_INTEGRATION_TESTS=1 $(PYTHON) -m pytest tests/integration

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-health:
	$(PYTHON) -m scecs.db_health

alembic-current:
	$(PYTHON) -m alembic current
