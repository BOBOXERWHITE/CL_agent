"""Order-anomaly agent (P3.4).

Pre-Phase-3 this file returned a constant and ignored ``question``
entirely. The new version does an actual signal-based triage: it scans
the incoming question for anomaly categories and routes to a matching
review queue with a confidence that reflects how sure we are.

Why not ReAct here
------------------

Anomaly triage, unlike policy QA, is a classification problem, not a
retrieval problem. Firing up an LLM to classify short signal phrases
would be overkill; the keyword + regex matcher gives deterministic
results, is trivial to extend when ops adds a new anomaly category,
and (most importantly) is testable without an LLM fixture.

If and when the business wants richer diagnosis (e.g. "look up the
order, cross-check with rules engine, prepare a CS reply"), it's a
drop-in ReAct upgrade — the engine / tool runner from P3.1 / P3.5 is
already in the codebase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.agents.engine import (
    Graph,
    GraphRunResult,
    GraphState,
    NodeResult,
)
from app.services.agents.nodes import append_timeline_step
from app.services.agents.state import AgentExecutionResult, TimelineStep


@dataclass(frozen=True)
class _AnomalyCategory:
    """One anomaly kind with its detection signals and routing target."""

    code: str
    queue_name: str
    reason: str
    # Plain substrings (case-insensitive) that indicate the category.
    keywords: tuple[str, ...]
    # Compiled regexes for patterns (e.g. ticket id format). Optional.
    patterns: tuple[re.Pattern[str], ...] = ()
    # Base confidence when a single signal hits; further hits add
    # ``per_hit_boost`` up to ``max_confidence``.
    base_confidence: float = 0.6
    per_hit_boost: float = 0.1
    max_confidence: float = 0.92


_ANOMALY_CATEGORIES: tuple[_AnomalyCategory, ...] = (
    _AnomalyCategory(
        code="duplicate_booking",
        queue_name="ops-review",
        reason="疑似重复预订，需运营人工核查订单并联系客户。",
        keywords=("重复预订", "重复下单", "duplicate booking", "double book"),
    ),
    _AnomalyCategory(
        code="refund_dispute",
        queue_name="cs-escalation",
        reason="检测到退款争议语义，需客服升级处理。",
        keywords=("退款", "争议", "refund", "chargeback"),
        base_confidence=0.65,
    ),
    _AnomalyCategory(
        code="suspected_fraud",
        queue_name="risk-review",
        reason="检测到疑似欺诈信号，需风控核查。",
        keywords=("欺诈", "异常支付", "盗刷", "fraud", "suspected fraud"),
        base_confidence=0.7,
        max_confidence=0.95,
    ),
    _AnomalyCategory(
        code="generic_anomaly",
        queue_name="ops-review",
        reason="异常订单类问题默认进入运营人工复核。",
        keywords=("异常订单", "order anomaly"),
        base_confidence=0.55,
    ),
)


@dataclass(frozen=True)
class _Match:
    category: _AnomalyCategory
    hit_count: int

    @property
    def confidence(self) -> float:
        boosted = self.category.base_confidence + (self.hit_count - 1) * self.category.per_hit_boost
        return round(min(boosted, self.category.max_confidence), 4)


def _detect(question: str) -> _Match | None:
    """Scan ``question`` for signals; return the best-fit category."""
    normalised = question.lower()
    best: _Match | None = None
    for category in _ANOMALY_CATEGORIES:
        hits = 0
        for keyword in category.keywords:
            if keyword.lower() in normalised:
                hits += 1
        for pattern in category.patterns:
            if pattern.search(question):
                hits += 1
        if hits == 0:
            continue
        candidate = _Match(category=category, hit_count=hits)
        # Prefer higher hit count, then higher base confidence.
        if best is None:
            best = candidate
            continue
        if candidate.hit_count > best.hit_count or (
            candidate.hit_count == best.hit_count
            and candidate.category.base_confidence > best.category.base_confidence
        ):
            best = candidate
    return best


def _default_output_for_no_match() -> dict[str, Any]:
    """Fallback payload when no signal matched; keep the queue generic."""
    return {
        "code": "unknown",
        "queue_name": "ops-review",
        "reason": "未识别到具体异常类别，默认转运营人工复核以便进一步调查。",
        "matched_signals": [],
    }


# ---------------------------------------------------------------------------
# Engine-driven nodes (P5.3)
# ---------------------------------------------------------------------------


def _classify_node(state: GraphState) -> NodeResult:
    """Run the keyword / regex matcher; write result into scratchpad.

    No tool calls, no IO — deterministic classification. Emitting it
    as its own node gives the engine a NODE_START / NODE_END pair that
    the ``agent_event`` table can persist (mirrors how policy_graph
    surfaces its ReAct steps).
    """
    question = str(state.scratchpad.get("question", ""))
    match = _detect(question)
    if match is None:
        classification: dict[str, Any] = {
            "matched": False,
            "confidence": 0.35,
            "output": _default_output_for_no_match(),
            "detail": "未命中任何异常类别关键词，降级默认处理。",
            "status": "fallback",
        }
    else:
        matched_keywords = [k for k in match.category.keywords if k.lower() in question.lower()]
        classification = {
            "matched": True,
            "confidence": match.confidence,
            "output": {
                "code": match.category.code,
                "queue_name": match.category.queue_name,
                "reason": match.category.reason,
                "matched_signals": matched_keywords,
            },
            "detail": (
                f"识别为 {match.category.code}，命中信号 {matched_keywords}，"
                f"路由至 {match.category.queue_name}。"
            ),
            "status": "completed",
        }
    return NodeResult(
        next_node="route",
        state_delta={"scratchpad": {"classification": classification}},
    )


def _route_node(state: GraphState) -> NodeResult:
    """Stamp the final decision + queue routing into scratchpad.

    Kept as its own node so the engine_event timeline clearly shows
    "classify finished → route decided"; reviewers looking at the
    timeline can tell exactly which step produced the queue_name.
    """
    classification = state.scratchpad.get("classification") or {}
    output = dict(classification.get("output") or {})
    confidence = float(classification.get("confidence", 0.35))
    final = {
        "output": output,
        "confidence": confidence,
        "classification_detail": classification.get("detail", ""),
        "classification_status": classification.get("status", ""),
        "queue_name": output.get("queue_name", "ops-review"),
    }
    return NodeResult(
        next_node=None,
        state_delta={"scratchpad": {"final": final}},
    )


def build_anomaly_graph() -> Graph:
    """Expose the graph factory for tests that want to drive the
    engine without the full ``execute_anomaly_graph`` adapter.
    """
    return Graph(
        nodes={
            "classify": _classify_node,
            "route": _route_node,
        },
        entry="classify",
    )


# ---------------------------------------------------------------------------
# Adapter: GraphRunResult → legacy AgentExecutionResult
# ---------------------------------------------------------------------------


def _run_result_to_execution(
    run_result: GraphRunResult,
    *,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    """Translate engine output back to the pre-P5.3 contract.

    Timeline entries remain the same three human-readable steps
    (triage + human review checkpoint + engine NODE_START markers) so
    existing frontend parsing keeps working. Structured events from
    the engine are handed off separately via ``engine_events``.
    """
    final = run_result.state.scratchpad.get("final") or {}
    output = dict(final.get("output") or {})
    confidence = float(final.get("confidence", 0.35))

    timeline = list(base_timeline)
    append_timeline_step(
        timeline,
        node_name="order_anomaly_triage",
        status=str(final.get("classification_status") or "completed"),
        detail=str(final.get("classification_detail") or ""),
    )
    queue_name = output.get("queue_name") or "ops-review"
    append_timeline_step(
        timeline,
        node_name="human_review_checkpoint",
        status="required",
        detail=f"异常订单需人工在 {queue_name} 队列复核。",
    )

    interrupt = {
        "kind": "human_review",
        "reason": "anomaly triage requires operator review",
        "queue_name": queue_name,
        "anomaly_code": output.get("code", "unknown"),
        "allowed_decisions": ["approve", "edit", "reject"],
    }

    return AgentExecutionResult(
        agent_name="order_anomaly_agent",
        route_name=route_name,
        status="needs_review",
        confidence=confidence,
        requires_human_review=True,
        output=output,
        timeline=timeline,
        tool_calls=[],
        engine_events=list(run_result.events),
        interrupt=interrupt,
        checkpoint_payload={
            "output": dict(output),
            "queue_name": queue_name,
            "anomaly_code": output.get("code", "unknown"),
            "review_interrupt": interrupt,
        },
        checkpoint_type="engine_adapter_state",
    )


def execute_anomaly_graph(
    *,
    question: str,
    route_name: str,
    base_timeline: list[TimelineStep],
) -> AgentExecutionResult:
    """Classify the question into an anomaly category + route to a queue.

    P5.3: now driven by the P3.1 engine internally so every run emits
    structured ``agent_event`` rows. Public signature unchanged.
    """
    initial_state = GraphState(
        tenant_id="",
        user_id="",
        request_id="",
        scratchpad={"question": question},
    )
    graph = build_anomaly_graph()
    run_result = graph.run(initial_state, max_steps=4)
    return _run_result_to_execution(
        run_result,
        route_name=route_name,
        base_timeline=base_timeline,
    )
