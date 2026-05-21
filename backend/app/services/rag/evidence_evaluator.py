"""CRAG evidence sufficiency evaluator (Stage 3 multi-hop hardening).

Why this exists
---------------
Stage 1 (hybrid + RRF + reranker) and Stage 2 (multi-query + HyDE) make
retrieval *broader*, but they have a structural blind spot for multi-hop
questions: if one sub-question is phrased with rare or technical wording,
its supporting chunks rank low against the original combined query and get
truncated by ``CHAT_TOP_K``. The user sees a confident-sounding answer
that silently omits a sub-question.

The evaluator closes that loop. After initial retrieval it asks the LLM:

    "Given these chunks, which aspects of the user's question are
    sufficiently covered? Which are still missing? What new queries would
    fill the gaps?"

The query engine then re-retrieves with the suggested queries, merges the
result, and re-evaluates. Multiple rounds are allowed (capped + anti-loop)
so questions with 3+ disjoint sub-questions can converge incrementally.

Failure semantics
-----------------
The evaluator is a *quality boost*, not a correctness gate. Any failure
(timeout, malformed JSON, upstream error) returns a ``"sufficient"`` verdict
so the chat path stays online. Worst case under failure: we behave exactly
like Stage 2, no regression.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.services.llm.rewrite_client import (
    OpenAICompatibleRewriteClient,
    RewriteClientConfigError,
)
from app.services.rag.citation_service import CitationRecord

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvidenceEvaluation:
    """Structured output from one CRAG evaluator round.

    ``sufficiency_score`` is a self-reported 0–1 estimate of whether the
    current evidence pool can fully answer the question. Below the
    configured threshold the engine triggers a re-retrieval round using
    ``suggested_queries`` (which are derived from ``missing_aspects``).

    ``reasoning`` is a short rationale that lands in ``retrieval_trace``
    so operators can see why a round was triggered or skipped. Don't
    rely on it being parseable — it's free-form Chinese / English.
    """

    sufficiency_score: float
    covered_aspects: list[str] = field(default_factory=list)
    missing_aspects: list[str] = field(default_factory=list)
    suggested_queries: list[str] = field(default_factory=list)
    reasoning: str = ""
    succeeded: bool = True  # False when the LLM call failed; engine should
    # treat as "sufficient" to avoid blocking.

    def is_sufficient(self, threshold: float) -> bool:
        if not self.succeeded:
            return True  # fail-open
        return self.sufficiency_score >= threshold

    def as_dict(self) -> dict[str, object]:
        return {
            "sufficiency_score": self.sufficiency_score,
            "covered_aspects": list(self.covered_aspects),
            "missing_aspects": list(self.missing_aspects),
            "suggested_queries": list(self.suggested_queries),
            "reasoning": self.reasoning,
            "succeeded": self.succeeded,
        }


_EVALUATOR_SYSTEM_PROMPT = (
    "你是 RAG 检索评估员。基于用户问题与已检索的文档片段，判断证据是否足以"
    "完整回答问题。注意区分：\n"
    "1. 用户问题中是否有多个子问题（如 'A 是什么？以及 B 怎么处理？'）\n"
    "2. 每个子问题在已检索证据中是否有直接对应内容（不是表面词汇命中，而是"
    "实际能答出该子问题）\n"
    "3. 缺失的证据应当用什么样的检索 query 才能补上\n\n"
    "输出严格 JSON 对象，不要包含 markdown 代码块标记，结构如下：\n"
    "{\n"
    '  "sufficiency_score": 0.0-1.0,\n'
    '  "covered_aspects": ["已被覆盖的子问题描述", ...],\n'
    '  "missing_aspects": ["未被覆盖的子问题描述", ...],\n'
    '  "suggested_queries": ["建议补充的检索 query", ...],\n'
    '  "reasoning": "一句话说明判断理由"\n'
    "}\n"
    "如果证据已足以完整答题，sufficiency_score >= 0.8 且 missing_aspects 为空。\n"
    "如果某子问题完全无证据，sufficiency_score < 0.5 且至少 1 条 suggested_queries。\n"
    "suggested_queries 必须与原 query 不同义、聚焦缺失子问题，最多 3 条。"
)


def _format_evidence_block(citations: list[CitationRecord]) -> str:
    """Render citations into a numbered evidence block for the prompt.

    Truncates each chunk to a budget so the prompt stays under typical
    32K-token limits even when the retriever returns 8 large chunks.
    """
    if not citations:
        return "(无证据)"
    lines: list[str] = []
    for idx, citation in enumerate(citations, start=1):
        body = (citation.full_content or citation.snippet or "").strip()
        if len(body) > 600:
            body = body[:597] + "..."
        title = citation.document_title or citation.chunk_id
        lines.append(f"[证据{idx}] 文档={title}\n{body}")
    return "\n\n".join(lines)


def _strip_json_fence(text: str) -> str:
    """Extract the JSON object from possibly-fenced LLM output.

    Some models still wrap structured output in ```json ... ``` despite
    the system prompt asking otherwise. We pluck out the first ``{...}``
    block defensively.
    """
    text = text.strip()
    # Quick path: already raw JSON.
    if text.startswith("{") and text.endswith("}"):
        return text
    # Strip code fence if present.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    # Last resort: greedy braces.
    brace_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if brace_match:
        return brace_match.group(0)
    return text


def _parse_evaluation(raw: str) -> EvidenceEvaluation:
    """Parse the evaluator's JSON output, defaulting safely on any error."""
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        _log.warning(
            "crag_evaluator_json_parse_failed", extra={"error": str(exc), "raw": raw[:200]}
        )
        return EvidenceEvaluation(
            sufficiency_score=1.0, reasoning="JSON parse failed", succeeded=False
        )

    try:
        score = float(data.get("sufficiency_score", 1.0))
    except (TypeError, ValueError):
        score = 1.0
    score = max(0.0, min(score, 1.0))

    def _string_list(key: str) -> list[str]:
        value = data.get(key) or []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    return EvidenceEvaluation(
        sufficiency_score=score,
        covered_aspects=_string_list("covered_aspects"),
        missing_aspects=_string_list("missing_aspects"),
        suggested_queries=_string_list("suggested_queries")[:3],
        reasoning=str(data.get("reasoning") or "").strip()[:300],
        succeeded=True,
    )


