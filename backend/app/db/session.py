from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_configured_database_url: str | None = None


def _build_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
    return create_engine(database_url, future=True)


def get_engine() -> Engine:
    global _engine, _session_factory, _configured_database_url

    settings = get_settings()
    if _engine is None or _configured_database_url != settings.database_url:
        _engine = _build_engine(settings.database_url)
        _session_factory = sessionmaker(
            bind=_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        _configured_database_url = settings.database_url

    return _engine


class _SessionLocalProxy:
    def __call__(self) -> Session:
        engine = get_engine()
        assert _session_factory is not None
        if engine != _session_factory.kw["bind"]:
            raise RuntimeError("session factory bind drift detected")
        return _session_factory()


SessionLocal = _SessionLocalProxy()


def init_db() -> None:
    from app.db.models.agent import AgentRun, ToolCallLog
    from app.db.models.conversation import ChatMessage, ChatSession
    from app.db.models.eval import EvalDataset, EvalRun
    from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
    from app.db.models.prompt_template import PromptTemplate
    from app.db.models.rag_recall_log import RagRecallLog
    from app.db.models.rule import PolicyRule, ReviewCase

    del (
        AgentRun,
        ChatMessage,
        ChatSession,
        EvalDataset,
        EvalRun,
        KnowledgeChunk,
        KnowledgeDocument,
        PolicyRule,
        PromptTemplate,
        RagRecallLog,
        ReviewCase,
        ToolCallLog,
    )
    Base.metadata.create_all(bind=get_engine())


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
