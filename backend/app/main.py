import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.api.error_handlers import register_error_handlers
from app.api.rate_limit_middleware import attach_rate_limiter
from app.api.routes.agents import router as agents_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.evals import router as evals_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.prompt_templates import (
    feedback_router as prompt_feedback_router,
)
from app.api.routes.prompt_templates import (
    router as prompt_templates_router,
)
from app.api.routes.reviews import router as reviews_router
from app.api.routes.rules import router as rules_router
from app.api.routes.runtime_logs import router as runtime_logs_router
from app.api.routes.slo import router as slo_router
from app.api.routes.system_settings import router as system_settings_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.usage import router as usage_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.metrics import observe_request, observe_token_usage, render_metrics
from app.db.session import bypass_rls_session, init_db
from app.services.rules.engine import seed_default_rules
from app.services.runtime_logs import create_runtime_log

_bootstrap_logger = logging.getLogger("travel_ops.bootstrap")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """One-shot startup and shutdown hooks.

    Runs schema bootstrap + default-rule seeding exactly once per process,
    so hot-path request handlers can stay free of ``init_db()`` calls.
    """
    init_db()
    # P5.1: best-effort OTEL init. Silently no-ops when env isn't set or
    # opentelemetry packages are missing; real tracer is installed when
    # OTEL_EXPORTER_OTLP_ENDPOINT is configured and ``.[otel]`` extras
    # are available.
    from app.core.observability.tracing import init_otel_tracer

    init_otel_tracer()
    # bypass_rls_session: lifespan boot has no caller tenant, must touch
    # every row. Switching to a normal session here would silently see no
    # rows once RLS lands in P1.4.
    with bypass_rls_session() as session:
        seeded = seed_default_rules(session)
    # P2.1: surface the active embedding configuration at startup so
    # operators can see at a glance whether they are actually running
    # a real embedding model or the test-only deterministic fallback.
    from app.services.rag.embedding_client import get_active_embedding_profile

    profile = get_active_embedding_profile()
    _bootstrap_logger.info(
        "app_ready",
        extra={
            "seeded_rules": len(seeded),
            "embedding_provider": profile.provider,
            "embedding_model": profile.model_name,
            "embedding_dimension": profile.dimension,
        },
    )
    if profile.provider == "deterministic":
        _bootstrap_logger.warning(
            "embedding_provider_is_deterministic",
            extra={
                "hint": (
                    "EMBEDDING_PROVIDER=deterministic produces non-semantic "
                    "vectors. Only safe for unit tests -- set "
                    "EMBEDDING_PROVIDER=openai-compatible with a real gateway "
                    "for anything you would show to a user."
                )
            },
        )

    # P2.8: warm Milvus once per process, not per query. ``preload`` is
    # idempotent and failure-tolerant; search() will defensively retry
    # the load if this startup call was skipped (e.g. collection doesn't
    # exist yet because nothing has been ingested).
    from app.services.rag.vector_store import get_vector_store

    try:
        get_vector_store().preload()
    except Exception as exc:
        _bootstrap_logger.warning(
            "vector_store_preload_failed",
            extra={"error": str(exc)},
        )
    yield
    # P4.1: close the shared async HTTP client so connections drain
    # cleanly on shutdown. Safe when the client was never created
    # (idempotent).
    from app.services.rag.async_http_client import close_async_http_client

    await close_async_http_client()
    # P5.1: flush any pending OTEL spans before exit.
    from app.core.observability.tracing import shutdown_otel_tracer

    shutdown_otel_tracer()
    _bootstrap_logger.info("app_shutdown")


_DEFAULT_JWT_SECRET = "dev-only-insecure-change-me"
_DEFAULT_MINIO_ACCESS = "minioadmin"
_DEFAULT_MINIO_SECRET = "minioadmin123"
_DEFAULT_ADMIN_TOKEN = "admin-token"
_DEFAULT_OPERATOR_TOKEN = "operator-token"
_DEFAULT_REVIEWER_TOKEN = "reviewer-token"


