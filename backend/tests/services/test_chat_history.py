"""Unit tests for the multi-turn history loader (P11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.models.conversation import ChatMessage, ChatSession
from app.db.session import SessionLocal, init_db
from app.services.chat_history import (
    ChatHistoryTurn,
    load_recent_turns,
    turns_to_messages,
)


def _seed_session(messages: list[tuple[str, str]]) -> str:
    """Create a ChatSession + ordered ChatMessages, return session_id."""
    init_db()
    session_id = str(uuid4())
    base = datetime.now(UTC)
    with SessionLocal() as session:
        session.add(
            ChatSession(
                id=session_id,
                tenant_id="t1",
                customer_id="c1",
            )
        )
        for offset, (role, content) in enumerate(messages):
            session.add(
                ChatMessage(
                    id=str(uuid4()),
                    session_id=session_id,
                    role=role,
                    content=content,
                    created_at=base + timedelta(seconds=offset),
                )
            )
        session.commit()
    return session_id


def test_load_recent_turns_returns_empty_for_blank_session_id() -> None:
    init_db()
    with SessionLocal() as session:
        assert load_recent_turns(session, session_id=None, max_turns=5) == []
        assert load_recent_turns(session, session_id="", max_turns=5) == []


def test_load_recent_turns_returns_empty_when_max_turns_zero() -> None:
    session_id = _seed_session([("user", "Q1"), ("assistant", "A1")])
    with SessionLocal() as session:
        assert load_recent_turns(session, session_id=session_id, max_turns=0) == []


def test_load_recent_turns_pairs_user_with_following_assistant() -> None:
    session_id = _seed_session(
        [
            ("user", "北京住宿标准是多少？"),
            ("assistant", "L2 在 A 档城市是 700 元/晚。"),
            ("user", "那广州呢？"),
            ("assistant", "广州也属于 A 档，标准相同。"),
        ]
    )
    with SessionLocal() as session:
        turns = load_recent_turns(session, session_id=session_id, max_turns=5)

    assert turns == [
        ChatHistoryTurn(
            user_message="北京住宿标准是多少？",
            assistant_message="L2 在 A 档城市是 700 元/晚。",
        ),
        ChatHistoryTurn(
            user_message="那广州呢？",
            assistant_message="广州也属于 A 档，标准相同。",
        ),
    ]


def test_load_recent_turns_caps_at_max_turns_keeping_newest() -> None:
    session_id = _seed_session(
        [
            ("user", "Q1"),
            ("assistant", "A1"),
            ("user", "Q2"),
            ("assistant", "A2"),
            ("user", "Q3"),
            ("assistant", "A3"),
        ]
    )
    with SessionLocal() as session:
        turns = load_recent_turns(session, session_id=session_id, max_turns=2)

    # Newest 2 turns kept (Q2/A2 and Q3/A3); Q1/A1 dropped.
    assert [t.user_message for t in turns] == ["Q2", "Q3"]


def test_load_recent_turns_drops_orphan_assistant_with_no_user() -> None:
    # An assistant row with no preceding user must be ignored — feeding a
    # half-turn confuses the LLM more than helps.
    session_id = _seed_session(
        [
            ("assistant", "orphan"),
            ("user", "Q1"),
            ("assistant", "A1"),
        ]
    )
    with SessionLocal() as session:
        turns = load_recent_turns(session, session_id=session_id, max_turns=5)

    assert len(turns) == 1
    assert turns[0].user_message == "Q1"


def test_load_recent_turns_drops_trailing_unanswered_user() -> None:
    # The current in-flight user message is appended by the caller; the
    # loader must not return a half-turn for it.
    session_id = _seed_session(
        [
            ("user", "Q1"),
            ("assistant", "A1"),
            ("user", "Q2 in flight"),
        ]
    )
    with SessionLocal() as session:
        turns = load_recent_turns(session, session_id=session_id, max_turns=5)

    assert [t.user_message for t in turns] == ["Q1"]


def test_turns_to_messages_flattens_to_alternating_roles() -> None:
    flat = turns_to_messages(
        [
            ChatHistoryTurn(user_message="Q1", assistant_message="A1"),
            ChatHistoryTurn(user_message="Q2", assistant_message="A2"),
        ]
    )
    assert [m["role"] for m in flat] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in flat] == ["Q1", "A1", "Q2", "A2"]
