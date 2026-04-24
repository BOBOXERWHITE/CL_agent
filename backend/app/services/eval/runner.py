from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.db.models.eval import EvalDataset, EvalRun
from app.db.session import bypass_rls_session, init_db
from app.services.rag.query_engine import answer_policy_question
from app.services.system_settings import get_runtime_settings


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _normalize_text(value: str) -> str:
    return "".join(value.lower().split())


def _matches_expected_answer(
    answer: str, sample: dict[str, object], citation_matched: bool
) -> bool:
    expected_keywords = [
        str(item).strip()
        for item in sample.get("expected_answer_keywords", [])
        if str(item).strip()
    ]
    if not expected_keywords:
        return citation_matched

    normalized_answer = _normalize_text(answer)
    return all(_normalize_text(keyword) in normalized_answer for keyword in expected_keywords)


def _expected_citation_rank(expected_citation: str, citations: list[object]) -> int | None:
    for index, citation in enumerate(citations, start=1):
        snippet = getattr(citation, "snippet", "")
        if expected_citation in snippet:
            return index
    return None


def _build_quality_gate(
    *,
    answer_correctness: float,
    citation_hit_rate: float,
    retrieval_mrr: float,
    low_confidence_rate: float,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if answer_correctness < 0.8:
        reasons.append("答案正确率低于 80%")
    if citation_hit_rate < 0.85:
        reasons.append("引用命中率低于 85%")
    if retrieval_mrr < 0.7:
        reasons.append("检索排序质量低于 MRR 0.7")
    if low_confidence_rate > 0.2:
        reasons.append("低置信度占比高于 20%")

    if not reasons:
        return "pass", []

    if (
        answer_correctness >= 0.6
        and citation_hit_rate >= 0.7
        and retrieval_mrr >= 0.55
        and low_confidence_rate <= 0.35
    ):
        return "warn", reasons

    return "fail", reasons


def _build_eval_detail(
    sample: dict[str, object],
    result,
    *,
    citation_matched: bool,
    answer_matched: bool,
    expected_citation_rank: int | None,
) -> dict[str, object]:
    return {
        "question": str(sample["question"]),
        "answer": result.answer,
        "expected_citation": str(sample["expected_citation"]),
        "expected_answer_keywords": [
            str(item) for item in sample.get("expected_answer_keywords", []) if str(item).strip()
        ],
        "confidence": round(float(result.confidence), 4),
        "citation_hit": citation_matched,
        "answer_correct": answer_matched,
        "answer_pass": answer_matched and citation_matched and result.confidence >= 0.6,
        "expected_citation_rank": expected_citation_rank,
        "low_confidence": result.confidence < 0.6,
        "citations": [citation.snippet for citation in result.citations],
    }


def run_eval(eval_dataset_id: str) -> EvalRun:
    init_db()
    runtime_settings = get_runtime_settings()
    with bypass_rls_session() as session:
        dataset = session.execute(
            select(EvalDataset).where(EvalDataset.id == eval_dataset_id)
        ).scalar_one()

        samples = list(dataset.samples_json)
        answer_correct_hits = 0
        citation_hits = 0
        retrieval_rank_sum = 0.0
        low_confidence_hits = 0
        answer_pass_hits = 0
        details: list[dict[str, object]] = []

        for sample in samples:
            result = answer_policy_question(
                question=str(sample["question"]),
                tenant_id=str(sample["tenant_id"]),
                customer_id=str(sample["customer_id"]),
            )

            expected_citation = str(sample["expected_citation"])
            citation_rank = _expected_citation_rank(expected_citation, result.citations)
            citation_matched = citation_rank is not None
            if citation_matched:
                citation_hits += 1
                retrieval_rank_sum += 1.0 / citation_rank
            answer_matched = _matches_expected_answer(result.answer, sample, citation_matched)
            if answer_matched:
                answer_correct_hits += 1
            low_confidence = result.confidence < 0.6
            if low_confidence:
                low_confidence_hits += 1
            answer_pass = answer_matched and citation_matched and not low_confidence
            if answer_pass:
                answer_pass_hits += 1
            details.append(
                _build_eval_detail(
                    sample,
                    result,
                    citation_matched=citation_matched,
                    answer_matched=answer_matched,
                    expected_citation_rank=citation_rank,
                )
            )

        answer_correctness = _safe_ratio(answer_correct_hits, len(samples))
        citation_hit_rate = _safe_ratio(citation_hits, len(samples))
        retrieval_mrr = round(retrieval_rank_sum / len(samples), 4) if samples else 0.0
        low_confidence_rate = _safe_ratio(low_confidence_hits, len(samples))
        answer_pass_rate = _safe_ratio(answer_pass_hits, len(samples))
        quality_gate, quality_gate_reasons = _build_quality_gate(
            answer_correctness=answer_correctness,
            citation_hit_rate=citation_hit_rate,
            retrieval_mrr=retrieval_mrr,
            low_confidence_rate=low_confidence_rate,
        )
        eval_run = EvalRun(
            id=str(uuid4()),
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            status="completed",
            question_count=len(samples),
            metrics_json={
                "answer_correctness": answer_correctness,
                "answer_recall": answer_correctness,
                "citation_hit_rate": citation_hit_rate,
                "retrieval_hit_rate": citation_hit_rate,
                "retrieval_mrr": retrieval_mrr,
                "low_confidence_rate": low_confidence_rate,
                "answer_pass_rate": answer_pass_rate,
                "quality_gate": quality_gate,
                "quality_gate_reasons": quality_gate_reasons,
                "provider_snapshot": {
                    "llm_provider": runtime_settings.llm_provider,
                    "llm_model_name": runtime_settings.llm_model_name,
                    "embedding_provider": runtime_settings.embedding_provider,
                    "embedding_model_name": runtime_settings.embedding_model_name,
                    "vector_store_provider": runtime_settings.vector_store_provider,
                },
                "details": details,
            },
        )
        session.add(eval_run)
        session.commit()
        session.refresh(eval_run)
        return eval_run