def _accumulate_token_usage_safe(request: Request) -> None:
    """Best-effort ``token_usage_daily`` write from the response middleware.

    Must never escalate an error: if the DB is gone or the tenant_id
    isn't set on this request, we skip silently (the request already
    succeeded; we don't want a billing-side bug to retroactively 5xx
    a chat response that the user already received).
    """
    try:
        token_usage = getattr(request.state, "token_usage", None) or {}
        tenant_id = getattr(request.state, "tenant_id", None) or ""
        model_name = getattr(request.state, "model_name", None) or ""
        if not tenant_id or not model_name or not token_usage:
            return
        if not (token_usage.get("input_tokens") or token_usage.get("output_tokens")):
            return
        agent_name = getattr(request.state, "agent_name", None) or ""
        from app.db.session import bypass_rls_session
        from app.services.observability.token_sink import accumulate

        with bypass_rls_session() as session:
            accumulate(
                session,
                tenant_id=tenant_id,
                model_name=model_name,
                agent_name=agent_name,
                input_tokens=int(token_usage.get("input_tokens") or 0),
                output_tokens=int(token_usage.get("output_tokens") or 0),
            )
            session.commit()
    except Exception as exc:
        # Logged not raised — observability must never break the hot path.
        logging.getLogger("travel_ops.bootstrap").warning(
            "token_usage_accumulate_failed", extra={"error": str(exc)}
        )