class _DeterministicEvaluator:
    """Test/dev evaluator: always reports sufficient.

    Mirrors :class:`DeterministicRewriteClient`'s philosophy — when the
    real LLM gateway isn't configured, behave as a no-op so the rest of
    the chat path stays exercised.
    """

    async def evaluate_async(
        self, question: str, citations: list[CitationRecord]
    ) -> EvidenceEvaluation:
        return EvidenceEvaluation(
            sufficiency_score=1.0,
            reasoning="deterministic evaluator",
            succeeded=True,
        )


class OpenAICompatibleEvidenceEvaluator:
    """Evidence evaluator backed by an OpenAI-compatible chat endpoint.

    Reuses the same gateway as :class:`OpenAICompatibleRewriteClient`
    (typically the project's main LLM provider — DeepSeek via Volcengine
    Ark in this deployment) so we don't double our API-key surface area.
    """

    def __init__(
        self, *, base_url: str, api_key: str, model_name: str, timeout_seconds: float = 8.0
    ):
        # We delegate the actual HTTP call to the rewrite client's
        # ``_chat_async`` implementation: same gateway, same auth, same
        # async http client pool. Wrapping rather than subclassing keeps
        # the surface area small and avoids accidentally exposing
        # paraphrase / HyDE methods on the evaluator.
        self._chat_client = OpenAICompatibleRewriteClient(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
        )

    async def evaluate_async(
        self, question: str, citations: list[CitationRecord]
    ) -> EvidenceEvaluation:
        evidence_block = _format_evidence_block(citations)
        user_prompt = (
            f"# 用户问题\n{question}\n\n"
            f"# 已检索证据\n{evidence_block}\n\n"
            "请评估这些证据是否足以完整回答用户问题，并按 system 指令返回严格 JSON。"
        )
        try:
            raw = await self._chat_client._chat_async(
                _EVALUATOR_SYSTEM_PROMPT,
                user_prompt,
                temperature=0.0,
            )
        except Exception as exc:
            _log.warning("crag_evaluator_upstream_failed", extra={"error": str(exc)})
            return EvidenceEvaluation(
                sufficiency_score=1.0,
                reasoning=f"evaluator upstream failure: {type(exc).__name__}",
                succeeded=False,
            )
        return _parse_evaluation(raw)


def _build_evaluator():
    """Factory: pick provider by current LLM config.

    Falls back to deterministic when the real LLM gateway isn't available
    so dev / test environments aren't forced to mock CRAG.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if settings.llm_provider != "openai-compatible":
        return _DeterministicEvaluator()
    if not settings.llm_api_base_url or not settings.llm_api_key or not settings.llm_model_name:
        _log.warning("crag_evaluator_falling_back_to_deterministic_no_credentials")
        return _DeterministicEvaluator()
    try:
        return OpenAICompatibleEvidenceEvaluator(
            base_url=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
            timeout_seconds=settings.crag_evaluator_timeout_seconds,
        )
    except RewriteClientConfigError as exc:
        _log.warning("crag_evaluator_config_invalid", extra={"error": str(exc)})
        return _DeterministicEvaluator()


_evaluator_cache: object | None = None


def get_evidence_evaluator() -> object:
    """Process-wide evaluator instance.

    Cached because building the underlying httpx client each query would
    burn TCP connections; the rewrite-client gateway already has its own
    connection pool we want to share.
    """
    global _evaluator_cache
    if _evaluator_cache is None:
        _evaluator_cache = _build_evaluator()
    return _evaluator_cache


def reset_evidence_evaluator() -> None:
    """Test hook: drop the cached evaluator so the next call re-builds.

    Used by tests that monkeypatch settings (e.g. switch llm_provider on
    the fly). Production code should not need this.
    """
    global _evaluator_cache
    _evaluator_cache = None


__all__ = [
    "EvidenceEvaluation",
    "OpenAICompatibleEvidenceEvaluator",
    "get_evidence_evaluator",
    "reset_evidence_evaluator",
]
