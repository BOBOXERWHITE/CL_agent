"""Tests for the P3.2 three-tier router.

Covers the chain behaviour:
- ticket payload short-circuits every strategy
- keyword strategy matches the pre-Phase-3 cases (regression)
- embedding strategy picks by cosine similarity
- LLM strategy parses a label and rejects nonsense
- a failing primary strategy falls through to the next
- chain is guaranteed to always return a decision
"""

from __future__ import annotations

import pytest

from app.services.agents.router import (
    INTENT_CATALOG,
    AgentRouteDecision,
    AgentRouteRequest,
    EmbeddingRouteStrategy,
    IntentSpec,
    KeywordRouteStrategy,
    LLMRouteStrategy,
    choose_route,
)


def _req(question: str, *, ticket: dict | None = None) -> AgentRouteRequest:
    return AgentRouteRequest(
        question=question,
        tenant_id="t1",
        customer_id="c1",
        ticket=ticket,
    )


# ---------------------------------------------------------------------------
# Structural short-circuit
# ---------------------------------------------------------------------------


def test_ticket_payload_always_routes_to_ticket_triage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any LLM / embedding decision is ignored when a ticket is present."""
    # Even if we force LLM as primary, the ticket payload wins.
    monkeypatch.setenv("AGENT_ROUTER_PROVIDER", "llm")
    from app.core.config import get_settings

    get_settings.cache_clear()

    decision = choose_route(_req("policy question", ticket={"ticket_id": "x"}))
    assert decision.agent_name == "ticket_router_agent"
    assert "ticket-payload" in decision.reason


# ---------------------------------------------------------------------------
# Keyword strategy — regression from pre-Phase-3
# ---------------------------------------------------------------------------


def test_keyword_strategy_matches_policy_terms() -> None:
    strategy = KeywordRouteStrategy()
    match = strategy.classify("酒店报销上限是多少？")
    assert match is not None
    assert match.intent == "POLICY_QA"


def test_keyword_strategy_matches_ticket_terms() -> None:
    strategy = KeywordRouteStrategy()
    match = strategy.classify("这张报销单为什么还在排队？")
    assert match is not None
    assert match.intent == "TICKET_TRIAGE"


def test_keyword_strategy_matches_anomaly_terms() -> None:
    strategy = KeywordRouteStrategy()
    match = strategy.classify("这看起来是重复预订的异常订单")
    assert match is not None
    assert match.intent == "ORDER_ANOMALY"


def test_keyword_strategy_returns_none_on_no_match() -> None:
    assert KeywordRouteStrategy().classify("completely unrelated content") is None


def test_keyword_strategy_is_case_insensitive() -> None:
    strategy = KeywordRouteStrategy()
    assert strategy.classify("Can I BOOK Business Class?").intent == "POLICY_QA"


# ---------------------------------------------------------------------------
# Embedding strategy
# ---------------------------------------------------------------------------


def test_embedding_strategy_picks_best_cosine_match() -> None:
    """Deterministic embedding: question sharing tokens with exemplar wins."""
    strategy = EmbeddingRouteStrategy(threshold=0.0)
    # The POLICY_QA exemplar mentions "酒店" and "business class";
    # this query shares those tokens so should match POLICY_QA.
    match = strategy.classify("酒店报销上限 business class")
    assert match is not None
    assert match.intent == "POLICY_QA"


def test_embedding_strategy_returns_none_below_threshold() -> None:
    strategy = EmbeddingRouteStrategy(threshold=0.99)  # impossibly high
    assert strategy.classify("anything") is None


def test_embedding_strategy_returns_none_on_compute_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding backend raising → strategy yields None, not propagating."""
    import app.services.agents.router as router_module

    def boom(_texts, _dim):
        raise RuntimeError("embedding gateway down")

    # Patch the symbol the strategy imports inside its classify() call.
    import app.services.rag.embedding_client as emb

    monkeypatch.setattr(emb, "texts_to_embeddings", boom)
    # Fresh import inside classify() will pick up the monkeypatched function.
    assert router_module.EmbeddingRouteStrategy().classify("any question") is None


# ---------------------------------------------------------------------------
# LLM strategy
# ---------------------------------------------------------------------------


