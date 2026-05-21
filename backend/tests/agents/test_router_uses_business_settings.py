"""Verify ``choose_route`` consumes the DB-backed agent_router_provider.

Previously the router only honoured the env-bound ``AGENT_ROUTER_PROVIDER``,
so an admin had to redeploy to switch llm/embedding/keyword. The system-
settings panel now persists the provider into ``system_setting`` rows; the
router must read from that effective layer so the change is live.
"""

from __future__ import annotations

import pytest

from app.db.session import SessionLocal, init_db
from app.schemas.system_settings import EditableSystemSettings
from app.services.agents.router import (
    AgentRouteRequest,
    EmbeddingRouteStrategy,
    KeywordRouteStrategy,
    LLMRouteStrategy,
    choose_route,
)
from app.services.system_settings import update_editable_settings


@pytest.fixture()
def seeded_admin_settings() -> None:
    """Materialise the default editable-settings row so update doesn't 404."""
    init_db()


def _save_router_provider(provider: str) -> None:
    with SessionLocal() as session:
        update_editable_settings(
            session,
            EditableSystemSettings(
                default_tenant_id="default-tenant",
                default_customer_id="default-customer",
                chat_top_k=3,
                chat_confidence_threshold=0.2,
                default_eval_dataset="zh-policy-smoke",
                agent_router_provider=provider,  # type: ignore[arg-type]
            ),
            updated_by_role="admin",
        )


def test_router_uses_db_provider_keyword(
    seeded_admin_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Track which strategy the router consults first by recording
    # ``classify`` calls in order.
    seen: list[str] = []

    def _record(strategy_name: str):
        def _wrapper(self, question):  # type: ignore[no-untyped-def]
            seen.append(strategy_name)
            return KeywordRouteStrategy().classify(question)

        return _wrapper

    monkeypatch.setattr(KeywordRouteStrategy, "classify", _record("keyword"))
    monkeypatch.setattr(EmbeddingRouteStrategy, "classify", _record("embedding"))
    monkeypatch.setattr(LLMRouteStrategy, "classify", _record("llm"))

    _save_router_provider("keyword")

    choose_route(
        AgentRouteRequest(
            question="北京酒店报销上限是多少？",
            tenant_id="t1",
            customer_id="c1",
        )
    )

    # First strategy probed must be the one the operator selected.
    assert seen[0] == "keyword"


def test_router_uses_db_provider_embedding(
    seeded_admin_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def _record(strategy_name: str):
        def _wrapper(self, question):  # type: ignore[no-untyped-def]
            seen.append(strategy_name)
            # Defer to keyword so the chain still produces a valid decision
            # (we only care which strategy ran first).
            return KeywordRouteStrategy().classify(question)

        return _wrapper

    monkeypatch.setattr(KeywordRouteStrategy, "classify", _record("keyword"))
    monkeypatch.setattr(EmbeddingRouteStrategy, "classify", _record("embedding"))
    monkeypatch.setattr(LLMRouteStrategy, "classify", _record("llm"))

    _save_router_provider("embedding")

    choose_route(
        AgentRouteRequest(
            question="北京酒店报销上限是多少？",
            tenant_id="t1",
            customer_id="c1",
        )
    )

    assert seen[0] == "embedding"
