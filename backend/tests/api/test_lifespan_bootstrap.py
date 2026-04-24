"""Verify that schema bootstrap and default-rule seeding run exactly once
per application lifespan, not on every request.

Rationale: P0.4 moved ``init_db()`` + ``seed_default_rules()`` out of
per-request route handlers into the FastAPI lifespan hook. If a later
refactor accidentally re-introduces the old behaviour, this test catches it.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def patched_app() -> Iterator[tuple[TestClient, list[str]]]:
    """Track every call into ``seed_default_rules`` for the app under test."""
    call_log: list[str] = []

    import app.main as main_module
    import app.services.rules.engine as rules_engine

    original_seed = rules_engine.seed_default_rules

    def tracking_seed(session):  # type: ignore[no-untyped-def]
        call_log.append("seed")
        return original_seed(session)

    # Patch both in the defining module and in the consumer module because
    # ``create_app`` imported the symbol at module load time.
    with (
        patch.object(rules_engine, "seed_default_rules", tracking_seed),
        patch.object(main_module, "seed_default_rules", tracking_seed),
    ):
        client = TestClient(main_module.create_app())
        with client:
            yield client, call_log


def test_seed_runs_exactly_once_at_startup(patched_app) -> None:
    client, call_log = patched_app
    # After TestClient context manager enter, lifespan startup has finished.
    assert len(call_log) == 1


def test_many_requests_do_not_retrigger_seed(patched_app) -> None:
    client, call_log = patched_app
    # Hit a handful of endpoints that used to call seed_default_rules
    # themselves (agents and rules routes).
    for _ in range(5):
        client.get("/api/rules")
    assert len(call_log) == 1, (
        f"seed_default_rules should only fire at startup but was called {len(call_log)} times"
    )
