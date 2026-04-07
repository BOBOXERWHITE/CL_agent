from __future__ import annotations

from app.core.config import get_settings
from app.services.agents.nodes import append_timeline_step
from app.services.agents.state import AgentExecutionResult, TimelineStep
from app.services.rag.query_engine import answer_policy_question


def execute_policy_graph(
    *,
    question: str,
    tenant_id: str,
    customer_id: str,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    timeline = list(base_timeline)
    append_timeline_step(
        timeline,
        node_name="policy_retrieval",
        status="completed",
        detail="已执行政策检索与证据整理。",
    )
    answer_result = answer_policy_question(question=question, tenant_id=tenant_id, customer_id=customer_id)
    requires_human_review = answer_result.confidence < get_settings().chat_confidence_threshold
    if requires_human_review:
        append_timeline_step(
            timeline,
            node_name="human_review_checkpoint",
            status="required",
            detail="当前证据强度不足，已标记人工复核。",
        )

    citations = [
        {
            "chunk_id": citation.chunk_id,
            "document_id": citation.document_id,
            "document_title": citation.document_title,
            "snippet": citation.snippet,
            "score": citation.score,
        }
        for citation in answer_result.citations
    ]
    return AgentExecutionResult(
        agent_name="travel_policy_agent",
        route_name=route_name,
        status="needs_review" if requires_human_review else "completed",
        confidence=answer_result.confidence,
        requires_human_review=requires_human_review,
        output={
            "answer": answer_result.answer,
            "citations": citations,
            "retrieval_trace": answer_result.retrieval_trace.as_dict(),
        },
        timeline=timeline,
        tool_calls=[],
    )
