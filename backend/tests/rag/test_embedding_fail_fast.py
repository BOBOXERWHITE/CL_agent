"""Tests for the P2.1 embedding fail-fast + startup logging.

Covers:
- ``EMBEDDING_PROVIDER=openai-compatible`` without a base URL → raise.
- Same without an API key → raise.
- Correct config → returns an OpenAICompatibleEmbeddingClient, no fallback.
- Default deterministic provider still returns the deterministic client.
- Startup logging surfaces the active profile + warns when deterministic.
"""

from __future__ import annotations

import pytest

from app.services.rag.embedding_client import (
    DeterministicEmbeddingClient,
    EmbeddingConfigError,
    OpenAICompatibleEmbeddingClient,
    get_embedding_client,
)


def _reset_settings() -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()


def test_openai_compatible_without_base_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test")
    _reset_settings()
    with pytest.raises(EmbeddingConfigError, match="EMBEDDING_API_BASE_URL"):
        get_embedding_client()


def test_openai_compatible_without_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    _reset_settings()
    with pytest.raises(EmbeddingConfigError, match="EMBEDDING_API_KEY"):
        get_embedding_client()


def test_openai_compatible_error_lists_every_missing_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both URL and key missing → a single error names both, not just one."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    _reset_settings()
    with pytest.raises(EmbeddingConfigError) as exc_info:
        get_embedding_client()
    message = str(exc_info.value)
    assert "EMBEDDING_API_BASE_URL" in message
    assert "EMBEDDING_API_KEY" in message


def test_openai_compatible_with_full_config_returns_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test-real")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
    _reset_settings()
    client = get_embedding_client()
    assert isinstance(client, OpenAICompatibleEmbeddingClient)
    assert client.base_url == "https://api.example.com/v1"
    assert client.api_key == "sk-test-real"
    assert client.model_name == "text-embedding-3-small"


def test_deterministic_provider_returns_deterministic_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default / explicit deterministic still works; that path is the test
    fallback and we don't fail-fast on it.
    """
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    _reset_settings()
    assert isinstance(get_embedding_client(), DeterministicEmbeddingClient)


def test_startup_surfaces_embedding_profile_via_stderr(
    _test_environment: None, capfd: pytest.CaptureFixture[str]
) -> None:
    """Lifespan startup emits JSON logs to stderr; verify the
    deterministic-mode warning reaches operator-visible output.

    We capture at the file-descriptor level (``capfd``) rather than through
    Python's logging tree because the bootstrap logger uses a non-
    propagating JSON handler -- ``caplog`` would miss it, but any real
    operator reading container logs would see it.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer admin-token"})
        client.get("/health")

    captured = capfd.readouterr()
    combined = captured.out + captured.err
    assert "embedding_provider_is_deterministic" in combined, combined[-500:]


def test_active_embedding_profile_reflects_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """The profile helper drives the bootstrap log; make sure it flips to
    ``openai-compatible`` when properly configured.
    """
    from app.services.rag.embedding_client import get_active_embedding_profile

    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
    _reset_settings()

    profile = get_active_embedding_profile()
    assert profile.provider == "openai-compatible"
    assert profile.model_name == "text-embedding-3-small"
