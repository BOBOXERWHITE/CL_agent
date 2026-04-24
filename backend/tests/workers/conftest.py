"""Worker-test fixtures.

The P4.4 changes make ``submit_ingestion`` write to ``task_run`` via
``bypass_rls_session``. Tests that exercise that path need the schema
bootstrapped — normally the FastAPI lifespan does it, but worker unit
tests don't spin up an app.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ensure_schema_for_worker_tests() -> None:
    """Bootstrap the SQLite schema so ``bypass_rls_session`` works.

    Relies on the shared ``_test_environment`` fixture in
    ``tests/conftest.py`` having already pointed ``DATABASE_URL`` at a
    per-test SQLite file.
    """
    from app.db.session import init_db

    init_db()
