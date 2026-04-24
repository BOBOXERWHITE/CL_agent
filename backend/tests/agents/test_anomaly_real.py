"""Tests for the P3.4 rewritten anomaly_graph.

Validates the actual classification behaviour: the agent reads the
question, surfaces the matched category, and routes to the correct
queue. Multi-signal cases raise confidence; no-signal cases fall back
to the generic ops-review queue with low confidence.
"""

from __future__ import annotations

from app.services.agents.anomaly_graph import execute_anomaly_graph


def _run(question: str):
    return execute_anomaly_graph(
        question=question,
        route_name="order_anomaly",
        base_timeline=[],
    )


def test_duplicate_booking_routes_to_ops_review() -> None:
    result = _run("用户反馈这是重复预订的情况，需要排查")
    assert result.output["code"] == "duplicate_booking"
    assert result.output["queue_name"] == "ops-review"
    assert "重复预订" in result.output["matched_signals"]
    assert result.confidence >= 0.6


def test_refund_dispute_routes_to_cs_escalation() -> None:
    result = _run("客户发起退款争议，要求 chargeback")
    assert result.output["code"] == "refund_dispute"
    assert result.output["queue_name"] == "cs-escalation"
    assert any(
        keyword in result.output["matched_signals"] for keyword in ("退款", "争议", "chargeback")
    )


def test_suspected_fraud_routes_to_risk_review_with_higher_confidence() -> None:
    result = _run("这笔疑似欺诈交易，存在盗刷风险")
    assert result.output["code"] == "suspected_fraud"
    assert result.output["queue_name"] == "risk-review"
    # Multi-signal (欺诈 + 盗刷) -> confidence should be boosted above base.
    assert result.confidence > 0.7


def test_multiple_hits_raise_confidence() -> None:
    one = _run("这是重复预订").confidence
    two = _run("这是重复预订和重复下单的情况，double book").confidence
    assert two > one


def test_english_keywords_also_trigger_classification() -> None:
    result = _run("This is a suspected fraud transaction")
    assert result.output["code"] == "suspected_fraud"


def test_no_signal_falls_back_to_generic_low_confidence() -> None:
    result = _run("今天天气不错")  # no anomaly signals at all
    assert result.output["code"] == "unknown"
    assert result.output["queue_name"] == "ops-review"
    assert result.output["matched_signals"] == []
    assert result.confidence < 0.5
    assert result.requires_human_review is True


def test_timeline_records_triage_decision() -> None:
    result = _run("异常订单重复预订")
    node_names = {step.node_name for step in result.timeline}
    assert "order_anomaly_triage" in node_names
    assert "human_review_checkpoint" in node_names


def test_base_timeline_is_preserved() -> None:
    from app.services.agents.state import TimelineStep

    base = [TimelineStep(node_name="router", status="completed", detail="routed")]
    result = execute_anomaly_graph(
        question="异常订单",
        route_name="order_anomaly",
        base_timeline=base,
    )
    assert result.timeline[0].node_name == "router"


def test_confidence_stops_at_max_even_with_many_hits() -> None:
    """Lots of signals → cap at category.max_confidence (0.95 for fraud)."""
    result = _run("欺诈 异常支付 盗刷 fraud suspected fraud")  # 5 fraud keywords
    assert result.confidence <= 0.95


def test_status_is_always_needs_review() -> None:
    """Every anomaly goes to human review regardless of confidence."""
    for q in ["重复预订", "退款争议", "欺诈", "天气"]:
        assert _run(q).status == "needs_review"
        assert _run(q).requires_human_review is True
