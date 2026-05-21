"""Multi-turn chat history loader (P11).

The RAG main path (``answer_policy_question_async``) treats every request
as a single shot: ``messages = [system, user]``. That breaks paraphrase
follow-ups like "那广州呢？" because the LLM never sees the prior turn
that established "what" the user is asking about.

This module pulls the last N completed (user, assistant) turns from
``ChatMessage`` and exposes them as a flat ``[user, assistant, ...]``
list ordered oldest → newest. Callers prepend the result to the LLM
``messages`` array, then append the current user turn.

Design notes
------------
- "Turn" means one ``ChatMessage`` row of role ``user`` immediately
  followed by one of role ``assistant``. Orphan rows (a user message
  whose assistant reply hasn't been persisted yet, or an assistant row
  with no preceding user) are dropped — feeding a half-turn to the
  model confuses it more than helps.
- Cap is on **turns**, not on rows: ``max_turns=5`` returns up to 10
  rows. Token budget is the caller's responsibility (the prompt builder
  truncates if the total exceeds the model context window).
- Sort order in the DB query is ``created_at ASC`` so we walk in the
  natural conversation order and pair user→assistant deterministically.
- The current in-flight user message is **not** included by the loader;
  callers append it themselves so they can apply prompt-template-
  specific framing ("请基于给定证据回答…") to that one turn only.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.conversation import ChatMessage


@dataclass(frozen=True)
class ChatHistoryTurn:
    """One completed user→assistant exchange in a chat thread."""

    user_message: str
    assistant_message: str

    def as_messages(self) -> list[dict[str, str]]:
        """Render as the two consecutive OpenAI-style message dicts."""
        return [
            {"role": "user", "content": self.user_message},
            {"role": "assistant", "content": self.assistant_message},
        ]


def load_recent_turns(
    session: Session, *, session_id: str | None, max_turns: int
) -> list[ChatHistoryTurn]:
    """Return up to ``max_turns`` completed turns for ``session_id``.

    Empty list when:
    - ``session_id`` is falsy (a fresh thread)
    - ``max_turns <= 0`` (multi-turn disabled in business settings)
    - the session has no rows yet
    - all rows are orphan halves (no paired user→assistant in order)

    Newest turn is last in the returned list so the caller can extend
    the LLM messages array directly.
    """
    if not session_id or max_turns <= 0:
        return []

    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    ).all()

    turns: list[ChatHistoryTurn] = []
    pending_user: str | None = None
    for row in rows:
        role = (row.role or "").strip().lower()
        content = (row.content or "").strip()
        if not content:
            continue
        if role == "user":
            pending_user = content
        elif role == "assistant" and pending_user is not None:
            turns.append(
                ChatHistoryTurn(
                    user_message=pending_user,
                    assistant_message=content,
                )
            )
            pending_user = None

    if max_turns and len(turns) > max_turns:
        turns = turns[-max_turns:]
    return turns


def turns_to_messages(turns: list[ChatHistoryTurn]) -> list[dict[str, str]]:
    """Flatten ``[turn, turn, ...]`` into ``[user, assistant, ...]``."""
    messages: list[dict[str, str]] = []
    for turn in turns:
        messages.extend(turn.as_messages())
    return messages


__all__ = ["ChatHistoryTurn", "load_recent_turns", "turns_to_messages"]
