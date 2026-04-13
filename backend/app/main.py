import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.api.routes.agents import router as agents_router
from app.api.routes.chat import router as chat_router
from app.api.routes.evals import router as evals_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.prompt_templates import router as prompt_templates_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.runtime_logs import router as runtime_logs_router
from app.api.routes.rules import router as rules_router
from app.api.routes.system_settings import router as system_settings_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.metrics import observe_request, observe_token_usage, render_metrics
from app.db.session import init_db
from app.services.runtime_logs import create_runtime_log


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    request_logger = logging.getLogger("travel_ops.request")

    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        payload, content_type = render_metrics()
        return Response(content=payload, media_type=content_type)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
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
    app.include_router(knowledge_router)
    app.include_router(chat_router)
    app.include_router(prompt_templates_router)
    app.include_router(evals_router)
    app.include_router(agents_router)
    app.include_router(rules_router)
    app.include_router(reviews_router)
    app.include_router(system_settings_router)
    app.include_router(runtime_logs_router)
    app.include_router(monitoring_router)
    return app


app = create_app()
