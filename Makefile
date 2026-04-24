.PHONY: backend-install frontend-install \
        test-backend test-backend-full test-integration test-frontend test \
        db-migrate db-rollback db-revision db-stamp-baseline \
        lint typecheck format pre-commit-install pre-commit-run

backend-install:
	cd backend && python -m pip install -e ".[dev]"

frontend-install:
	cd frontend && npm install

# Fast unit tests (SQLite + noop adapters). Default CI target.
test-backend:
	cd backend && pytest tests/api/test_health.py -q

# All unit tests (integration still excluded by pyproject addopts).
test-backend-full:
	cd backend && pytest -q

# Integration tests only. Requires Docker Desktop running.
# Spins up ephemeral Postgres + MinIO via testcontainers.
test-integration:
	cd backend && pytest -m integration -q

test-frontend:
	cd frontend && npm test -- --run tests/app/App.test.tsx

test: test-backend test-frontend

# --- Database migrations (Alembic) ---------------------------------------
# Requires a running PostgreSQL (e.g., `docker compose up -d postgres`).
# DATABASE_URL is read by backend/alembic/env.py from app settings.

db-migrate:
	cd backend && alembic upgrade head

db-rollback:
	cd backend && alembic downgrade -1

# Usage: make db-revision m="add foo column"
db-revision:
	@if [ -z "$(m)" ]; then \
		echo "Usage: make db-revision m=\"short message\""; exit 1; \
	fi
	cd backend && alembic revision --autogenerate -m "$(m)"

# Mark a legacy DB (created via old init_db) as already at baseline.
# Run this exactly once on DBs that predate Alembic.
db-stamp-baseline:
	cd backend && alembic stamp 0001_baseline

# --- Code quality -------------------------------------------------------
# Configuration is in backend/pyproject.toml ([tool.ruff] and [tool.mypy]).

lint:
	cd backend && ruff check .

format:
	cd backend && ruff format . && ruff check --fix .

typecheck:
	cd backend && mypy

pre-commit-install:
	pre-commit install

pre-commit-run:
	pre-commit run --all-files
