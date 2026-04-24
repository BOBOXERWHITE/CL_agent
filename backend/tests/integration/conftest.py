"""Integration test fixtures: real PostgreSQL + real MinIO via testcontainers.

Vector store remains ``noop`` for Phase 0 — Milvus integration is scheduled for
Phase 2.8 (lifespan preload + HNSW). The focus of Phase 0 integration tests is
verifying that the code works against a real RDBMS (catching schema drift,
FK constraints, JSON column behaviour) and a real object store (catching
signing / content-type / bucket policy issues).

Run with: ``pytest -m integration`` or ``make test-integration``.

Requires Docker Desktop running. Containers are started once per pytest
session and torn down at the end.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_log = logging.getLogger(__name__)

# Session-scoped containers are slow to boot; share across the whole test run.
# Each test uses the shared DB but runs inside a SAVEPOINT that rolls back,
# so cross-test state leakage is avoided.
pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    """Return True iff the Docker daemon is reachable within a short timeout.

    A full ``client.ping()`` on Windows with Docker Desktop stopped can hang
    for up to a minute. Use a 3-second timeout so the integration suite fails
    fast rather than slowly.
    """
    try:
        import docker
    except ImportError:
        return False

    try:
        client = docker.DockerClient(
            base_url=os.environ.get("DOCKER_HOST") or "npipe:////./pipe/docker_engine"
            if os.name == "nt"
            else "unix:///var/run/docker.sock",
            timeout=3,
        )
        client.ping()
        client.close()
    except Exception:
        # Fall back to the default client with the same short timeout.
        try:
            client = docker.from_env(timeout=3)
            client.ping()
            client.close()
        except Exception:
            return False
    return True


@pytest.fixture(scope="session")
def _docker_check() -> None:
    """Skip all integration tests if Docker is not running."""
    if not _docker_available():
        pytest.skip(
            "Docker daemon not reachable. Start Docker Desktop and retry.",
            allow_module_level=True,
        )


@pytest.fixture(scope="session")
def pg_container(_docker_check: None) -> Iterator[object]:
    """Boot a throwaway Postgres 16 container for the test session."""
    from testcontainers.postgres import PostgresContainer

    container = (
        PostgresContainer("postgres:16")
        .with_env("POSTGRES_USER", "integration")
        .with_env("POSTGRES_PASSWORD", "integration")
        .with_env("POSTGRES_DB", "integration")
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def minio_container(_docker_check: None) -> Iterator[object]:
    """Boot a throwaway MinIO container and create the app's bucket."""
    from testcontainers.minio import MinioContainer

    container = MinioContainer(
        access_key="integration-access",
        secret_key="integration-secret",
    )
    container.start()

    # Create the application bucket so pipeline code can put objects into it.
    from minio import Minio

    endpoint = f"{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"
    client = Minio(
        endpoint,
        access_key="integration-access",
        secret_key="integration-secret",
        secure=False,
    )
    bucket = "knowledge"
    for attempt in range(10):
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
            break
        except Exception as exc:
            if attempt == 9:
                raise
            _log.info("minio not ready yet (attempt %d): %s", attempt + 1, exc)
            time.sleep(1)

    try:
        yield container
    finally:
        container.stop()


def _pg_url_from_container(container: object) -> str:
    """testcontainers exposes a psycopg2 URL; convert to psycopg3 dialect."""
    raw_url: str = container.get_connection_url()  # type: ignore[attr-defined]
    # Examples: postgresql+psycopg2://..., postgresql://...
    if raw_url.startswith("postgresql+psycopg2://"):
        return raw_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw_url


@pytest.fixture(scope="session")
def _alembic_upgrade(pg_container: object) -> None:
    """Run alembic upgrade head once against the session's PG container."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    alembic_cfg = AlembicConfig(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(ini_path.parent / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", _pg_url_from_container(pg_container))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture()
def integration_environment(
    monkeypatch: pytest.MonkeyPatch,
    pg_container: object,
    minio_container: object,
    _alembic_upgrade: None,
) -> None:
    """Point the app at the running containers by setting env vars."""
    pg_url = _pg_url_from_container(pg_container)
    minio_endpoint = (
        f"{minio_container.get_container_host_ip()}:"  # type: ignore[attr-defined]
        f"{minio_container.get_exposed_port(9000)}"  # type: ignore[attr-defined]
    )

    monkeypatch.setenv("APP_ENV", "integration")
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "minio")
    monkeypatch.setenv("MINIO_ENDPOINT", minio_endpoint)
    monkeypatch.setenv("MINIO_ROOT_USER", "integration-access")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "integration-secret")
    monkeypatch.setenv("MINIO_BUCKET_NAME", "knowledge")
    monkeypatch.setenv("MINIO_SECURE", "false")
    # Vector store stays noop — Milvus integration is scheduled for P2.8.
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "noop")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")

    from app.core.config import get_settings

    get_settings.cache_clear()

    # Truncate all domain tables between tests so we start from a clean slate.
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DO $$
                DECLARE r RECORD;
                BEGIN
                    FOR r IN
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
                    LOOP
                        EXECUTE format('TRUNCATE TABLE %I RESTART IDENTITY CASCADE', r.tablename);
                    END LOOP;
                END $$;
                """
            )
        )
    engine.dispose()


@pytest.fixture()
def integration_client(integration_environment: None) -> Iterator[TestClient]:
    """FastAPI TestClient bound to the container-backed environment."""
    # Force engine rebuild against the new DATABASE_URL.
    import app.db.session as session_module
    from app.db.session import get_engine
    from app.main import create_app

    session_module._engine = None
    session_module._session_factory = None
    session_module._configured_database_url = None
    session_module._initialized_urls.clear()
    get_engine()  # warm up against new URL

    app = create_app()
    with TestClient(app) as client:
        # P1.1 removed the auth_enabled=false admin bypass. The default
        # static-token mode is still active in tests, so authenticate as
        # admin via the well-known dev token.
        client.headers.update({"Authorization": "Bearer admin-token"})
        yield client

    from app.core.config import get_settings

    get_settings.cache_clear()
    session_module._engine = None
    session_module._session_factory = None
    session_module._configured_database_url = None
    session_module._initialized_urls.clear()
