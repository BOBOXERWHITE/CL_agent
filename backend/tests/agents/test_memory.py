"""Unit tests for P3.6 memory (short-term + semantic long-term).

Short-term uses a real ``ChatSession`` + ``ChatMessage`` round-trip so
the ordering contract (oldest-first into the prompt) is pinned. Long-term
uses the deterministic embedder so the cosine ranking is stable without
any real LLM/embedding provider.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.agent_memory import AgentMemoryEntry
from app.db.models.conversation import ChatMessage, ChatSession
from app.services.agents.engine import EventType
from app.services.agents.memory import (
    MemoryRecord,
    NullMemoryStore,
    SqlSemanticMemoryStore,
    read_recent_turns,
    recall_with_events,
    remember_with_events,
)


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", future=True)
    from app.db.models import (  # noqa: F401
        agent,
        agent_event,
        agent_memory,
        audit_log,
        conversation,
        eval,
        knowledge,
        prompt_template,
        rag_recall_log,
        rule,
        runtime_log,
        system_setting,
    )

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Short-term: ChatMessage reader
# ---------------------------------------------------------------------------


def _seed_chat(session: Session, session_id: str, turns: list[tuple[str, str]]) -> None:
    chat = ChatSession(id=session_id, tenant_id="t1", customer_id="c1")
    session.add(chat)
    session.flush()
    base = datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC)
    for offset, (role, content) in enumerate(turns):
        session.add(
            ChatMessage(
                id=str(uuid4()),
                session_id=session_id,
                role=role,
                content=content,
                metadata_json={},
                created_at=base + timedelta(minutes=offset),
            )
        )
    session.flush()


def test_read_recent_turns_returns_oldest_first(session: Session) -> None:
    _seed_chat(
        session,
        "sess-1",
        [
            ("user", "你好"),
            ("assistant", "你好，请问有什么可以帮您？"),
            ("user", "北京酒店报销上限多少？"),
            ("assistant", "650 元。"),
        ],
    )

    turns = read_recent_turns(session, session_id="sess-1", limit=10)
    contents = [t.content for t in turns]
    assert contents == [
        "你好",
        "你好，请问有什么可以帮您？",
        "北京酒店报销上限多少？",
        "650 元。",
    ]


def test_read_recent_turns_respects_limit_from_tail(session: Session) -> None:
    _seed_chat(
        session,
        "sess-2",
        [
            ("user", "msg-1"),
            ("user", "msg-2"),
            ("user", "msg-3"),
            ("user", "msg-4"),
        ],
    )
    turns = read_recent_turns(session, session_id="sess-2", limit=2)
    # The most recent two, oldest-first.
    assert [t.content for t in turns] == ["msg-3", "msg-4"]


def test_read_recent_turns_zero_limit_is_empty(session: Session) -> None:
    _seed_chat(session, "sess-3", [("user", "hi")])
    assert read_recent_turns(session, session_id="sess-3", limit=0) == []


def test_read_recent_turns_unknown_session_is_empty(session: Session) -> None:
    assert read_recent_turns(session, session_id="missing", limit=5) == []


# ---------------------------------------------------------------------------
# Long-term: semantic store
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory_store(session: Session) -> SqlSemanticMemoryStore:
    # The conftest test_environment fixture sets VECTOR_STORE_PROVIDER=noop
    # and clears the settings cache; EMBEDDING_PROVIDER defaults to
    # "deterministic" so no real HTTP is called.
    return SqlSemanticMemoryStore(session)


def test_remember_inserts_row_with_embedding(
    session: Session, memory_store: SqlSemanticMemoryStore
) -> None:
    record = memory_store.remember(
        tenant_id="t1",
        user_id="u1",
        content="用户偏好 经济舱",
        key="flight_preference",
        metadata={"source": "ticket_42"},
    )
    session.commit()

    assert record.id
    row = session.execute(
        select(AgentMemoryEntry).where(AgentMemoryEntry.id == record.id)
    ).scalar_one()
    assert row.content == "用户偏好 经济舱"
    assert row.key == "flight_preference"
    assert row.metadata_json == {"source": "ticket_42"}
    assert isinstance(row.embedding_json, list) and len(row.embedding_json) > 0


def test_remember_rejects_blank_content(memory_store: SqlSemanticMemoryStore) -> None:
    with pytest.raises(ValueError):
        memory_store.remember(tenant_id="t1", user_id="u1", content="   ")


def test_recall_returns_most_similar_first(
    session: Session, memory_store: SqlSemanticMemoryStore
) -> None:
    memory_store.remember(
        tenant_id="t1", user_id="u1", content="北京酒店报销上限为 650 元", key="beijing_hotel_cap"
    )
    memory_store.remember(
        tenant_id="t1", user_id="u1", content="上海酒店报销上限为 550 元", key="shanghai_hotel_cap"
    )
    memory_store.remember(
        tenant_id="t1", user_id="u1", content="差旅机票优先经济舱", key="flight_policy"
    )
    session.commit()

    hits = memory_store.recall(tenant_id="t1", user_id="u1", query="北京酒店 报销 上限", top_k=2)
    assert len(hits) >= 1
    # Top hit should match the Beijing entry, not flight policy.
    assert hits[0].key == "beijing_hotel_cap"
    # Score ordered non-increasing.
    from itertools import pairwise

    for left, right in pairwise(hits):
        assert left.score >= right.score


def test_recall_scopes_to_tenant_and_user(
    session: Session, memory_store: SqlSemanticMemoryStore
) -> None:
    """A recall from (t1, u1) must never see rows written by (t2, u2),
    even if their content matches the query word-for-word.
    """
    memory_store.remember(tenant_id="t1", user_id="u1", content="北京酒店报销上限 650")
    memory_store.remember(tenant_id="t2", user_id="u2", content="北京酒店报销上限 650")
    memory_store.remember(tenant_id="t1", user_id="u-other", content="北京酒店报销上限 650")
    session.commit()

    hits = memory_store.recall(tenant_id="t1", user_id="u1", query="北京酒店", top_k=10)
    assert len(hits) == 1
    assert hits[0].tenant_id == "t1" and hits[0].user_id == "u1"


def test_recall_empty_query_returns_empty(memory_store: SqlSemanticMemoryStore) -> None:
    assert memory_store.recall(tenant_id="t1", user_id="u1", query="   ", top_k=3) == []


def test_recall_filters_below_min_score(session: Session) -> None:
    store = SqlSemanticMemoryStore(session, min_score=0.99)  # effectively require exact match
    store.remember(tenant_id="t1", user_id="u1", content="北京酒店报销上限")
    store.remember(tenant_id="t1", user_id="u1", content="完全不相关的内容")
    session.commit()

    # Query shares no tokens with the second entry; min_score 0.99 rules
    # out everything except (near-)exact matches.
    hits = store.recall(tenant_id="t1", user_id="u1", query="不可能匹配的随机问题 xyz abc", top_k=5)
    assert hits == []


def test_recall_top_k_zero_returns_empty(
    session: Session, memory_store: SqlSemanticMemoryStore
) -> None:
    memory_store.remember(tenant_id="t1", user_id="u1", content="北京酒店")
    session.commit()
    assert memory_store.recall(tenant_id="t1", user_id="u1", query="北京", top_k=0) == []


def test_recall_respects_top_k_cap(session: Session, memory_store: SqlSemanticMemoryStore) -> None:
    for idx in range(5):
        memory_store.remember(tenant_id="t1", user_id="u1", content=f"北京酒店报销上限条款 {idx}")
    session.commit()

    hits = memory_store.recall(tenant_id="t1", user_id="u1", query="北京酒店", top_k=3)
    assert len(hits) == 3


# ---------------------------------------------------------------------------
# Null store
# ---------------------------------------------------------------------------


def test_null_store_remember_is_noop() -> None:
    store = NullMemoryStore()
    record = store.remember(tenant_id="t1", user_id="u1", content="anything")
    assert isinstance(record, MemoryRecord)
    assert record.id == ""
    assert record.content == "anything"


def test_null_store_recall_is_always_empty() -> None:
    store = NullMemoryStore()
    assert store.recall(tenant_id="t1", user_id="u1", query="北京酒店", top_k=10) == []


# ---------------------------------------------------------------------------
# Event-emitting wrappers
# ---------------------------------------------------------------------------


def test_remember_with_events_emits_memory_write(
    session: Session, memory_store: SqlSemanticMemoryStore
) -> None:
    record, events = remember_with_events(
        memory_store,
        tenant_id="t1",
        user_id="u1",
        content="用户偏好 经济舱",
        key="flight_preference",
    )
    session.commit()

    assert record.id
    assert len(events) == 1
    event = events[0]
    assert event.event_type == EventType.MEMORY_WRITE
    assert event.payload["memory_id"] == record.id
    assert event.payload["key"] == "flight_preference"
    assert event.payload["tenant_id"] == "t1"


def test_recall_with_events_reports_hit_count(
    session: Session, memory_store: SqlSemanticMemoryStore
) -> None:
    memory_store.remember(tenant_id="t1", user_id="u1", content="北京酒店报销上限 650")
    memory_store.remember(tenant_id="t1", user_id="u1", content="上海酒店报销上限 550")
    session.commit()

    hits, events = recall_with_events(
        memory_store, tenant_id="t1", user_id="u1", query="北京酒店", top_k=5
    )
    assert len(hits) >= 1
    assert len(events) == 1
    event = events[0]
    assert event.event_type == EventType.MEMORY_READ
    assert event.payload["hit_count"] == len(hits)
    assert event.payload["tenant_id"] == "t1"


def test_recall_with_events_zero_hits_still_emits_event(
    memory_store: SqlSemanticMemoryStore,
) -> None:
    hits, events = recall_with_events(
        memory_store, tenant_id="t1", user_id="u1", query="随机问题", top_k=3
    )
    assert hits == []
    # Even on a miss, the engine sees a MEMORY_READ so the timeline
    # records that the node consulted memory.
    assert len(events) == 1
    assert events[0].payload["hit_count"] == 0
