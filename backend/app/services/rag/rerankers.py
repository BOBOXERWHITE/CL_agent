"""Reranker abstraction for the second-pass ranking step.

Two providers, chosen by ``settings.reranker_provider``:

- **heuristic** (default, no network): in-process phrase-match + lexical
  overlap bonus on top of the RRF fused score. Cheap and deterministic;
  good enough for small corpora and CI.

- **openai-compatible**: HTTP ``POST {base}/rerank`` following the
  Cohere / Jina / 智谱 schema. Request payload::

      {"model": "...", "query": "...",
       "documents": ["...", ...], "top_n": N}

  Response must return ``{"results": [{"index": int, "relevance_score": float}]}``.
  On any failure (HTTP error, timeout, parse error) we downgrade to the
  heuristic path so a flaky upstream does not hard-fail ``/api/chat/ask``.

Both providers preserve the ``RetrievalHit`` shape so downstream
``query_engine`` / ``citation_service`` stay unchanged. The only field
they update is ``combined_score``.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings
from app.services.rag.retrievers import RetrievalHit, lexical_overlap_score
from app.services.rag.text_processing import normalize_text

_log = logging.getLogger(__name__)


class RerankerClient(Protocol):
    """Providers must rerank ``hits`` and return ``top_k`` in score-desc order."""

    def rerank(self, question: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]: ...


def _rerank_heuristic(question: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
    """Original phrase-match + lexical bonus on top of combined_score."""
    normalized_question = normalize_text(question)
    reranked: list[RetrievalHit] = []
    for hit in hits:
        phrase_bonus = 0.0
        normalized_content = normalize_text(hit.chunk.content)
        if normalized_question and normalized_question in normalized_content:
            phrase_bonus += 0.4
        lexical_bonus = lexical_overlap_score(question, hit.chunk.content, hit.chunk.title) * 0.15
        final_score = hit.combined_score + phrase_bonus + lexical_bonus
        reranked.append(
            RetrievalHit(
                chunk=hit.chunk,
                document=hit.document,
                dense_score=hit.dense_score,
                lexical_score=hit.lexical_score,
                combined_score=final_score,
            )
        )
    reranked.sort(key=lambda item: item.combined_score, reverse=True)
    return reranked[:top_k]


class OpenAICompatibleRerankerClient:
    """Client for Cohere/Jina/智谱-style ``/rerank`` endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self._timeout = timeout_seconds
        self._http_client = http_client

    def _client(self) -> httpx.Client:
        return self._http_client or httpx.Client(timeout=self._timeout)

    def rerank(self, question: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        if not hits:
            return []

        documents = [hit.chunk.content for hit in hits]
        payload = {
            "model": self.model_name,
            "query": question,
            "documents": documents,
            "top_n": min(top_k, len(documents)),
        }
        try:
            response = self._client().post(
                f"{self.base_url}/rerank",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning(
                "reranker_upstream_failed_downgrading_to_heuristic",
                extra={"error": str(exc), "model": self.model_name},
            )
            return _rerank_heuristic(question, hits, top_k)

        results = body.get("results") or body.get("data") or []
        if not isinstance(results, list) or not results:
            _log.warning("reranker_empty_results_downgrading", extra={"body": str(body)[:200]})
            return _rerank_heuristic(question, hits, top_k)

        # Map index -> relevance_score, defaulting to 0 for hits the
        # upstream dropped (so they sink, not crash).
        scored: list[RetrievalHit] = []
        score_by_index: dict[int, float] = {}
        for item in results:
            try:
                idx = int(item["index"])
                score = float(item.get("relevance_score", item.get("score", 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= idx < len(hits):
                score_by_index[idx] = score

        for idx, hit in enumerate(hits):
            scored.append(
                RetrievalHit(
                    chunk=hit.chunk,
                    document=hit.document,
                    dense_score=hit.dense_score,
                    lexical_score=hit.lexical_score,
                    combined_score=score_by_index.get(idx, 0.0),
                )
            )
        scored.sort(key=lambda item: item.combined_score, reverse=True)
        return scored[:top_k]


def _build_reranker(settings: Settings) -> RerankerClient | None:
    """Return a provider client for ``openai-compatible`` or ``None`` for
    the heuristic path. Missing creds on ``openai-compatible`` fall back
    to the heuristic with a warning (we prefer degraded-but-working over
    hard-failing the chat path).
    """
    if settings.reranker_provider != "openai-compatible":
        return None
    if not settings.reranker_api_base_url or not settings.reranker_api_key:
        _log.warning(
            "reranker_openai_compatible_missing_config_falling_back",
            extra={
                "missing_base_url": not settings.reranker_api_base_url,
                "missing_api_key": not settings.reranker_api_key,
            },
        )
        return None
    if not settings.reranker_model_name:
        _log.warning("reranker_openai_compatible_missing_model_falling_back")
        return None
    return OpenAICompatibleRerankerClient(
        base_url=settings.reranker_api_base_url,
        api_key=settings.reranker_api_key,
        model_name=settings.reranker_model_name,
        timeout_seconds=settings.reranker_timeout_seconds,
    )


def rerank_hits(question: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
    """Public entry point; picks the configured provider, with heuristic fallback."""
    settings = get_settings()
    provider = _build_reranker(settings)
    if provider is None:
        return _rerank_heuristic(question, hits, top_k)
    return provider.rerank(question, hits, top_k)


__all__ = [
    "OpenAICompatibleRerankerClient",
    "RerankerClient",
    "rerank_hits",
]
