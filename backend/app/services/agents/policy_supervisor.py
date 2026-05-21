from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from statistics import fmean
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.core.config import get_settings
from app.db.models.agent import AgentRun, AgentThread, AgentThreadCheckpoint
from app.db.session import scoped_session
from app.services.agents.engine import EventType, TimelineEvent
from app.services.agents.memory import SqlSemanticMemoryStore
from app.services.agents.nodes import append_timeline_step
from app.services.agents.policy_domain import (
    choose_policy_specialist,
    choose_policy_specialist_plan,
)
from app.services.agents.policy_graph import execute_policy_graph
from app.services.agents.policy_profiles import (
    PolicyDomainProfile,
    get_policy_profile,
    get_policy_profile_by_specialist,
)
from app.services.agents.state import AgentExecutionResult, TimelineStep, ToolCallRecord
from app.services.agents.tool_gateway import run_guarded_tool


def _merge_parallel_reports(
    existing: dict[str, dict[str, Any]] | None,
    new: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Reducer for the parallel-fan-out accumulator field.

    Each ``mixed_profile_worker`` invocation writes
    ``{profile.domain: {report, tool_calls, guardrail_events, engine_events}}``
    into ``parallel_profile_reports``. LangGraph runs the workers in
    parallel via ``Send`` and calls this reducer to merge their writes
    into a single dict keyed by domain. The reducer is associative +
    commutative so worker arrival order does not affect the final state.
    """
    base: dict[str, dict[str, Any]] = dict(existing or {})
    if new:
        for domain, bundle in new.items():
            base[domain] = bundle
    return base


class PolicySupervisorState(TypedDict, total=False):
    question: str
    tenant_id: str
    customer_id: str
    thread_id: str
    run_id: str
    user_id: str
    route_name: str
    policy_domain: str
    specialist: str
    specialist_plan: list[str]
    planned_domains: list[str]
    domain_confidence: float
    fallback_reason: str | None
    prior_thread_summary: dict[str, Any]
    facts: dict[str, Any]
    required_dimensions: list[str]
    subquestions: list[dict[str, str]]
    subresults: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    coverage: dict[str, Any]
    missing_dimensions: list[str]
    guardrail_events: list[dict[str, Any]]
    engine_events: list[TimelineEvent]
    tool_calls: list[dict[str, Any]]
    interrupt: dict[str, Any] | None
    profile_reports: list[dict[str, Any]]
    final_result: dict[str, Any]
    # P7 Phase A: accumulator for parallel-fan-out worker outputs.
    # Annotated with a custom reducer so multiple Send branches can
    # write concurrently without LangGraph raising InvalidUpdateError.
    # The ``mixed_reducer`` node consumes this and writes the same
    # shape into the canonical state fields (profile_reports, etc.).
    parallel_profile_reports: Annotated[dict[str, dict[str, Any]], _merge_parallel_reports]


def _next_sequence(events: list[TimelineEvent]) -> int:
    if not events:
        return 0
    return max(event.sequence for event in events) + 1


def _append_event(
    events: list[TimelineEvent],
    event_type: EventType,
    node_name: str,
    payload: dict[str, Any],
) -> list[TimelineEvent]:
    return [
        *events,
        TimelineEvent(
            sequence=_next_sequence(events),
            event_type=event_type,
            node_name=node_name,
            payload=payload,
        ),
    ]


def _merge_citations(subresults: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for result in subresults:
        for citation in result.get("citations", []):
            key = (
                citation.get("chunk_id")
                or f"{citation.get('document_id')}:{citation.get('snippet')}"
            )
            if key not in deduped:
                deduped[key] = citation
    return list(deduped.values())


def _average_confidence(results: list[dict[str, Any]]) -> float:
    confidences = [float(result.get("confidence", 0.0)) for result in results]
    if not confidences:
        return 0.0
    return round(float(fmean(confidences)), 4)


def _active_profile(state: PolicySupervisorState) -> PolicyDomainProfile | None:
    specialist = state.get("specialist")
    if specialist:
        profile = get_policy_profile_by_specialist(str(specialist))
        if profile is not None:
            return profile
    domain = state.get("policy_domain")
    if domain:
        return get_policy_profile(str(domain))
    return None


def _planned_profiles(state: PolicySupervisorState) -> list[PolicyDomainProfile]:
    domains = [
        str(domain) for domain in state.get("planned_domains", []) if str(domain) != "generic"
    ]
    profiles = [
        profile for domain in domains if (profile := get_policy_profile(domain)) is not None
    ]
    if profiles:
        return profiles
    active = _active_profile(state)
    return [active] if active is not None else []


def _read_prior_thread_summary(thread_id: str, tenant_id: str) -> dict[str, Any]:
    with scoped_session(tenant_id) as session:
        thread = session.get(AgentThread, thread_id)
        if thread is None:
            return {"thread_exists": False, "recent_runs": [], "long_term_memory": []}

        recent_runs = list(
            session.query(AgentRun)
            .filter(AgentRun.thread_id == thread_id)
            .order_by(AgentRun.updated_at.desc())
            .limit(5)
            .all()
        )
        memory_hits: list[dict[str, Any]] = []
        try:
            store = SqlSemanticMemoryStore(session)
            memory_hits = [
                {
                    "key": hit.key,
                    "content": hit.content,
                    "score": hit.score,
                    "created_at": hit.created_at.isoformat(),
                }
                for hit in store.recall(
                    tenant_id=tenant_id,
                    user_id=thread.customer_id,
                    query=thread.specialist or "policy",
                    top_k=3,
                )
            ]
        except Exception:
            memory_hits = []

        return {
            "thread_exists": True,
            "status": thread.status,
            "specialist": thread.specialist,
            "memory_summary": dict(thread.memory_summary_json or {}),
            "pending_interrupt": dict(thread.pending_interrupt_json or {}),
            "recent_runs": [
                {
                    "run_id": run.id,
                    "status": run.status,
                    "agent_name": run.agent_name,
                    "updated_at": run.updated_at.isoformat(),
                    "answer_preview": str((run.output_json or {}).get("answer", ""))[:240],
                }
                for run in recent_runs
            ],
            "long_term_memory": memory_hits,
        }


def _route_node(state: PolicySupervisorState) -> PolicySupervisorState:
    decision = choose_policy_specialist(state["question"])
    specialist_plan = choose_policy_specialist_plan(state["question"])
    planned_domains = [item.domain for item in specialist_plan]
    planned_specialists = [item.specialist for item in specialist_plan]
    policy_domain = (
        "mixed"
        if len(planned_domains) > 1 and any(domain != "generic" for domain in planned_domains)
        else decision.domain
    )
    specialist = "mixed_policy_supervisor" if policy_domain == "mixed" else decision.specialist
    events = _append_event(
        state.get("engine_events", []),
        EventType.ROUTE_DECISION,
        "policy_supervisor",
        {
            "domain": policy_domain,
            "specialist": specialist,
            "confidence": decision.confidence,
            "fallback_reason": decision.fallback_reason,
            "planned_domains": planned_domains,
            "specialist_plan": planned_specialists,
        },
    )
    return {
        "policy_domain": policy_domain,
        "specialist": specialist,
        "specialist_plan": planned_specialists,
        "planned_domains": planned_domains,
        "domain_confidence": decision.confidence,
        "fallback_reason": decision.fallback_reason,
        "engine_events": events,
    }


def _route_after_policy(state: PolicySupervisorState) -> str:
    if state.get("policy_domain") == "mixed":
        return "mixed"
    return "profiled" if _active_profile(state) is not None else "generic"


def _profile_fact_node(state: PolicySupervisorState) -> PolicySupervisorState:
    profile = _active_profile(state)
    if profile is None:
        return {}
    facts = profile.extract_facts(state["question"])
    dimensions = profile.required_dimensions(state["question"], facts)
    events = _append_event(
        state.get("engine_events", []),
        EventType.MEMORY_READ,
        f"{profile.domain}_fact_extract",
        {
            "thread_id": state["thread_id"],
            "profile": profile.domain,
            "fact_count": len(facts),
            "required_dimensions": dimensions,
        },
    )
    return {"facts": facts, "required_dimensions": dimensions, "engine_events": events}


def _profile_plan_node(state: PolicySupervisorState) -> PolicySupervisorState:
    profile = _active_profile(state)
    if profile is None:
        return {"subquestions": [{"dimension": "primary", "question": state["question"]}]}
    return {
        "subquestions": profile.build_subquestions(
            state["question"],
            state.get("facts", {}),
            state.get("required_dimensions", []),
        )
    }


def _profile_execute_node(state: PolicySupervisorState) -> PolicySupervisorState:
    profile = _active_profile(state)
    subresults: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    guardrail_events = list(state.get("guardrail_events", []))
    engine_events = list(state.get("engine_events", []))
    for subquestion in state.get("subquestions", []):
        guarded = run_guarded_tool(
            "policy_search",
            {
                "question": subquestion["question"],
                "tenant_id": state["tenant_id"],
                "customer_id": state["customer_id"],
            },
            thread_id=state["thread_id"],
        )
        guardrail_events.extend(guarded.guardrail_events)
        for event in guarded.engine_events:
            engine_events = _append_event(
                engine_events,
                event.event_type,
                event.node_name,
                dict(event.payload),
            )
        tool_calls.append(
            {
                "tool_name": guarded.tool_name,
                "status": guarded.status,
                "latency_ms": guarded.latency_ms,
                "input_payload": guarded.input_payload,
                "output_payload": guarded.output_payload,
            }
        )
        subresults.append(
            {
                "dimension": subquestion["dimension"],
                "question": subquestion["question"],
                "status": guarded.status,
                "answer": guarded.output_payload.get("answer", ""),
                "confidence": guarded.output_payload.get("confidence", 0.0),
                "citations": guarded.output_payload.get("citations", []),
                "retrieval_mode": guarded.output_payload.get("retrieval_mode", "unknown"),
            }
        )

    profile_domain = profile.domain if profile is not None else "generic"
    return {
        "subresults": subresults,
        "tool_calls": tool_calls,
        "guardrail_events": guardrail_events,
        "engine_events": _append_event(
            engine_events,
            EventType.NODE_END,
            f"{profile_domain}_execute_subquestions",
            {"subquestion_count": len(subresults)},
        ),
        "citations": _merge_citations(subresults),
    }


def _profile_validate_node(state: PolicySupervisorState) -> PolicySupervisorState:
    profile = _active_profile(state)
    if profile is None:
        return {
            "coverage": {
                "required_dimensions": [],
                "covered_dimensions": [],
                "coverage_ratio": 1.0,
            },
            "missing_dimensions": [],
            "interrupt": None,
        }

    threshold = get_settings().chat_confidence_threshold
    covered_dimensions = [
        result["dimension"]
        for result in state.get("subresults", [])
        if result["dimension"] != "primary"
        and result.get("status") == "completed"
        and float(result.get("confidence", 0.0)) >= threshold
        and bool(result.get("citations"))
    ]
    required_dimensions = list(state.get("required_dimensions", []))
    missing_dimensions = [item for item in required_dimensions if item not in covered_dimensions]
    coverage_ratio = (
        1.0
        if not required_dimensions
        else round(
            len(covered_dimensions) / len(required_dimensions),
            4,
        )
    )

    interrupt: dict[str, Any] | None = None
    guardrail_events = list(state.get("guardrail_events", []))
    engine_events = list(state.get("engine_events", []))
    if missing_dimensions:
        interrupt = {
            "kind": "completeness_review",
            "reason": profile.interrupt_reason,
            "missing_dimensions": missing_dimensions,
            "allowed_decisions": ["approve", "edit", "reject"],
        }
        guardrail_events.append(
            {
                "decision": "interrupt",
                "reason": profile.interrupt_reason,
                "missing_dimensions": missing_dimensions,
                "thread_id": state["thread_id"],
                "profile": profile.domain,
            }
        )
        engine_events = _append_event(
            engine_events,
            EventType.PAUSE,
            f"{profile.domain}_completeness_validator",
            {
                "reason": profile.interrupt_reason,
                "missing_dimensions": missing_dimensions,
            },
        )

    return {
        "coverage": {
            "required_dimensions": required_dimensions,
            "covered_dimensions": covered_dimensions,
            "coverage_ratio": coverage_ratio,
        },
        "missing_dimensions": missing_dimensions,
        "interrupt": interrupt,
        "guardrail_events": guardrail_events,
        "engine_events": engine_events,
    }


def _build_profile_report(
    profile: PolicyDomainProfile,
    *,
    thread_id: str,
    question: str,
    tenant_id: str,
    customer_id: str,
    starting_events: list[TimelineEvent],
    starting_guardrails: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[TimelineEvent]]:
    facts = profile.extract_facts(question)
    required_dimensions = profile.required_dimensions(question, facts)
    subquestions = profile.build_subquestions(question, facts, required_dimensions)
    engine_events = _append_event(
        list(starting_events),
        EventType.MEMORY_READ,
        f"{profile.domain}_fact_extract",
        {
            "thread_id": thread_id,
            "profile": profile.domain,
            "fact_count": len(facts),
            "required_dimensions": required_dimensions,
        },
    )
    guardrail_events = list(starting_guardrails)
    tool_calls: list[dict[str, Any]] = []
    subresults: list[dict[str, Any]] = []
    for subquestion in subquestions:
        guarded = run_guarded_tool(
            "policy_search",
            {
                "question": subquestion["question"],
                "tenant_id": tenant_id,
                "customer_id": customer_id,
            },
            thread_id=thread_id,
        )
        guardrail_events.extend(guarded.guardrail_events)
        for event in guarded.engine_events:
            engine_events = _append_event(
                engine_events,
                event.event_type,
                event.node_name,
                dict(event.payload),
            )
        tool_calls.append(
            {
                "tool_name": guarded.tool_name,
                "status": guarded.status,
                "latency_ms": guarded.latency_ms,
                "input_payload": guarded.input_payload,
                "output_payload": guarded.output_payload,
            }
        )
        subresults.append(
            {
                "dimension": subquestion["dimension"],
                "question": subquestion["question"],
                "status": guarded.status,
                "answer": guarded.output_payload.get("answer", ""),
                "confidence": guarded.output_payload.get("confidence", 0.0),
                "citations": guarded.output_payload.get("citations", []),
                "retrieval_mode": guarded.output_payload.get("retrieval_mode", "unknown"),
            }
        )

    threshold = get_settings().chat_confidence_threshold
    covered_dimensions = [
        result["dimension"]
        for result in subresults
        if result["dimension"] != "primary"
        and result.get("status") == "completed"
        and float(result.get("confidence", 0.0)) >= threshold
        and bool(result.get("citations"))
    ]
    missing_dimensions = [item for item in required_dimensions if item not in covered_dimensions]
    coverage_ratio = (
        1.0
        if not required_dimensions
        else round(
            len(covered_dimensions) / len(required_dimensions),
            4,
        )
    )
    interrupt: dict[str, Any] | None = None
    if missing_dimensions:
        interrupt = {
            "kind": "completeness_review",
            "reason": profile.interrupt_reason,
            "missing_dimensions": missing_dimensions,
            "allowed_decisions": ["approve", "edit", "reject"],
        }
        guardrail_events.append(
            {
                "decision": "interrupt",
                "reason": profile.interrupt_reason,
                "missing_dimensions": missing_dimensions,
                "thread_id": thread_id,
                "profile": profile.domain,
            }
        )
        engine_events = _append_event(
            engine_events,
            EventType.PAUSE,
            f"{profile.domain}_completeness_validator",
            {
                "reason": profile.interrupt_reason,
                "missing_dimensions": missing_dimensions,
            },
        )
    engine_events = _append_event(
        engine_events,
        EventType.NODE_END,
        f"{profile.domain}_execute_subquestions",
        {"subquestion_count": len(subresults)},
    )
    primary = next((item for item in subresults if item.get("dimension") == "primary"), None)
    domain_summary = next(
        (
            str(item.get("answer", "")).strip()
            for item in subresults
            if item.get("dimension") != "primary" and str(item.get("answer", "")).strip()
        ),
        primary.get("answer", "") if primary else "",
    )
    return (
        {
            "domain": profile.domain,
            "specialist": profile.specialist,
            "label": profile.label,
            "facts": facts,
            "required_dimensions": required_dimensions,
            "coverage": {
                "required_dimensions": required_dimensions,
                "covered_dimensions": covered_dimensions,
                "coverage_ratio": coverage_ratio,
            },
            "missing_dimensions": missing_dimensions,
            "interrupt": interrupt,
            "subresults": subresults,
            "citations": _merge_citations(subresults),
            "primary_answer": domain_summary,
        },
        tool_calls,
        guardrail_events,
        engine_events,
    )


def _mixed_execute_node(state: PolicySupervisorState) -> PolicySupervisorState:
    profiles = _planned_profiles(state)
    profile_reports: list[dict[str, Any]] = []
    tool_calls = list(state.get("tool_calls", []))
    guardrail_events = list(state.get("guardrail_events", []))
    engine_events = list(state.get("engine_events", []))
    aggregate_subresults: list[dict[str, Any]] = []
    aggregate_citations: list[dict[str, Any]] = []
    per_domain: dict[str, Any] = {}
    prefixed_required_dimensions: list[str] = []
    prefixed_covered_dimensions: list[str] = []
    missing_dimensions: list[str] = []

    for profile in profiles:
        report, profile_tool_calls, next_guardrails, next_events = _build_profile_report(
            profile,
            thread_id=state["thread_id"],
            question=state["question"],
            tenant_id=state["tenant_id"],
            customer_id=state["customer_id"],
            starting_events=engine_events,
            starting_guardrails=guardrail_events,
        )
        profile_reports.append(report)
        tool_calls.extend(profile_tool_calls)
        guardrail_events = next_guardrails
        engine_events = next_events
        per_domain[profile.domain] = report["coverage"]
        prefixed_required_dimensions.extend(
            [
                f"{profile.domain}.{dimension}"
                for dimension in report["coverage"]["required_dimensions"]
            ]
        )
        prefixed_covered_dimensions.extend(
            [
                f"{profile.domain}.{dimension}"
                for dimension in report["coverage"]["covered_dimensions"]
            ]
        )
        missing_dimensions.extend(
            [f"{profile.domain}.{dimension}" for dimension in report["missing_dimensions"]]
        )
        aggregate_subresults.extend(
            [
                {
                    **subresult,
                    "dimension": f"{profile.domain}.{subresult['dimension']}",
                }
                for subresult in report["subresults"]
            ]
        )
        aggregate_citations.extend(report["citations"])

    overall_coverage_ratio = (
        1.0
        if not prefixed_required_dimensions
        else round(
            len(prefixed_covered_dimensions) / len(prefixed_required_dimensions),
            4,
        )
    )
    interrupt = (
        {
            "kind": "completeness_review",
            "reason": "mixed-domain policy answer does not cover all required dimensions",
            "missing_dimensions": missing_dimensions,
            "allowed_decisions": ["approve", "edit", "reject"],
        }
        if missing_dimensions
        else None
    )

    if interrupt is not None:
        guardrail_events.append(
            {
                "decision": "interrupt",
                "reason": interrupt["reason"],
                "missing_dimensions": missing_dimensions,
                "thread_id": state["thread_id"],
                "profile": "mixed",
            }
        )
        engine_events = _append_event(
            engine_events,
            EventType.PAUSE,
            "mixed_domain_completeness_validator",
            {
                "reason": interrupt["reason"],
                "missing_dimensions": missing_dimensions,
                "domains": [report["domain"] for report in profile_reports],
            },
        )

    return {
        "facts": {report["domain"]: report["facts"] for report in profile_reports},
        "required_dimensions": prefixed_required_dimensions,
        "subquestions": [],
        "subresults": aggregate_subresults,
        "citations": _merge_citations([{"citations": aggregate_citations}]),
        "coverage": {
            "required_dimensions": prefixed_required_dimensions,
            "covered_dimensions": prefixed_covered_dimensions,
            "coverage_ratio": overall_coverage_ratio,
            "per_domain": per_domain,
        },
        "missing_dimensions": missing_dimensions,
        "guardrail_events": guardrail_events,
        "engine_events": engine_events,
        "tool_calls": tool_calls,
        "interrupt": interrupt,
        "profile_reports": profile_reports,
    }


def _generic_search_node(state: PolicySupervisorState) -> PolicySupervisorState:
    guarded = run_guarded_tool(
        "policy_search",
        {
            "question": state["question"],
            "tenant_id": state["tenant_id"],
            "customer_id": state["customer_id"],
        },
        thread_id=state["thread_id"],
    )
    engine_events = list(state.get("engine_events", []))
    for event in guarded.engine_events:
        engine_events = _append_event(
            engine_events,
            event.event_type,
            event.node_name,
            dict(event.payload),
        )
    return {
        "subresults": [
            {
                "dimension": "primary",
                "question": state["question"],
                "status": guarded.status,
                "answer": guarded.output_payload.get("answer", ""),
                "confidence": guarded.output_payload.get("confidence", 0.0),
                "citations": guarded.output_payload.get("citations", []),
                "retrieval_mode": guarded.output_payload.get("retrieval_mode", "unknown"),
            }
        ],
        "tool_calls": [
            {
                "tool_name": guarded.tool_name,
                "status": guarded.status,
                "latency_ms": guarded.latency_ms,
                "input_payload": guarded.input_payload,
                "output_payload": guarded.output_payload,
            }
        ],
        "citations": guarded.output_payload.get("citations", []),
        "coverage": {"required_dimensions": [], "covered_dimensions": [], "coverage_ratio": 1.0},
        "missing_dimensions": [],
        "guardrail_events": [*state.get("guardrail_events", []), *guarded.guardrail_events],
        "engine_events": engine_events,
    }


def _finalize_node(state: PolicySupervisorState) -> PolicySupervisorState:
    profile = _active_profile(state)
    subresults = list(state.get("subresults", []))
    primary = next((item for item in subresults if item.get("dimension") == "primary"), None)
    citations = _merge_citations(subresults)
    coverage = dict(state.get("coverage", {}))
    missing_dimensions = list(state.get("missing_dimensions", []))

    if missing_dimensions and profile is not None:
        labels = [profile.dimension_labels.get(item, item) for item in missing_dimensions]
        answer = (
            f"已完成{profile.label}政策多跳检查，但证据覆盖仍不完整。"
            f"已覆盖维度：{', '.join(coverage.get('covered_dimensions', [])) or '无'}。"
            f"仍缺少维度：{', '.join(labels)}。"
            "为避免给出不完整合规结论，本次结果已转入人工复核。"
        )
        if primary and primary.get("answer"):
            answer += f"\n\n当前已确认信息：{primary['answer']}"
    else:
        answer = primary["answer"] if primary else "未能生成政策答案。"

    final_result = {
        "answer": answer,
        "confidence": round(
            _average_confidence(subresults) * max(float(coverage.get("coverage_ratio", 1.0)), 0.5),
            4,
        ),
        "citations": citations,
        "coverage": coverage,
        "missing_dimensions": missing_dimensions,
        "guardrail_events": state.get("guardrail_events", []),
        "interrupt": state.get("interrupt"),
        "retrieval_trace": {
            "router": {
                "domain": state.get("policy_domain", "generic"),
                "specialist": state.get("specialist", "generic_policy_agent"),
                "confidence": state.get("domain_confidence", 0.0),
                "fallback_reason": state.get("fallback_reason"),
            },
            "coverage": coverage,
            "guardrail_events": state.get("guardrail_events", []),
            "thread_id": state["thread_id"],
        },
        "specialist": state.get("specialist", "generic_policy_agent"),
    }
    engine_events = _append_event(
        list(state.get("engine_events", [])),
        EventType.GRAPH_END,
        "policy_supervisor_finalize",
        {
            "specialist": final_result["specialist"],
            "requires_review": bool(state.get("interrupt")),
            "coverage_ratio": coverage.get("coverage_ratio", 0.0),
        },
    )
    return {"final_result": final_result, "engine_events": engine_events}


def _finalize_supervisor_node(state: PolicySupervisorState) -> PolicySupervisorState:
    profile_reports = list(state.get("profile_reports", []))
    subresults = list(state.get("subresults", []))
    coverage = dict(state.get("coverage", {}))
    missing_dimensions = list(state.get("missing_dimensions", []))
    planned_domains = list(state.get("planned_domains", []))
    specialist_plan = list(state.get("specialist_plan", []))
    citations = _merge_citations(profile_reports or subresults)

    if profile_reports:
        answer_lines: list[str] = ["已完成多领域政策拆分，按领域结论如下："]
        for report in profile_reports:
            label = str(report.get("label", report.get("domain", "未知领域")))
            primary_answer = (
                str(report.get("primary_answer", "")).strip() or "该领域未生成明确结论。"
            )
            answer_lines.append(f"{label}：{primary_answer}")
        if missing_dimensions:
            answer_lines.append("")
            answer_lines.append("当前证据仍未覆盖全部必答维度，结果已转入人工复核。")
            answer_lines.append(f"缺失维度：{', '.join(missing_dimensions)}")
        answer = "\n".join(answer_lines)
    else:
        profile = _active_profile(state)
        primary = next((item for item in subresults if item.get("dimension") == "primary"), None)
        if missing_dimensions and profile is not None:
            labels = [profile.dimension_labels.get(item, item) for item in missing_dimensions]
            answer = (
                f"已完成{profile.label}政策多跳检查，但证据覆盖仍不完整。"
                f"已覆盖维度：{', '.join(coverage.get('covered_dimensions', [])) or '无'}。"
                f"仍缺少维度：{', '.join(labels)}。"
                "为避免给出不完整合规结论，本次结果已转入人工复核。"
            )
            if primary and primary.get("answer"):
                answer += f"\n\n当前已确认信息：{primary['answer']}"
        else:
            answer = primary["answer"] if primary else "未能生成政策答案。"

    final_result = {
        "answer": answer,
        "confidence": round(
            _average_confidence(subresults) * max(float(coverage.get("coverage_ratio", 1.0)), 0.5),
            4,
        ),
        "citations": citations,
        "coverage": coverage,
        "missing_dimensions": missing_dimensions,
        "guardrail_events": state.get("guardrail_events", []),
        "interrupt": state.get("interrupt"),
        "retrieval_trace": {
            "router": {
                "domain": state.get("policy_domain", "generic"),
                "specialist": state.get("specialist", "generic_policy_agent"),
                "confidence": state.get("domain_confidence", 0.0),
                "fallback_reason": state.get("fallback_reason"),
                "planned_domains": planned_domains,
            },
            "coverage": coverage,
            "guardrail_events": state.get("guardrail_events", []),
            "thread_id": state["thread_id"],
            "specialist_plan": specialist_plan,
        },
        "specialist": state.get("specialist", "generic_policy_agent"),
        "specialist_plan": specialist_plan,
        "profile_reports": profile_reports,
    }
    engine_events = _append_event(
        list(state.get("engine_events", [])),
        EventType.GRAPH_END,
        "policy_supervisor_finalize",
        {
            "specialist": final_result["specialist"],
            "requires_review": bool(state.get("interrupt")),
            "coverage_ratio": coverage.get("coverage_ratio", 0.0),
            "planned_domains": planned_domains,
        },
    )
    return {"final_result": final_result, "engine_events": engine_events}


# ---------------------------------------------------------------------------
# P7 Phase A — parallel mixed-domain (Orchestrator-Worker via LangGraph Send)
# ---------------------------------------------------------------------------


class _ParallelWorkerInput(TypedDict):
    profile_domain: str
    thread_id: str
    question: str
    tenant_id: str
    customer_id: str


def _mixed_fan_out_router(state: PolicySupervisorState) -> list[Send]:
    """Fan out: emit one ``Send`` per planned profile so LangGraph runs
    them in parallel via the Pregel runtime.

    Each Send carries only the worker's own input — workers see a tiny
    private state, not the full ``PolicySupervisorState``. Their outputs
    land in ``parallel_profile_reports`` (annotated reducer above) and
    are aggregated by ``_mixed_reducer_node``.
    """
    profiles = _planned_profiles(state)
    base_input: _ParallelWorkerInput = {
        "profile_domain": "",
        "thread_id": state["thread_id"],
        "question": state["question"],
        "tenant_id": state["tenant_id"],
        "customer_id": state["customer_id"],
    }
    return [
        Send(
            "mixed_profile_worker",
            {**base_input, "profile_domain": profile.domain},
        )
        for profile in profiles
    ]


def _mixed_profile_worker_node(payload: _ParallelWorkerInput) -> PolicySupervisorState:
    """Run :func:`_build_profile_report` for one profile.

    LangGraph invokes this once per ``Send`` returned by the fan-out
    router. Concurrent invocations are safe because the worker is a
    pure function over its private ``payload`` — no shared mutable
    state. Each worker writes a single key into the
    ``parallel_profile_reports`` accumulator which the reducer node
    consolidates after the Pregel barrier.
    """
    profile = get_policy_profile(payload["profile_domain"])
    if profile is None:
        # Unknown domain — emit nothing; reducer will see an empty bundle
        # and skip it gracefully.
        return {"parallel_profile_reports": {}}
    report, tool_calls, guardrail_events, engine_events = _build_profile_report(
        profile,
        thread_id=payload["thread_id"],
        question=payload["question"],
        tenant_id=payload["tenant_id"],
        customer_id=payload["customer_id"],
        starting_events=[],
        starting_guardrails=[],
    )
    return {
        "parallel_profile_reports": {
            payload["profile_domain"]: {
                "report": report,
                "tool_calls": tool_calls,
                "guardrail_events": guardrail_events,
                "engine_events": engine_events,
            }
        }
    }


def _mixed_reducer_node(state: PolicySupervisorState) -> PolicySupervisorState:
    """Aggregate parallel-worker outputs into the same shape that
    :func:`_mixed_execute_node` produces in serial mode.

    The output contract MUST match serial mode bit-for-bit: same
    ``profile_reports`` ordering (by ``_planned_profiles`` order, not
    arrival order), same coverage / missing dimensions / interrupt
    blocks. Flipping ``AGENT_MIXED_EXECUTION`` between serial and
    parallel is a no-op for any downstream consumer.
    """
    reports_by_domain = state.get("parallel_profile_reports") or {}
    planned_profiles_in_order = _planned_profiles(state)

    profile_reports: list[dict[str, Any]] = []
    tool_calls = list(state.get("tool_calls", []))
    guardrail_events = list(state.get("guardrail_events", []))
    engine_events = list(state.get("engine_events", []))
    aggregate_subresults: list[dict[str, Any]] = []
    aggregate_citations: list[dict[str, Any]] = []
    per_domain: dict[str, Any] = {}
    prefixed_required_dimensions: list[str] = []
    prefixed_covered_dimensions: list[str] = []
    missing_dimensions: list[str] = []

    for profile in planned_profiles_in_order:
        bundle = reports_by_domain.get(profile.domain)
        if bundle is None:
            continue
        report = bundle["report"]
        profile_reports.append(report)
        tool_calls.extend(bundle.get("tool_calls", []))
        guardrail_events.extend(bundle.get("guardrail_events", []))
        for event in bundle.get("engine_events", []):
            engine_events = _append_event(
                engine_events,
                event.event_type,
                event.node_name,
                dict(event.payload),
            )
        per_domain[profile.domain] = report["coverage"]
        prefixed_required_dimensions.extend(
            f"{profile.domain}.{dimension}"
            for dimension in report["coverage"]["required_dimensions"]
        )
        prefixed_covered_dimensions.extend(
            f"{profile.domain}.{dimension}"
            for dimension in report["coverage"]["covered_dimensions"]
        )
        missing_dimensions.extend(
            f"{profile.domain}.{dimension}" for dimension in report["missing_dimensions"]
        )
        aggregate_subresults.extend(
            {
                **subresult,
                "dimension": f"{profile.domain}.{subresult['dimension']}",
            }
            for subresult in report["subresults"]
        )
        aggregate_citations.extend(report["citations"])

    overall_coverage_ratio = (
        1.0
        if not prefixed_required_dimensions
        else round(
            len(prefixed_covered_dimensions) / len(prefixed_required_dimensions),
            4,
        )
    )
    interrupt = (
        {
            "kind": "completeness_review",
            "reason": "mixed-domain policy answer does not cover all required dimensions",
            "missing_dimensions": missing_dimensions,
            "allowed_decisions": ["approve", "edit", "reject"],
        }
        if missing_dimensions
        else None
    )

    if interrupt is not None:
        guardrail_events.append(
            {
                "decision": "interrupt",
                "reason": interrupt["reason"],
                "missing_dimensions": missing_dimensions,
                "thread_id": state["thread_id"],
                "profile": "mixed",
            }
        )
        engine_events = _append_event(
            engine_events,
            EventType.PAUSE,
            "mixed_domain_completeness_validator",
            {
                "reason": interrupt["reason"],
                "missing_dimensions": missing_dimensions,
                "domains": [report["domain"] for report in profile_reports],
            },
        )

    return {
        "facts": {report["domain"]: report["facts"] for report in profile_reports},
        "required_dimensions": prefixed_required_dimensions,
        "subquestions": [],
        "subresults": aggregate_subresults,
        "citations": _merge_citations([{"citations": aggregate_citations}]),
        "coverage": {
            "required_dimensions": prefixed_required_dimensions,
            "covered_dimensions": prefixed_covered_dimensions,
            "coverage_ratio": overall_coverage_ratio,
            "per_domain": per_domain,
        },
        "missing_dimensions": missing_dimensions,
        "guardrail_events": guardrail_events,
        "engine_events": engine_events,
        "tool_calls": tool_calls,
        "interrupt": interrupt,
        "profile_reports": profile_reports,
    }


def _mixed_orchestrator_passthrough(state: PolicySupervisorState) -> PolicySupervisorState:
    """No-op node that owns the outgoing conditional edge to ``Send`` workers.

    LangGraph requires the fan-out router to live on a conditional edge
    OUT of a real node (the router itself is not a node). This node is
    intentionally empty — it exists only to give the router an anchor.
    """
    return {}


def _build_graph():
    settings = get_settings()
    parallel_mode = settings.agent_mixed_execution == "parallel"

    graph = StateGraph(PolicySupervisorState)
    graph.add_node("route_policy", _route_node)
    graph.add_node("extract_domain_facts", _profile_fact_node)
    graph.add_node("plan_domain_subquestions", _profile_plan_node)
    graph.add_node("execute_domain_subquestions", _profile_execute_node)
    graph.add_node("validate_domain_coverage", _profile_validate_node)
    if parallel_mode:
        graph.add_node("mixed_orchestrator", _mixed_orchestrator_passthrough)
        graph.add_node("mixed_profile_worker", _mixed_profile_worker_node)
        graph.add_node("mixed_reducer", _mixed_reducer_node)
    else:
        graph.add_node("mixed_execute_profiles", _mixed_execute_node)
    graph.add_node("generic_policy_search", _generic_search_node)
    graph.add_node("finalize", _finalize_supervisor_node)
    graph.add_edge(START, "route_policy")
    graph.add_conditional_edges(
        "route_policy",
        _route_after_policy,
        {
            "profiled": "extract_domain_facts",
            "mixed": "mixed_orchestrator" if parallel_mode else "mixed_execute_profiles",
            "generic": "generic_policy_search",
        },
    )
    graph.add_edge("extract_domain_facts", "plan_domain_subquestions")
    graph.add_edge("plan_domain_subquestions", "execute_domain_subquestions")
    graph.add_edge("execute_domain_subquestions", "validate_domain_coverage")
    graph.add_edge("validate_domain_coverage", "finalize")
    if parallel_mode:
        # Orchestrator fans out via Send → workers run in parallel →
        # LangGraph's barrier waits for all workers before running the
        # reducer (because reducer is the only outgoing edge target of
        # mixed_profile_worker, the Pregel runtime treats it as a join).
        graph.add_conditional_edges(
            "mixed_orchestrator",
            _mixed_fan_out_router,
            ["mixed_profile_worker"],
        )
        graph.add_edge("mixed_profile_worker", "mixed_reducer")
        graph.add_edge("mixed_reducer", "finalize")
    else:
        graph.add_edge("mixed_execute_profiles", "finalize")
    graph.add_edge("generic_policy_search", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


_POLICY_SUPERVISOR_GRAPH = _build_graph()


def _persist_thread_state(
    *,
    thread_id: str,
    run_id: str,
    tenant_id: str,
    customer_id: str,
    state: PolicySupervisorState,
) -> None:
    with scoped_session(tenant_id) as session:
        thread = session.get(AgentThread, thread_id)
        if thread is None:
            thread = AgentThread(
                id=thread_id,
                tenant_id=tenant_id,
                customer_id=customer_id,
                domain=str(state.get("policy_domain", "policy")),
                specialist=str(state.get("specialist", "generic_policy_agent")),
            )
            session.add(thread)
            session.flush()

        checkpoint = AgentThreadCheckpoint(
            id=str(uuid4()),
            thread_id=thread_id,
            agent_run_id=None,
            checkpoint_type="langgraph_state",
            status="paused" if state.get("interrupt") else "completed",
            state_json={
                "question": state["question"],
                "facts": dict(state.get("facts", {})),
                "coverage": dict(state.get("coverage", {})),
                "missing_dimensions": list(state.get("missing_dimensions", [])),
                "specialist_plan": list(state.get("specialist_plan", [])),
                "profile_reports": list(state.get("profile_reports", [])),
                "retrieval_trace": dict(
                    (state.get("final_result") or {}).get("retrieval_trace", {})
                ),
            },
            pending_interrupt_json=dict(state.get("interrupt") or {}),
        )
        session.add(checkpoint)
        session.flush()

        thread.domain = str(state.get("policy_domain", "policy"))
        thread.specialist = str(state.get("specialist", "generic_policy_agent"))
        thread.status = "awaiting_review" if state.get("interrupt") else "active"
        thread.pending_interrupt_json = dict(state.get("interrupt") or {})
        thread.latest_checkpoint_id = checkpoint.id
        thread.memory_summary_json = {
            "last_answer_preview": str((state.get("final_result") or {}).get("answer", ""))[:400],
            "last_coverage": dict(state.get("coverage", {})),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        try:
            answer = str((state.get("final_result") or {}).get("answer", "")).strip()
            if answer and not state.get("interrupt"):
                store = SqlSemanticMemoryStore(session)
                store.remember(
                    tenant_id=tenant_id,
                    user_id=customer_id,
                    content=answer,
                    key=f"policy:{state.get('policy_domain', 'generic')}",
                    metadata={
                        "thread_id": thread_id,
                        "specialist": state.get("specialist", "generic_policy_agent"),
                        "coverage_ratio": (state.get("coverage") or {}).get("coverage_ratio", 0.0),
                    },
                )
        except Exception:
            pass

        session.add(thread)
        session.commit()


def _result_to_execution(
    *,
    state: PolicySupervisorState,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    final = dict(state.get("final_result") or {})
    timeline = list(base_timeline)
    append_timeline_step(
        timeline,
        node_name="policy_supervisor",
        status="completed",
        detail=(
            f"域内路由命中 {state.get('policy_domain', 'generic')} / "
            f"{state.get('specialist', 'generic_policy_agent')}"
        ),
    )
    append_timeline_step(
        timeline,
        node_name="policy_guardrail",
        status="required" if state.get("interrupt") else "completed",
        detail=str((state.get("interrupt") or {}).get("reason", "policy workflow finished")),
    )
    return AgentExecutionResult(
        agent_name="policy_supervisor_agent",
        route_name=route_name,
        status="needs_review" if state.get("interrupt") else "completed",
        confidence=float(final.get("confidence", 0.0)),
        requires_human_review=bool(state.get("interrupt")),
        output=final,
        timeline=timeline,
        tool_calls=[
            ToolCallRecord(
                tool_name=call.get("tool_name", ""),
                status=call.get("status", ""),
                latency_ms=int(call.get("latency_ms", 0)),
                input_payload=dict(call.get("input_payload", {})),
                output_payload=dict(call.get("output_payload", {})),
            )
            for call in state.get("tool_calls", [])
        ],
        engine_events=list(state.get("engine_events", [])),
        interrupt=dict(state.get("interrupt") or {}) or None,
    )


def _result_to_execution_v2(
    *,
    state: PolicySupervisorState,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    final = dict(state.get("final_result") or {})
    timeline = list(base_timeline)
    route_detail = (
        f"policy route resolved to {state.get('policy_domain', 'generic')} / "
        f"{state.get('specialist', 'generic_policy_agent')}"
    )
    if state.get("specialist_plan"):
        route_detail += f" with plan {', '.join(state.get('specialist_plan', []))}"
    append_timeline_step(
        timeline,
        node_name="policy_supervisor",
        status="completed",
        detail=route_detail,
    )
    append_timeline_step(
        timeline,
        node_name="policy_guardrail",
        status="required" if state.get("interrupt") else "completed",
        detail=str((state.get("interrupt") or {}).get("reason", "policy workflow finished")),
    )
    return AgentExecutionResult(
        agent_name="policy_supervisor_agent",
        route_name=route_name,
        status="needs_review" if state.get("interrupt") else "completed",
        confidence=float(final.get("confidence", 0.0)),
        requires_human_review=bool(state.get("interrupt")),
        output=final,
        timeline=timeline,
        tool_calls=[
            ToolCallRecord(
                tool_name=call.get("tool_name", ""),
                status=call.get("status", ""),
                latency_ms=int(call.get("latency_ms", 0)),
                input_payload=dict(call.get("input_payload", {})),
                output_payload=dict(call.get("output_payload", {})),
            )
            for call in state.get("tool_calls", [])
        ],
        engine_events=list(state.get("engine_events", [])),
        interrupt=dict(state.get("interrupt") or {}) or None,
    )


def execute_policy_supervisor(
    *,
    question: str,
    tenant_id: str,
    customer_id: str,
    thread_id: str,
    run_id: str,
    user_id: str,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    prior_summary = _read_prior_thread_summary(thread_id, tenant_id)
    initial_state: PolicySupervisorState = {
        "question": question,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "thread_id": thread_id,
        "run_id": run_id,
        "user_id": user_id,
        "route_name": route_name,
        "prior_thread_summary": prior_summary,
        "facts": {},
        "required_dimensions": [],
        "subquestions": [],
        "subresults": [],
        "citations": [],
        "coverage": {},
        "missing_dimensions": [],
        "guardrail_events": [],
        "specialist_plan": [],
        "planned_domains": [],
        "profile_reports": [],
        "engine_events": [
            TimelineEvent(
                sequence=0,
                event_type=EventType.MEMORY_READ,
                node_name="policy_supervisor_bootstrap",
                payload={
                    "thread_id": thread_id,
                    "thread_exists": prior_summary.get("thread_exists", False),
                    "recent_run_count": len(prior_summary.get("recent_runs", [])),
                },
            )
        ],
        "tool_calls": [],
        "interrupt": None,
        "final_result": {},
    }
    try:
        state = _POLICY_SUPERVISOR_GRAPH.invoke(initial_state)
    except Exception:
        return execute_policy_graph(
            question=question,
            tenant_id=tenant_id,
            customer_id=customer_id,
            route_name=f"{route_name}:legacy_fallback",
            base_timeline=base_timeline,
        )

    _persist_thread_state(
        thread_id=thread_id,
        run_id=run_id,
        tenant_id=tenant_id,
        customer_id=customer_id,
        state=state,
    )
    return _result_to_execution_v2(state=state, route_name=route_name, base_timeline=base_timeline)


__all__ = ["execute_policy_supervisor"]
