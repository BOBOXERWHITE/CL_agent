"""Agent router (P3.2).

The router picks *which agent* handles an incoming question. Pre-Phase-3
it did one thing: substring-match a hand-maintained keyword list. That's
OK for a demo and terrible as soon as domain vocabulary drifts.

This version keeps the keyword logic as the **safety net** and adds two
better strategies on top:

- **``llm``** – ask the LLM to classify the intent. One short chat-
  completion, no retrieval. Handles paraphrases / new terminology /
  multilingual phrasing without new keyword entries.
- **``embedding``** – embed the question + three intent exemplars,
  pick argmax cosine. No LLM tokens spent, works offline with the
  deterministic embedding in tests.
- **``keyword``** – pre-Phase-3 behaviour, verbatim. Always runs as the
  final fallback so the router is guaranteed to return something.

Strategies are chained: the selected primary runs first; if it can't
decide (LLM down, embedding empty, exception…), we drop down to
``embedding``, then ``keyword``. One branch always succeeds.

One structural short-circuit survives: if the request carries a
``ticket`` payload, route straight to the ticket agent without asking
any strategy. A user who submits a ticket is always triaging it.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API types — unchanged from pre-Phase-3 so callers don't break.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentRouteRequest:
    question: str
    tenant_id: str
    customer_id: str
    run_id: str | None = None
    thread_id: str | None = None
    user_id: str | None = None
    ticket: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentRouteDecision:
    agent_name: str
    route_name: str
    reason: str
    requires_human_review: bool
    domain: str = "generic"
    specialist: str = ""
    confidence: float = 1.0
    fallback_reason: str | None = None


# ---------------------------------------------------------------------------
# Intent catalog
# ---------------------------------------------------------------------------
#
# Three intents, each bound to an agent. The exemplar sentences feed
# the embedding strategy; the label strings are what the LLM must
# return verbatim. If we add a new intent later, extend this tuple
# and provide one exemplar plus one keyword set -- that's the full
# surface area for a new agent.


@dataclass(frozen=True)
class IntentSpec:
    intent: str
    agent_name: str
    route_name: str
    reason: str
    requires_human_review: bool
    exemplar: str  # a canonical sentence the embedding strategy matches against
    keywords: Sequence[str]


INTENT_CATALOG: tuple[IntentSpec, ...] = (
    IntentSpec(
        intent="TICKET_TRIAGE",
        agent_name="ticket_router_agent",
        route_name="ticket_triage",
        reason="检测到工单或审核排队语义，转入工单分流 Agent。",
        requires_human_review=True,
        exemplar="这张报销单为什么还在排队、卡在审批环节？",
        keywords=("工单", "报销单", "排队", "拦截", "审批", "ticket"),
    ),
    IntentSpec(
        intent="ORDER_ANOMALY",
        agent_name="order_anomaly_agent",
        route_name="order_anomaly",
        reason="检测到订单异常语义，转入异常订单 Agent。",
        requires_human_review=True,
        exemplar="这是异常订单，存在重复预订或疑似欺诈交易。",
        keywords=("异常订单", "重复预订", "重复下单", "duplicate booking"),
    ),
    IntentSpec(
        intent="POLICY_QA",
        agent_name="policy_supervisor_agent",
        route_name="policy_qa",
        reason="检测到政策问答语义，转入政策问答 Agent。",
        requires_human_review=False,
        exemplar="差旅政策里酒店报销上限是多少？可以坐 business class 吗？",
        keywords=(
            "政策",
            "报销",
            "酒店",
            "住宿",
            "机票",
            "舱位",
            "差旅",
            "business class",
            "economy class",
        ),
    ),
)

# Fallback intent when no strategy picks anything. Pre-Phase-3 default
# was "travel_policy_agent" so policy is the neutral catch-all.
_DEFAULT_INTENT: IntentSpec = INTENT_CATALOG[-1]

# Legacy exports kept so older tests that `from router import POLICY_KEYWORDS` still work.
POLICY_KEYWORDS: tuple[str, ...] = tuple(
    next(s for s in INTENT_CATALOG if s.intent == "POLICY_QA").keywords
)
TICKET_KEYWORDS: tuple[str, ...] = tuple(
    next(s for s in INTENT_CATALOG if s.intent == "TICKET_TRIAGE").keywords
)
ANOMALY_KEYWORDS: tuple[str, ...] = tuple(
    next(s for s in INTENT_CATALOG if s.intent == "ORDER_ANOMALY").keywords
)


def _spec_for_intent(intent: str) -> IntentSpec | None:
    for spec in INTENT_CATALOG:
        if spec.intent == intent:
            return spec
    return None


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


class RouteStrategy(ABC):
    """Return the chosen ``IntentSpec`` or ``None`` to defer to the next strategy."""

    name: str = ""

    @abstractmethod
    def classify(self, question: str) -> IntentSpec | None: ...


class KeywordRouteStrategy(RouteStrategy):
    """Legacy substring match. Runs offline; always deterministic."""

    name = "keyword"

    def classify(self, question: str) -> IntentSpec | None:
        normalized = question.lower()
        for spec in INTENT_CATALOG:
            if any(keyword.lower() in normalized for keyword in spec.keywords):
                return spec
        return None


class EmbeddingRouteStrategy(RouteStrategy):
    """Cosine similarity between the question embedding and each intent
    exemplar. Uses whatever ``EMBEDDING_PROVIDER`` is configured; even the
    deterministic hash embedding gives usable lexical-overlap similarity
    for tests.

    We embed exemplars *at every call* rather than caching at startup
    because swapping ``EMBEDDING_MODEL_NAME`` between tests invalidates
    a cache and cache keys depend on ``get_active_embedding_profile``.
    The call is one batched embedding of 4 strings -- cheap relative to
    the agent flow it's gating.
    """

    name = "embedding"

    def __init__(self, *, threshold: float = 0.05) -> None:
        # Minimum cosine similarity to accept a match. Below threshold we
        # return ``None`` so the chain falls through to keyword match.
        self._threshold = threshold

    def classify(self, question: str) -> IntentSpec | None:
        try:
            from app.core.config import get_settings
            from app.services.rag.embedding_client import texts_to_embeddings
        except Exception as exc:  # pragma: no cover - defensive import
            _log.warning("router_embedding_import_failed", extra={"error": str(exc)})
            return None

        settings = get_settings()
        dim = settings.embedding_dimension
        exemplars = [spec.exemplar for spec in INTENT_CATALOG]
        try:
            vectors = texts_to_embeddings([question, *exemplars], dim)
        except Exception as exc:
            _log.warning("router_embedding_compute_failed", extra={"error": str(exc)})
            return None

        if len(vectors) != len(INTENT_CATALOG) + 1:
            return None

        query_vec = vectors[0]
        best_spec: IntentSpec | None = None
        best_score = -1.0
        for spec, vec in zip(INTENT_CATALOG, vectors[1:], strict=True):
            score = _cosine(query_vec, vec)
            if score > best_score:
                best_score = score
                best_spec = spec

        if best_spec is None or best_score < self._threshold:
            return None
        return best_spec


class LLMRouteStrategy(RouteStrategy):
    """Prompt-based intent classifier.

    We reuse the Phase-2 ``rewrite_client`` — it already encapsulates the
    OpenAI-compatible chat-completions adapter with fail-fast config
    checks. The system prompt pins the expected output (one of three
    labels, verbatim). Any non-matching response → ``None`` so the
    chain falls through.

    The client's ``paraphrase`` / ``generate_hyde_document`` methods
    take (question, n) / (question,) respectively. For intent we'd
    normally add a third method, but that bloats the interface for
    every downstream consumer. Instead we call the private ``_chat``
    helper directly here -- the coupling is localised and stable.
    """

    name = "llm"

    _SYSTEM_PROMPT = (
        "You classify the user's question into one intent. "
        "Return EXACTLY one of these labels, nothing else: "
        "TICKET_TRIAGE, ORDER_ANOMALY, POLICY_QA."
    )

    def classify(self, question: str) -> IntentSpec | None:
        try:
            from app.services.llm.rewrite_client import (
                DeterministicRewriteClient,
                OpenAICompatibleRewriteClient,
                get_rewrite_client,
            )
        except Exception as exc:  # pragma: no cover - defensive import
            _log.warning("router_llm_import_failed", extra={"error": str(exc)})
            return None

        try:
            client = get_rewrite_client()
        except Exception as exc:
            _log.warning("router_llm_client_unavailable", extra={"error": str(exc)})
            return None

        # Deterministic client intentionally refuses to play: fall through
        # to embedding. The LLM strategy exists for real LLMs only.
        if isinstance(client, DeterministicRewriteClient):
            return None

        # We need a plain chat call; OpenAICompatibleRewriteClient exposes
        # ``_chat`` which fits. Guarding with the type check keeps this
        # file from leaking into unexpected client types.
        if not isinstance(client, OpenAICompatibleRewriteClient):
            return None

        try:
            response = client._chat(self._SYSTEM_PROMPT, question, temperature=0.0)
        except Exception as exc:
            _log.warning("router_llm_chat_failed", extra={"error": str(exc)})
            return None

        label = response.strip().upper()
        # Be forgiving about surrounding punctuation / markdown the LLM
        # sometimes adds: pull any known label out of the string.
        for spec in INTENT_CATALOG:
            if spec.intent in label:
                return spec
        return None


# ---------------------------------------------------------------------------
# Strategy chain
# ---------------------------------------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _build_chain(primary: str) -> list[RouteStrategy]:
    """Assemble strategies in the required fall-through order.

    The keyword strategy always tail-calls so the chain is guaranteed to
    produce a decision. Duplicates are removed (e.g. primary=keyword
    doesn't get the keyword strategy again).
    """
    pool: dict[str, RouteStrategy] = {
        "llm": LLMRouteStrategy(),
        "embedding": EmbeddingRouteStrategy(),
        "keyword": KeywordRouteStrategy(),
    }
    # Start with the primary, then append the non-primary ones in order.
    order: list[str] = [primary] if primary in pool else ["keyword"]
    for fallback in ("embedding", "keyword"):
        if fallback not in order:
            order.append(fallback)
    return [pool[name] for name in order]


def _decision_from_spec(spec: IntentSpec, *, via: str) -> AgentRouteDecision:
    domain = "policy"
    if spec.intent == "TICKET_TRIAGE":
        domain = "ticket"
    elif spec.intent == "ORDER_ANOMALY":
        domain = "anomaly"
    return AgentRouteDecision(
        agent_name=spec.agent_name,
        route_name=spec.route_name,
        reason=f"{spec.reason}（路由策略：{via}）",
        requires_human_review=spec.requires_human_review,
        domain=domain,
        specialist=spec.agent_name,
        confidence=1.0,
    )


def choose_route(request: AgentRouteRequest) -> AgentRouteDecision:
    """Pick an agent for this request.

    Decision priority:
    1. Structural: ``ticket`` payload → ticket_triage, no matter what.
    2. Primary strategy (per ``AGENT_ROUTER_PROVIDER``).
    3. Fallback strategies in fixed order.
    4. Default intent (``POLICY_QA``) as the last resort.
    """
    # 1. Structural short-circuit.
    if request.ticket is not None:
        spec = _spec_for_intent("TICKET_TRIAGE")
        assert spec is not None  # static invariant
        return _decision_from_spec(spec, via="ticket-payload")

    # 2 + 3. Run the strategy chain.
    # Resolve the primary strategy from DB-backed business settings so the
    # operator can switch llm/embedding/keyword from the System Settings
    # page without redeploying. Fall back to the env-bound value if the
    # business-settings layer is unavailable for any reason (e.g. the DB
    # was just initialised in a unit test).
    primary_provider: str
    try:
        from app.services.system_settings import get_effective_business_settings

        primary_provider = get_effective_business_settings().agent_router_provider
    except Exception as exc:
        _log.warning(
            "router_effective_settings_unavailable",
            extra={"error": str(exc)},
        )
        primary_provider = get_settings().agent_router_provider
    chain = _build_chain(primary_provider)
    for strategy in chain:
        try:
            matched = strategy.classify(request.question)
        except Exception as exc:
            _log.warning(
                "router_strategy_raised",
                extra={"strategy": strategy.name, "error": str(exc)},
            )
            continue
        if matched is not None:
            return _decision_from_spec(matched, via=strategy.name)

    # 4. No strategy matched (shouldn't happen -- keyword always runs last --
    # but handle it anyway).
    return _decision_from_spec(_DEFAULT_INTENT, via="default")


__all__ = [
    "ANOMALY_KEYWORDS",
    "INTENT_CATALOG",
    "POLICY_KEYWORDS",
    "TICKET_KEYWORDS",
    "AgentRouteDecision",
    "AgentRouteRequest",
    "EmbeddingRouteStrategy",
    "IntentSpec",
    "KeywordRouteStrategy",
    "LLMRouteStrategy",
    "RouteStrategy",
    "choose_route",
]
