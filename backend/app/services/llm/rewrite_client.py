"""LLM adapter for query rewriting (paraphrase) and HyDE document generation.

Not to be confused with ``app.services.llm.client`` which handles the
*answer generation* path. This module handles the *retrieval-assist*
path: cheap chat completions used to improve recall, not to surface
content to the end user.

Providers:
- ``deterministic``: no-op, returns empty paraphrases + a stub HyDE doc.
  Used in tests so we don't burn LLM quota.
- ``openai-compatible``: POST /chat/completions against any OpenAI-
  schema gateway (OpenAI, DeepSeek, 智谱, Kimi, etc.).

Missing config (provider=openai-compatible + no url/key/model) raises
``RewriteClientConfigError`` at construction time. ``query_rewriter`` is
the sole consumer; it catches exceptions and degrades to alias-only.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings

_log = logging.getLogger(__name__)


class RewriteClientConfigError(RuntimeError):
    """Raised when the configured rewrite LLM is missing required env."""


class RewriteClient(Protocol):
    def paraphrase(self, question: str, n: int) -> list[str]: ...

    def generate_hyde_document(self, question: str) -> str: ...


class DeterministicRewriteClient:
    """Test-only stub. Returns deterministic canned outputs.

    ``paraphrase`` returns an empty list (the rewrite pipeline treats
    empty as "no variants"), so tests that don't mock the LLM path
    don't accidentally exercise it. ``generate_hyde_document`` returns
    a short canned string so HyDE-enabled tests can still verify the
    wiring without needing a real LLM.
    """

    model_name = "deterministic-rewrite-client"

    def paraphrase(self, question: str, n: int) -> list[str]:
        return []

    def generate_hyde_document(self, question: str) -> str:
        return f"(deterministic HyDE) {question}"

    async def paraphrase_async(self, question: str, n: int) -> list[str]:
        """Async twin — pure CPU / no IO, but keeps the signature symmetric
        with :class:`OpenAICompatibleRewriteClient` so the async query-engine
        path doesn't branch on provider type.
        """
        return self.paraphrase(question, n)

    async def generate_hyde_document_async(self, question: str) -> str:
        return self.generate_hyde_document(question)


_PARAPHRASE_SYSTEM_PROMPT = (
    "You rewrite the user's question into alternative phrasings for retrieval. "
    "Keep the same intent and language. Return ONLY a JSON array of strings."
)

_HYDE_SYSTEM_PROMPT = (
    "You are a retrieval assistant. Write a short hypothetical answer to the "
    "user's question in 1-2 sentences, in the same language as the question. "
    "Make up plausible facts -- this text is used only to embed and retrieve "
    "real documents, not shown to the user. Return ONLY the hypothetical "
    "answer, no preamble."
)


class OpenAICompatibleRewriteClient:
    """HTTP client for any OpenAI-schema ``/chat/completions`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_seconds: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise RewriteClientConfigError("base_url is required")
        if not api_key:
            raise RewriteClientConfigError("api_key is required")
        if not model_name:
            raise RewriteClientConfigError("model_name is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self._timeout = timeout_seconds
        self._http_client = http_client

    def _client(self) -> httpx.Client:
        return self._http_client or httpx.Client(timeout=self._timeout)

    def _chat(self, system: str, user: str, temperature: float = 0.4) -> str:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        response = self._client().post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        return str(body["choices"][0]["message"]["content"]).strip()

    async def _chat_async(
        self,
        system: str,
        user: str,
        temperature: float = 0.4,
        *,
        async_client: httpx.AsyncClient | None = None,
    ) -> str:
        """Async twin of :meth:`_chat` (P4.2).

        Same request shape, same upstream error model. Pulls the shared
        ``AsyncClient`` from P4.1 when callers don't inject one.
        """
        client = async_client
        if client is None:
            from app.services.rag.async_http_client import get_async_http_client

            client = get_async_http_client()

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()
        return str(body["choices"][0]["message"]["content"]).strip()

    async def paraphrase_async(
        self,
        question: str,
        n: int,
        *,
        async_client: httpx.AsyncClient | None = None,
    ) -> list[str]:
        """Async version of :meth:`paraphrase`; same fallback semantics."""
        if n <= 0:
            return []
        user = f"Question: {question}\n\nReturn {n} paraphrases as a JSON array."
        try:
            content = await self._chat_async(
                _PARAPHRASE_SYSTEM_PROMPT, user, temperature=0.7, async_client=async_client
            )
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            _log.warning("rewrite_paraphrase_upstream_failed", extra={"error": str(exc)})
            return []

        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            lines = [line.strip(" -*\t") for line in stripped.splitlines() if line.strip()]
            return lines[:n]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()][:n]
        return []

    async def generate_hyde_document_async(
        self,
        question: str,
        *,
        async_client: httpx.AsyncClient | None = None,
    ) -> str:
        try:
            return await self._chat_async(
                _HYDE_SYSTEM_PROMPT, question, temperature=0.5, async_client=async_client
            )
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            _log.warning("rewrite_hyde_upstream_failed", extra={"error": str(exc)})
            return ""

    def paraphrase(self, question: str, n: int) -> list[str]:
        """Return up to ``n`` paraphrases, or empty list on any failure."""
        if n <= 0:
            return []
        user = f"Question: {question}\n\nReturn {n} paraphrases as a JSON array."
        try:
            content = self._chat(_PARAPHRASE_SYSTEM_PROMPT, user, temperature=0.7)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            _log.warning("rewrite_paraphrase_upstream_failed", extra={"error": str(exc)})
            return []

        stripped = content.strip()
        # Strip ```json fenced blocks if the model wrapped them.
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            # Some providers return a plain newline-separated list; fall back.
            lines = [line.strip(" -*\t") for line in stripped.splitlines() if line.strip()]
            return lines[:n]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()][:n]
        return []

    def generate_hyde_document(self, question: str) -> str:
        try:
            return self._chat(_HYDE_SYSTEM_PROMPT, question, temperature=0.5)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            _log.warning("rewrite_hyde_upstream_failed", extra={"error": str(exc)})
            return ""


def _build_rewrite_client(settings: Settings) -> RewriteClient:
    """Factory: pick provider by llm_provider config.

    Falls back to deterministic stub when ``llm_provider=deterministic``
    or the OpenAI-compatible path is not configured. The query rewriter
    already catches exceptions, so we prefer to hand back a no-op
    client rather than raising here.
    """
    if settings.llm_provider != "openai-compatible":
        return DeterministicRewriteClient()
    if not settings.llm_api_base_url or not settings.llm_api_key or not settings.llm_model_name:
        _log.info(
            "rewrite_client_falling_back_to_deterministic",
            extra={
                "reason": "llm provider=openai-compatible but config incomplete",
                "missing_base_url": not settings.llm_api_base_url,
                "missing_api_key": not settings.llm_api_key,
                "missing_model": not settings.llm_model_name,
            },
        )
        return DeterministicRewriteClient()
    return OpenAICompatibleRewriteClient(
        base_url=settings.llm_api_base_url,
        api_key=settings.llm_api_key,
        model_name=settings.llm_model_name,
    )


def get_rewrite_client() -> RewriteClient:
    return _build_rewrite_client(get_settings())


__all__ = [
    "DeterministicRewriteClient",
    "OpenAICompatibleRewriteClient",
    "RewriteClient",
    "RewriteClientConfigError",
    "get_rewrite_client",
]