class _FakeOpenAIClient:
    """Stand-in for OpenAICompatibleRewriteClient — just _chat is needed."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.base_url = "https://fake/v1"
        self.api_key = "k"
        self.model_name = "m"

    def _chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        del system, user, temperature
        return self._response


def test_llm_strategy_parses_valid_label(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.agents.router as router_module
    import app.services.llm.rewrite_client as rc

    fake = _FakeOpenAIClient("POLICY_QA")
    monkeypatch.setattr(rc, "get_rewrite_client", lambda: fake)
    # Make isinstance(fake, OpenAICompatibleRewriteClient) return True.
    monkeypatch.setattr(rc, "OpenAICompatibleRewriteClient", type(fake))
    # Also patch the import line inside the strategy.
    monkeypatch.setattr(
        router_module.LLMRouteStrategy,
        "_SYSTEM_PROMPT",
        router_module.LLMRouteStrategy._SYSTEM_PROMPT,
    )

    match = router_module.LLMRouteStrategy().classify("what can I book?")
    assert match is not None and match.intent == "POLICY_QA"


def test_llm_strategy_tolerates_punctuation_around_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.agents.router as router_module
    import app.services.llm.rewrite_client as rc

    fake = _FakeOpenAIClient("Label: `TICKET_TRIAGE`.")
    monkeypatch.setattr(rc, "get_rewrite_client", lambda: fake)
    monkeypatch.setattr(rc, "OpenAICompatibleRewriteClient", type(fake))
    match = router_module.LLMRouteStrategy().classify("my claim is stuck")
    assert match is not None and match.intent == "TICKET_TRIAGE"


def test_llm_strategy_returns_none_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.agents.router as router_module
    import app.services.llm.rewrite_client as rc

    fake = _FakeOpenAIClient("I have no idea what you mean.")
    monkeypatch.setattr(rc, "get_rewrite_client", lambda: fake)
    monkeypatch.setattr(rc, "OpenAICompatibleRewriteClient", type(fake))
    assert router_module.LLMRouteStrategy().classify("x") is None


def test_llm_strategy_skips_deterministic_client() -> None:
    """Deterministic rewrite client (test default) → strategy returns None."""
    # Default test env has LLM_PROVIDER=deterministic, so get_rewrite_client
    # returns DeterministicRewriteClient. The strategy must refuse it.
    assert LLMRouteStrategy().classify("酒店报销") is None


def test_llm_strategy_catches_upstream_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.agents.router as router_module
    import app.services.llm.rewrite_client as rc

    class _Boom:
        base_url = "https://x"
        api_key = "k"
        model_name = "m"

        def _chat(self, *_a, **_k):
            raise RuntimeError("upstream 502")

    fake = _Boom()
    monkeypatch.setattr(rc, "get_rewrite_client", lambda: fake)
    monkeypatch.setattr(rc, "OpenAICompatibleRewriteClient", _Boom)
    assert router_module.LLMRouteStrategy().classify("anything") is None


# ---------------------------------------------------------------------------
# Chain composition
# ---------------------------------------------------------------------------


def test_chain_falls_through_to_keyword_when_primary_defers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force primary=llm (deterministic client → defers); the next tier
    must produce *some* decision (keyword strategy always succeeds for
    questions whose terms appear in the keyword list).

    We pick a query that keyword matches unambiguously -- embedding with
    the deterministic backend is noisy enough that it can pick a
    neighbour intent. That's a known limitation of the hash embedding
    in tests; real embedding models separate intents more cleanly.
    """
    monkeypatch.setenv("AGENT_ROUTER_PROVIDER", "llm")
    from app.core.config import get_settings

    get_settings.cache_clear()
    decision = choose_route(_req("异常订单 重复预订"))
    assert decision.agent_name == "order_anomaly_agent"


def test_chain_always_returns_decision_even_for_unknown_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Noisy question that matches no keyword must still route somewhere."""
    monkeypatch.setenv("AGENT_ROUTER_PROVIDER", "keyword")
    from app.core.config import get_settings

    get_settings.cache_clear()
    decision = choose_route(_req("wholly unrelated nonsense"))
    assert isinstance(decision, AgentRouteDecision)
    # Default intent is policy_qa; embedding may route elsewhere.
    assert decision.agent_name.endswith("_agent")


def test_chain_reports_strategy_name_in_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ROUTER_PROVIDER", "keyword")
    from app.core.config import get_settings

    get_settings.cache_clear()
    decision = choose_route(_req("酒店报销上限"))
    assert "keyword" in decision.reason or "embedding" in decision.reason


def test_invalid_provider_config_falls_back_to_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_ROUTER_PROVIDER", "nonexistent_provider")
    from app.core.config import get_settings

    get_settings.cache_clear()
    decision = choose_route(_req("酒店"))
    assert decision.agent_name == "travel_policy_agent"


# ---------------------------------------------------------------------------
# Intent catalog static invariants
# ---------------------------------------------------------------------------


def test_intent_catalog_all_specs_have_required_fields() -> None:
    for spec in INTENT_CATALOG:
        assert isinstance(spec, IntentSpec)
        assert spec.intent and spec.agent_name and spec.route_name
        assert spec.exemplar
        assert spec.keywords
