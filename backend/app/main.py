from fastapi import FastAPI

from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()

    app = FastAPI(title=settings.app_name)
    app.include_router(health_router)
    app.include_router(knowledge_router)
    app.include_router(chat_router)
    return app


app = create_app()
