from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.db.models.eval import EvalDataset, EvalRun
from app.db.session import SessionLocal, init_db
from app.services.rag.query_engine import answer_policy_question


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _normalize_text(value: str) -> str:
    return "".join(value.lower().split())


def _matches_expected_answer(answer: str, sample: dict[str, object], citation_matched: bool) -> bool:
    expected_keywords = [
        str(item).strip()
        for item in sample.get("expected_answer_keywords", [])
        if str(item).strip()
    ]
    if not expected_keywords:
        return citation_matched

    normalized_answer = _normalize_text(answer)
    return all(_normalize_text(keyword) in normalized_answer for keyword in expected_keywords)


def _build_eval_detail(
    sample: dict[str, object],
    result,
    *,
    citation_matched: bool,
    answer_matched: bool,
) -> dict[str, object]:
    return {
        "question": str(sample["question"]),
        "answer": result.answer,
        "expected_citation": str(sample["expected_citation"]),
        "expected_answer_keywords": [
            str(item)
            for item in sample.get("expected_answer_keywords", [])
            if str(item).strip()
        ],
        "confidence": round(float(result.confidence), 4),
        "citation_hit": citation_matched,
        "answer_correct": answer_matched,
        "low_confidence": result.confidence < 0.6,
        "citations": [citation.snippet for citation in result.citations],
    }


def run_eval(eval_dataset_id: str) -> EvalRun:
    init_db()
    with SessionLocal() as session:
        dataset = session.execute(
            select(EvalDataset).where(EvalDataset.id == eval_dataset_id)
        ).scalar_one()

        samples = list(dataset.samples_json)
        answer_correct_hits = 0
        citation_hits = 0
        low_confidence_hits = 0
        details: list[dict[str, object]] = []

        for sample in samples:
            result = answer_policy_question(
                question=str(sample["question"]),
                tenant_id=str(sample["tenant_id"]),
                customer_id=str(sample["customer_id"]),
            )

            expected_citation = str(sample["expected_citation"])
            citation_matched = any(expected_citation in citation.snippet for citation in result.citations)
            if citation_matched:
                citation_hits += 1
            answer_matched = _matches_expected_answer(result.answer, sample, citation_matched)
            if answer_matched:
                answer_correct_hits += 1
            low_confidence = result.confidence < 0.6
            if low_confidence:
                low_confidence_hits += 1
            details.append(
                _build_eval_detail(
                    sample,
                    result,
                    citation_matched=citation_matched,
                    answer_matched=answer_matched,
                )
            )

        answer_correctness = _safe_ratio(answer_correct_hits, len(samples))
        eval_run = EvalRun(
            id=str(uuid4()),
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            status="completed",
            question_count=len(samples),
            metrics_json={
                "answer_correctness": answer_correctness,
                "answer_recall": answer_correctness,
                "citation_hit_rate": _safe_ratio(citation_hits, len(samples)),
                "low_confidence_rate": _safe_ratio(low_confidence_hits, len(samples)),
                "details": details,
            },
        )
        session.add(eval_run)
        session.commit()
        session.refresh(eval_run)
        return eval_run
