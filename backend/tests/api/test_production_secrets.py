"""Tests for the expanded production secret validator (P1.7).

P1.1 covered JWT-level guards. P1.7 adds:
- Static AUTH_*_TOKENS default values rejected
- LLM_API_KEY required when LLM_PROVIDER != deterministic
- EMBEDDING_API_KEY required when EMBEDDING_PROVIDER != deterministic
- MinIO root credentials default values rejected
"""

from __future__ import annotations

import pytest


def _prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Baseline: production with ALL secrets fixed except the one under test."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "a-real-looking-prod-secret-xxxxxxxxxx")
    monkeypatch.setenv("JWT_DEV_TOKEN_ENDPOINT_ENABLED", "false")
    monkeypatch.setenv("AUTH_ADMIN_TOKENS", "prod-admin-rotated-abc123")
    monkeypatch.setenv("AUTH_OPERATOR_TOKENS", "prod-operator-rotated-def456")
    monkeypatch.setenv("AUTH_REVIEWER_TOKENS", "prod-reviewer-rotated-ghi789")
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")  # no API key needed
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    # conftest._test_environment forces OBJECT_STORAGE_PROVIDER=local for
    # the shared unit suite; flip back to minio so the MinIO credential
    # checks actually trip in these tests.
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "minio")
    monkeypatch.setenv("MINIO_ROOT_USER", "prod-minio-user")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "prod-minio-password-long-enough")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    # conftest._test_environment forces CELERY_TASK_ALWAYS_EAGER=true for
    # the shared unit suite; production must have it false (P4.3) so the
    # baseline explicitly flips it back.
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "false")


def _expect_boot_failure(substr: str) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match=substr):
        create_app()
    get_settings.cache_clear()


def _expect_boot_success() -> None:
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    create_app()  # should not raise
    get_settings.cache_clear()


def test_production_rejects_default_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch)
    monkeypatch.setenv("AUTH_ADMIN_TOKENS", "admin-token")  # the shipped default

    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with pytest.raises(RuntimeError) as exc_info:
        create_app()
    assert "AUTH_ADMIN_TOKENS" in str(exc_info.value)
    get_settings.cache_clear()


def test_production_rejects_default_operator_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch)
    monkeypatch.setenv("AUTH_OPERATOR_TOKENS", "operator-token")
    _expect_boot_failure("AUTH_OPERATOR_TOKENS")


def test_production_rejects_default_reviewer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch)
    monkeypatch.setenv("AUTH_REVIEWER_TOKENS", "reviewer-token")
    _expect_boot_failure("AUTH_REVIEWER_TOKENS")


def test_production_requires_llm_api_key_for_nondeterministic_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prod_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_API_KEY", "")
    _expect_boot_failure("LLM_API_KEY required")


def test_production_requires_embedding_api_key_for_nondeterministic_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prod_env(monkeypatch)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    _expect_boot_failure("EMBEDDING_API_KEY required")


def test_production_rejects_default_minio_access_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch)
    monkeypatch.setenv("MINIO_ROOT_USER", "minioadmin")
    _expect_boot_failure("MINIO_ROOT_USER")


def test_production_rejects_default_minio_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch)
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "minioadmin123")
    _expect_boot_failure("MINIO_ROOT_PASSWORD")


def test_production_aggregates_multiple_problems_in_one_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple misconfigurations should surface together, not one-by-one."""
    _prod_env(monkeypatch)
    monkeypatch.setenv("AUTH_ADMIN_TOKENS", "admin-token")
    monkeypatch.setenv("MINIO_ROOT_USER", "minioadmin")

    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with pytest.raises(RuntimeError) as exc_info:
        create_app()
    message = str(exc_info.value)
    assert "AUTH_ADMIN_TOKENS" in message
    assert "MINIO_ROOT_USER" in message
    get_settings.cache_clear()


def test_production_rejects_celery_eager_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """P4.3: eager mode runs Celery tasks inline in the web worker.
    That's fine for tests but would serialise every ingestion /
    eval request in production — exactly what Phase 4 is fixing.
    """
    _prod_env(monkeypatch)
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")
    _expect_boot_failure("CELERY_TASK_ALWAYS_EAGER")


def test_production_accepts_valid_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch)
    _expect_boot_success()


def test_non_production_env_skips_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Development with all defaults should boot fine."""
    monkeypatch.setenv("APP_ENV", "development")
    # Everything else left as default
    _expect_boot_success()
