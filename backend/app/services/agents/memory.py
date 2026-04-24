"""Agent memory — short-term conversation + long-term semantic (P3.6).

Short-term
----------

``ConversationMemory.recent`` just reads the last N rows of
``ChatMessage`` for a given session_id. That's the "natural" memory a
ReAct plan node wants ("what was the user asking about five minutes
ago?") and it lives in the same RDBMS as the agent runs, so there's
nothing new to store.

Long-term
---------

``SemanticMemoryStore`` is the fresh piece: agents distill facts /
conclusions mid-run and ``remember`` them. Future runs ``recall`` by
meaning — "anything this user has said about Beijing hotel caps".

Storage is the ``agent_memory`` table created in alembic 0005 (see
``app.db.models.agent_memory``). We picked the in-process cosine search
path over Milvus because the per-user volume is small (dozens to a few
hundred rows) and it dodges a network hop for every plan node. If the
workload grows, replace the store implementation without touching the
callers — the ``MemoryStore`` Protocol is the contract, not the concrete
class.

Embedding provenance: every row carries ``model_name``. At recall time
we filter out rows produced by a different embedder so a model rotation
doesn't serve vectors in the wrong geometry.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.services.agents.engine import TimelineEvent

from app.core.config import get_settings
from app.db.models.agent_memory import AgentMemoryEntry
from app.db.models.conversation import ChatMessage
from app.services.rag.embedding_client import (
    get_active_embedding_profile,
    texts_to_embeddings,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Short-term: conversation history
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationTurn:
    role: str
    content: str
    created_at: datetime


def read_recent_turns(
    session: Session,
    *,
    session_id: str,
    limit: int = 10,
) -> list[ConversationTurn]:
    """Return the last ``limit`` turns of a chat session, oldest-first.

    SQL takes the newest N (DESC ORDER + LIMIT) and we reverse in Python
    so the caller gets them in natural conversational order. Empty list
    when the session has no messages yet — callers should not have to
    handle ``None``.
    """
    if limit <= 0:
        return []
    rows = list(
        session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        ).scalars()
    )
    # Oldest first for the prompt; DB gave us newest first.
    rows.reverse()
    return [
        ConversationTurn(role=row.role, content=row.content, created_at=row.created_at)
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Long-term: semantic memory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryRecord:
    """One semantic memory hit returned from ``recall``."""

    id: str
    tenant_id: str
    user_id: str
    key: str
    content: str
    score: float
    metadata: dict[str, Any]
    created_at: datetime


class MemoryStore(Protocol):
    """Interface the agent graph depends on; keeps tests swap-friendly."""

    def remember(
        self,
        *,
        tenant_id: str,
        user_id: str,
        content: str,
        key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord: ...

    def recall(
        self,
        *,
        tenant_id: str,
        user_id: str,
        query: str,
        top_k: int = 3,
    ) -> list[MemoryRecord]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; returns 0 when either vector is all-zero.

    We keep it in pure Python instead of reaching for numpy — the per-user
    corpus is small (O(10²)) and the rest of the app doesn't pull numpy.
    """
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class SqlSemanticMemoryStore:
    """SQL-backed memory store.

    - ``remember`` embeds content via the configured embedder and inserts
      a row (with ``session.flush()``; the caller owns commit/rollback).
    - ``recall`` embeds the query, pulls tenant+user rows scoped to the
      current embedder, ranks by cosine similarity, returns top_k.
    - ``min_score`` floors noisy matches so "nothing relevant" returns
      an empty list instead of garbage.
    """

    def __init__(
        self,
        session: Session,
        *,
        min_score: float = 0.1,
    ) -> None:
        self._session = session
        self._min_score = min_score

    @property
    def session(self) -> Session:
        return self._session

    def remember(
        self,
        *,
        tenant_id: str,
        user_id: str,
        content: str,
        key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        if not content.strip():
            raise ValueError("memory content cannot be blank")
        profile = get_active_embedding_profile()
        dim = get_settings().embedding_dimension
        vector = texts_to_embeddings([content], dim)[0]

        entry = AgentMemoryEntry(
            id=str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            key=key,
            content=content,
            embedding_json=list(vector),
            model_name=profile.model_name,
            metadata_json=dict(metadata or {}),
        )
        self._session.add(entry)
        self._session.flush()
        return MemoryRecord(
            id=entry.id,
            tenant_id=entry.tenant_id,
            user_id=entry.user_id,
            key=entry.key,
            content=entry.content,
            score=1.0,  # exact round-trip; not meaningful for recall
            metadata=dict(entry.metadata_json),
            created_at=entry.created_at,
        )

    def recall(
        self,
        *,
        tenant_id: str,
        user_id: str,
        query: str,
        top_k: int = 3,
    ) -> list[MemoryRecord]:
        if top_k <= 0 or not query.strip():
            return []
        profile = get_active_embedding_profile()
        dim = get_settings().embedding_dimension
        query_vec = texts_to_embeddings([query], dim)[0]

        rows = list(
            self._session.execute(
                select(AgentMemoryEntry).where(
                    and_(
                        AgentMemoryEntry.tenant_id == tenant_id,
                        AgentMemoryEntry.user_id == user_id,
                        AgentMemoryEntry.model_name == profile.model_name,
                    )
                )
            ).scalars()
        )
        scored: list[tuple[float, AgentMemoryEntry]] = []
        for row in rows:
            score = _cosine(query_vec, list(row.embedding_json))
            if score >= self._min_score:
                scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            MemoryRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                key=row.key,
                content=row.content,
                score=round(score, 4),
                metadata=dict(row.metadata_json),
                created_at=row.created_at,
            )
            for score, row in scored[:top_k]
        ]