def _validate_production_security(settings) -> None:  # type: ignore[no-untyped-def]
    """Refuse to boot a production process with dev-only security settings.

    Organised in four groups, each group contributing to a single error
    message on failure. Clients see a single ``RuntimeError`` with every
    problem listed, rather than fixing one, restarting, and hitting the
    next.

    Groups:
    1. **Auth / JWT** -- JWT must be on, signing key must not be default,
       dev-token endpoint must be off.
    2. **Static tokens** -- AUTH_*_TOKENS env must not be default dev values
       (they grant admin/operator/reviewer immediately).
    3. **LLM / embedding gateway** -- when provider != "deterministic",
       a real API key must be configured.
    4. **Object storage (MinIO)** -- root user / password must not be the
       default "minioadmin" pair.
    """
    if settings.app_env.lower() != "production":
        return

    problems: list[str] = []

    # 1. JWT
    if not settings.jwt_enabled:
        problems.append("JWT_ENABLED must be true in production")
    if not settings.jwt_secret_key or settings.jwt_secret_key == _DEFAULT_JWT_SECRET:
        problems.append("JWT_SECRET_KEY must be overridden in production")
    if settings.jwt_dev_token_endpoint_enabled:
        problems.append("JWT_DEV_TOKEN_ENDPOINT_ENABLED must be false in production")

    # 2. Static tokens (legacy path). With JWT enabled they shouldn't be
    # used, but a mis-rollout that leaves jwt_enabled=false would silently
    # grant admin access via the shipped default values.
    if _DEFAULT_ADMIN_TOKEN in settings.auth_admin_tokens:
        problems.append("AUTH_ADMIN_TOKENS must not contain the default dev value")
    if _DEFAULT_OPERATOR_TOKEN in settings.auth_operator_tokens:
        problems.append("AUTH_OPERATOR_TOKENS must not contain the default dev value")
    if _DEFAULT_REVIEWER_TOKEN in settings.auth_reviewer_tokens:
        problems.append("AUTH_REVIEWER_TOKENS must not contain the default dev value")

    # 3. LLM / embedding: non-deterministic providers need real creds.
    if settings.llm_provider != "deterministic" and not settings.llm_api_key:
        problems.append(f"LLM_API_KEY required when LLM_PROVIDER={settings.llm_provider}")
    if settings.embedding_provider != "deterministic" and not settings.embedding_api_key:
        problems.append(
            f"EMBEDDING_API_KEY required when EMBEDDING_PROVIDER={settings.embedding_provider}"
        )

    # 4. MinIO root credentials.
    if (
        settings.object_storage_provider == "minio"
        and settings.minio_access_key == _DEFAULT_MINIO_ACCESS
    ):
        problems.append("MINIO_ROOT_USER must not be 'minioadmin' in production")
    if (
        settings.object_storage_provider == "minio"
        and settings.minio_secret_key == _DEFAULT_MINIO_SECRET
    ):
        problems.append("MINIO_ROOT_PASSWORD must not be the default in production")

    # 5. Celery eager mode (P4.3): in production, tasks must go through
    # a real broker + worker. Eager mode runs tasks synchronously inside
    # the web process which is fine for tests but means production
    # uploads / evals would block the request thread (the exact thing
    # Phase 4 is trying to fix).
    if settings.celery_task_always_eager:
        problems.append(
            "CELERY_TASK_ALWAYS_EAGER must be false in production "
            "(eager mode runs tasks inline and blocks web workers)"
        )

    if problems:
        raise RuntimeError("insecure production config: " + "; ".join(problems))


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    _validate_production_security(settings)
    request_logger = logging.getLogger("travel_ops.request")

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    attach_rate_limiter(app)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        payload, content_type = render_metrics()
        return Response(content=payload, media_type=content_type)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        # P5.1: install a trace_id for this request so every downstream
        # log / audit / agent_event / task_run can correlate back. The
        # id comes from the upstream ``traceparent`` header when the
        # caller is already traced; otherwise we mint a fresh one.
        from app.core.observability.tracing import (
            extract_trace_id_from_headers,
            set_trace_id,
        )

        trace_id = extract_trace_id_from_headers(request.headers)
        set_trace_id(trace_id)
        request.state.trace_id = trace_id
        started_at = perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            latency_ms = int((perf_counter() - started_at) * 1000)
            error_message = "internal server error"
            create_runtime_log(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                latency_ms=latency_ms,
                tenant_id=getattr(request.state, "tenant_id", None),
                customer_id=getattr(request.state, "customer_id", None),
                session_id=getattr(request.state, "session_id", None),
                user_role=getattr(request.state, "user_role", None),
                model_name=getattr(request.state, "model_name", None),
                token_usage=getattr(request.state, "token_usage", None),
                error_message=error_message,
            )
            request_logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "tenant_id": getattr(request.state, "tenant_id", None),
                    "customer_id": getattr(request.state, "customer_id", None),
                    "session_id": getattr(request.state, "session_id", None),
                    "user_role": getattr(request.state, "user_role", None),
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "latency_ms": latency_ms,
                    "model_name": getattr(request.state, "model_name", None),
                    "token_usage": getattr(request.state, "token_usage", None),
                    "error_message": error_message,
                },
            )
            raise

        latency_ms = int((perf_counter() - started_at) * 1000)
        response.headers["X-Request-ID"] = request_id
        create_runtime_log(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
            tenant_id=getattr(request.state, "tenant_id", None),
            customer_id=getattr(request.state, "customer_id", None),
            session_id=getattr(request.state, "session_id", None),
            user_role=getattr(request.state, "user_role", None),
            model_name=getattr(request.state, "model_name", None),
            token_usage=getattr(request.state, "token_usage", None),
        )
        observe_request(request.method, request.url.path, response.status_code, latency_ms)
        observe_token_usage(
            getattr(request.state, "model_name", None),
            getattr(request.state, "token_usage", None),
        )
        # P5.2: persist the same usage into the ``token_usage_daily``
        # aggregate so per-tenant spend queries don't have to scan
        # RagRecallLog / ChatMessage metadata.
        _accumulate_token_usage_safe(request)
        request_logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "customer_id": getattr(request.state, "customer_id", None),
                "session_id": getattr(request.state, "session_id", None),
                "user_role": getattr(request.state, "user_role", None),
                "http_method": request.method,
                "http_path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "model_name": getattr(request.state, "model_name", None),
                "token_usage": getattr(request.state, "token_usage", None),
            },
        )
        return response

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(knowledge_router)
    app.include_router(chat_router)
    app.include_router(prompt_templates_router)
    app.include_router(prompt_feedback_router)
    app.include_router(evals_router)
    app.include_router(agents_router)
    app.include_router(rules_router)
    app.include_router(reviews_router)
    app.include_router(system_settings_router)
    app.include_router(runtime_logs_router)
    app.include_router(tasks_router)
    app.include_router(usage_router)
    app.include_router(slo_router)
    app.include_router(monitoring_router)
    return app


# Deployment note (P1.7): the module no longer builds an ``app`` at import
# time. Production must run uvicorn in factory mode so the production
# secret validator runs at process boot, not at import time (which would
# break tests and tooling that just want to inspect the module).
#
#   uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
#
# For ergonomics we still expose ``app`` via a lazy attribute so legacy
# callers / tooling that do ``from app.main import app`` keep working.
def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
