from __future__ import annotations

from app.services.agents.engine import EventType, TimelineEvent
from app.services.agents.policy_domain import choose_policy_specialist_plan
from app.services.agents.policy_supervisor import execute_policy_supervisor
from app.services.agents.state import TimelineStep
from app.services.agents.tool_gateway import GuardedToolResult


def _guarded_result(
    *,
    question: str,
    answer: str,
    confidence: float = 0.9,
    citations: list[dict[str, object]] | None = None,
) -> GuardedToolResult:
    return GuardedToolResult(
        tool_name="policy_search",
        status="completed",
        latency_ms=12,
        input_payload={"question": question},
        output_payload={
            "answer": answer,
            "confidence": confidence,
            "citations": citations or [{"document_id": "doc-1", "chunk_id": answer}],
            "retrieval_mode": "stubbed",
        },
        error=None,
        guardrail_events=[],
        engine_events=[
            TimelineEvent(
                sequence=0,
                event_type=EventType.TOOL_CALL_END,
                node_name="policy_search",
                payload={"question": question},
            )
        ],
    )


def test_policy_specialist_plan_detects_mixed_domains() -> None:
    plan = choose_policy_specialist_plan(
        "北京酒店含早超标，同时国内机票想订 business class，这张差旅报销单怎么处理？"
    )

    assert [item.domain for item in plan] == ["hotel", "flight", "reimbursement"]
    assert [item.specialist for item in plan] == [
        "hotel_policy_agent",
        "flight_policy_agent",
        "reimbursement_policy_agent",
    ]


def test_execute_policy_supervisor_aggregates_mixed_domains(
    client,
    monkeypatch,
) -> None:
    def fake_run_guarded_tool(
        tool_name: str,
        raw_input: dict[str, object],
        *,
        thread_id: str,
        approved: bool = False,
    ) -> GuardedToolResult:
        question = str(raw_input["question"])
        assert tool_name == "policy_search"
        assert approved is False
        if "酒店" in question or "住宿" in question:
            return _guarded_result(
                question=question,
                answer="酒店域结论：北京 L2 每晚标准 700 元，760 元属于超标。",
            )
        if "机票" in question or "business class" in question.lower() or "舱位" in question:
            return _guarded_result(
                question=question,
                answer="机票域结论：国内 business class 需要额外审批。",
            )
        return _guarded_result(
            question=question,
            answer="报销域结论：发票抬头、税号和进项税需要分别核查。",
        )

    monkeypatch.setattr(
        "app.services.agents.policy_supervisor.run_guarded_tool",
        fake_run_guarded_tool,
    )

    result = execute_policy_supervisor(
        question="北京酒店 760 元含早，同时国内机票想订 business class，这张报销单是否合规？",
        tenant_id="t1",
        customer_id="c1",
        thread_id="thread-mixed-ok",
        run_id="run-mixed-ok",
        user_id="u1",
        route_name="policy_qa",
        base_timeline=[
            TimelineStep(node_name="route", status="completed", detail="entered policy flow")
        ],
    )

    assert result.requires_human_review is False
    assert result.output["specialist"] == "mixed_policy_supervisor"
    assert result.output["retrieval_trace"]["router"]["domain"] == "mixed"
    assert result.output["specialist_plan"] == [
        "hotel_policy_agent",
        "flight_policy_agent",
        "reimbursement_policy_agent",
    ]
    assert set(result.output["coverage"]["per_domain"]) == {"hotel", "flight", "reimbursement"}
    assert result.output["missing_dimensions"] == []
    assert len(result.output["profile_reports"]) == 3
    assert "酒店域结论" in result.output["answer"]
    assert "机票域结论" in result.output["answer"]
    assert "报销域结论" in result.output["answer"]


def test_execute_policy_supervisor_interrupts_when_any_domain_incomplete(
    client,
    monkeypatch,
) -> None:
    def fake_run_guarded_tool(
        tool_name: str,
        raw_input: dict[str, object],
        *,
        thread_id: str,
        approved: bool = False,
    ) -> GuardedToolResult:
        question = str(raw_input["question"])
        if "审批条件" in question or "审批要求" in question:
            return _guarded_result(
                question=question,
                answer="机票审批证据不足。",
                confidence=0.05,
                citations=[],
            )
        if "机票" in question or "business class" in question.lower() or "舱位" in question:
            return _guarded_result(
                question=question,
                answer="机票域结论：默认规则已找到。",
            )
        if "酒店" in question or "住宿" in question:
            return _guarded_result(
                question=question,
                answer="酒店域结论：房费标准已找到。",
            )
        return _guarded_result(
            question=question,
            answer="报销域结论：基础报销规则已找到。",
        )

    monkeypatch.setattr(
        "app.services.agents.policy_supervisor.run_guarded_tool",
        fake_run_guarded_tool,
    )

    result = execute_policy_supervisor(
        question="北京酒店 760 元，同时国内机票想订 business class，这张报销单是否合规？",
        tenant_id="t1",
        customer_id="c1",
        thread_id="thread-mixed-review",
        run_id="run-mixed-review",
        user_id="u1",
        route_name="policy_qa",
        base_timeline=[],
    )

    assert result.requires_human_review is True
    assert result.status == "needs_review"
    assert result.output["specialist"] == "mixed_policy_supervisor"
    assert "flight.approval_requirement" in result.output["missing_dimensions"]
    assert result.output["interrupt"] is not None
    assert result.output["interrupt"]["kind"] == "completeness_review"
