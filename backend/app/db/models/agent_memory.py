"""Long-term semantic memory for agents (P3.6).

Short-term memory piggybacks on ``ChatMessage`` (already exists and is
the natural home for a conversation history), so this table is only for
the *semantic* layer: distilled facts / conclusions an agent wants to
recall across sessions.

Storage layout
--------------

We keep the embedding on the row itself (``embedding_json``) rather than
pushing to the Milvus collection used by RAG because:

- The expected volume is tiny (O(10²) per user) — in-process cosine over
  all rows is faster than a network hop to Milvus until we cross 10⁴+.
- Keeping memory in the same RDBMS as ``AgentRun`` / ``AuditLog`` means
  one RLS policy, one transactional story, one backup path.
- Migrating to Milvus later is a code-only change: swap the store
  implementation; schema stays compatible via a ``model_name`` column
  that tags which embedder produced each vector.

RLS follows the audit_log / agent_event pattern: tenant-scoped reads
plus a GRANT to ``travel_ops_app_user``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentMemoryEntry(Base):
    __tablename__ = "agent_memory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # Free-form category / namespace the agent chose when remembering
    # (e.g. "preferred_city", "last_blocked_reason"). Nullable because
    # some callers just want a dumping-ground fact log.
    key: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Embedding stored as JSON-encoded list[float]; small overhead vs
    # binary but keeps SQLite tests trivial and Alembic migrations dialect-
    # agnostic. Produced by ``texts_to_embeddings`` so the dimension matches
    # the configured embedder.
    embedding_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    # Name of the embedder that produced ``embedding_json``. Used at recall
    # time to skip vectors from a stale model after rotation.
    model_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