class NullMemoryStore:
    """Inert store used when an agent is invoked without a DB session.

    Mirrors the Protocol so graph nodes can depend on ``MemoryStore``
    unconditionally without sprinkling ``if store is not None`` branches.
    ``recall`` returns empty; ``remember`` is a structural no-op that
    still returns a placeholder record so call sites don't special-case.
    """

    def remember(
        self,
        *,
        tenant_id: str,
        user_id: str,
        content: str,
        key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        return MemoryRecord(
            id="",
            tenant_id=tenant_id,
            user_id=user_id,
            key=key,
            content=content,
            score=0.0,
            metadata=dict(metadata or {}),
            created_at=datetime.now(tz=None),
        )

    def recall(
        self,
        *,
        tenant_id: str,
        user_id: str,
        query: str,
        top_k: int = 3,
    ) -> list[MemoryRecord]:
        return []


def remember_with_events(
    store: MemoryStore,
    *,
    tenant_id: str,
    user_id: str,
    content: str,
    key: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[MemoryRecord, list[TimelineEvent]]:
    """Thin wrapper that emits a ``MEMORY_WRITE`` engine event alongside.

    Graph nodes call this instead of ``store.remember`` directly so the
    structured timeline gets ``MEMORY_WRITE`` rows for free; the events
    piggyback on whatever ``NodeResult`` the caller is already returning.
    """
    from app.services.agents.engine import EventType, TimelineEvent

    record = store.remember(
        tenant_id=tenant_id,
        user_id=user_id,
        content=content,
        key=key,
        metadata=metadata,
    )
    event = TimelineEvent(
        sequence=0,  # engine reassigns; sequence=0 is just a placeholder
        event_type=EventType.MEMORY_WRITE,
        node_name="memory",
        payload={"memory_id": record.id, "key": record.key, "tenant_id": tenant_id},
    )
    return record, [event]


def recall_with_events(
    store: MemoryStore,
    *,
    tenant_id: str,
    user_id: str,
    query: str,
    top_k: int = 3,
) -> tuple[list[MemoryRecord], list[TimelineEvent]]:
    """Same idea as ``remember_with_events`` but for ``recall``.

    Emits a single ``MEMORY_READ`` event with the hit count so the
    timeline tells whether the plan node had any memory context
    available at the moment of the call.
    """
    from app.services.agents.engine import EventType, TimelineEvent

    hits = store.recall(tenant_id=tenant_id, user_id=user_id, query=query, top_k=top_k)
    event = TimelineEvent(
        sequence=0,
        event_type=EventType.MEMORY_READ,
        node_name="memory",
        payload={"tenant_id": tenant_id, "query": query, "hit_count": len(hits)},
    )
    return hits, [event]


__all__ = [
    "ConversationTurn",
    "MemoryRecord",
    "MemoryStore",
    "NullMemoryStore",
    "SqlSemanticMemoryStore",
    "read_recent_turns",
    "recall_with_events",
    "remember_with_events",
]
