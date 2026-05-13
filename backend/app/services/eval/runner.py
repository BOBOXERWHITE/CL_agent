from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select

from app.db.models.eval import EvalDataset, EvalRun
from app.db.session import bypass_rls_session, init_db
from app.services.eval.llm_judge import JudgeVerdict, judge_answer
from app.services.eval.regression import compute_regression_diff
from app.services.eval.retrieval_metrics import context_precision, context_recall
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
    """Locate the rank of the expected citation in the retrieval result.

    Prefers ``full_content`` (the complete chunk text) so the rank check
    matches against the same evidence the LLM saw, not the 220-char UI
    preview. Falls back to ``snippet`` for older code paths / agents that
    only populate the preview field.
    """
    for index, citation in enumerate(citations, start=1):
        text = getattr(citation, "full_content", "") or getattr(citation, "snippet", "")
        if expected_citation in text:
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


def _per_chunk_relevance(
    citation_full_texts: list[str],
    expected_citation: str,
    expected_keywords: list[str],
) -> list[bool]:
    """Mark each retrieved chunk relevant or not, in rank order.

    A chunk is relevant if it contains the gold citation substring OR
    at least one expected keyword. Keyword OR-match keeps the metric
    informative when ``expected_citation`` is a short anchor phrase
    that only the first hit happens to include — the surrounding
    paragraphs are still useful context if they carry the supporting
    keywords. Empty inputs degenerate to "no chunk is relevant".
    """
    if not citation_full_texts:
        return []
    haystacks_lower = [text.lower() for text in citation_full_texts]
    citation_lower = expected_citation.lower().strip()
    keyword_terms = [kw.strip().lower() for kw in expected_keywords if kw.strip()]
    marks: list[bool] = []
    for text_lower in haystacks_lower:
        citation_hit = bool(citation_lower) and citation_lower in text_lower
        keyword_hit = any(kw in text_lower for kw in keyword_terms)
        marks.append(citation_hit or keyword_hit)
    return marks


def _build_eval_detail(
    sample: dict[str, object],
    result,
    *,
    citation_matched: bool,
    answer_matched: bool,
    expected_citation_rank: int | None,
    judge_verdict: JudgeVerdict,
    sample_context_precision: float,
    sample_context_recall: float,
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
        # P0: per-sample judge breakdown so the UI can show why a sample
        # passed or failed at the semantic level, not just keyword-AND.
        "judge_answer_correct": judge_verdict.answer_correct,
        "judge_faithfulness": round(judge_verdict.faithfulness, 4),
        "judge_reasoning": judge_verdict.reasoning,
        "judge_fallback_used": judge_verdict.fallback_used,
        # P2: per-sample judge cost — surfaces in the eval UI so ops can
        # see which expensive paraphrase the judge spent budget on.
        "judge_prompt_tokens": judge_verdict.prompt_tokens,
        "judge_completion_tokens": judge_verdict.completion_tokens,
        "judge_cost_usd": round(judge_verdict.cost_usd, 6),
        # P1: RAGAS-aligned context metrics, per-sample. Lets the UI
        # explain "retrieval found the right chunk but pulled 4 noise
        # chunks with it" (low precision) vs. "retrieval missed an
        # atom needed to answer" (low recall).
        "context_precision": round(sample_context_precision, 4),
        "context_recall": round(sample_context_recall, 4),
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
        # P0: LLM-as-judge aggregates. ``judge_correct_hits`` counts the
        # judge's semantic-correctness verdict (which can pass paraphrases
        # the keyword path misses). ``faithfulness_sum`` averages how
        # grounded each answer was in its citations.
        judge_correct_hits = 0
        faithfulness_sum = 0.0
        judge_fallback_count = 0
        # P1: per-sample context_precision / context_recall sums. The
        # mean across samples becomes the dataset-level RAGAS metric.
        context_precision_sum = 0.0
        context_recall_sum = 0.0
        # P2: judge token / cost aggregates. These only count tokens
        # spent by the LLM judge — answer-generation token usage is
        # tracked separately in chat history / request logs.
        judge_prompt_tokens_total = 0
        judge_completion_tokens_total = 0
        judge_cost_usd_total = 0.0
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

            # Ask the LLM judge for a semantic verdict. With the judge
            # disabled (default) this just rephrases ``answer_matched``
            # into a JudgeVerdict via the keyword fallback path — same
            # numbers, no extra LLM cost.
            expected_keywords = [
                str(item).strip()
                for item in sample.get("expected_answer_keywords", [])
                if str(item).strip()
            ]
            citation_full_texts = [
                getattr(c, "full_content", "") or getattr(c, "snippet", "")
                for c in result.citations
            ]
            judge_verdict = judge_answer(
                question=str(sample["question"]),
                answer=result.answer,
                expected_keywords=expected_keywords,
                expected_citation=expected_citation,
                citations=citation_full_texts,
                keyword_fallback_match=answer_matched,
            )
            if judge_verdict.answer_correct:
                judge_correct_hits += 1
            faithfulness_sum += judge_verdict.faithfulness
            if judge_verdict.fallback_used:
                judge_fallback_count += 1
            judge_prompt_tokens_total += judge_verdict.prompt_tokens
            judge_completion_tokens_total += judge_verdict.completion_tokens
            judge_cost_usd_total += judge_verdict.cost_usd

            # P1: RAGAS-aligned context metrics computed on the same
            # retrieved chunks the LLM saw. Relevance signal is the
            # gold citation substring OR any expected keyword — cheap,
            # no extra LLM cost, and distinguishes "right chunk found"
            # from "right chunk found alongside 3 noise chunks".
            relevance_marks = _per_chunk_relevance(
                citation_full_texts, expected_citation, expected_keywords
            )
            sample_context_precision = context_precision(relevance_marks)
            sample_context_recall = context_recall(citation_full_texts, expected_keywords)
            context_precision_sum += sample_context_precision
            context_recall_sum += sample_context_recall

            details.append(
                _build_eval_detail(
                    sample,
                    result,
                    citation_matched=citation_matched,
                    answer_matched=answer_matched,
                    expected_citation_rank=citation_rank,
                    judge_verdict=judge_verdict,
                    sample_context_precision=sample_context_precision,
                    sample_context_recall=sample_context_recall,
                )
            )

        answer_correctness = _safe_ratio(answer_correct_hits, len(samples))
        citation_hit_rate = _safe_ratio(citation_hits, len(samples))
        retrieval_mrr = round(retrieval_rank_sum / len(samples), 4) if samples else 0.0
        low_confidence_rate = _safe_ratio(low_confidence_hits, len(samples))
        answer_pass_rate = _safe_ratio(answer_pass_hits, len(samples))
        judge_answer_correctness = _safe_ratio(judge_correct_hits, len(samples))
        faithfulness = round(faithfulness_sum / len(samples), 4) if samples else 0.0
        judge_fallback_rate = _safe_ratio(judge_fallback_count, len(samples))
        mean_context_precision = round(context_precision_sum / len(samples), 4) if samples else 0.0
        mean_context_recall = round(context_recall_sum / len(samples), 4) if samples else 0.0
        quality_gate, quality_gate_reasons = _build_quality_gate(
            answer_correctness=answer_correctness,
            citation_hit_rate=citation_hit_rate,
            retrieval_mrr=retrieval_mrr,
            low_confidence_rate=low_confidence_rate,
        )

        # P3: cross-run regression diff. Find the most recent completed
        # run for this dataset (excluding the current one, which hasn't
        # been committed yet) and diff each headline metric. The result
        # populates a second-tier ``regression_gate`` that CI can use
        # to fail PRs that ship a worse system even when absolute
        # thresholds still pass.
        previous_run = session.execute(
            select(EvalRun)
            .where(EvalRun.dataset_name == dataset.name)
            .where(EvalRun.status == "completed")
            .order_by(EvalRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        current_metrics_for_diff = {
            "answer_correctness": answer_correctness,
            "citation_hit_rate": citation_hit_rate,
            "retrieval_mrr": retrieval_mrr,
            "low_confidence_rate": low_confidence_rate,
            "judge_answer_correctness": judge_answer_correctness,
            "faithfulness": faithfulness,
            "context_precision": mean_context_precision,
            "context_recall": mean_context_recall,
            "judge_cost_usd_total": round(judge_cost_usd_total, 6),
        }
        regression_diff = compute_regression_diff(
            current=current_metrics_for_diff,
            previous=previous_run.metrics_json if previous_run else None,
            previous_run_id=previous_run.id if previous_run else None,
        )
        regression_payload = {
            "has_previous": regression_diff.has_previous,
            "previous_run_id": regression_diff.previous_run_id,
            "regression_gate": regression_diff.regression_gate,
            "regression_reasons": list(regression_diff.regression_reasons),
            "deltas": [asdict(delta) for delta in regression_diff.deltas],
        }

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
                # P0: LLM-as-judge metrics, aligned with RAGAS naming.
                # ``judge_answer_correctness`` is the semantic-correctness
                # rate; ``faithfulness`` is the mean grounding score.
                # ``judge_fallback_rate`` lets consumers see how much of
                # the metric came from the LLM vs. the keyword fallback.
                "judge_answer_correctness": judge_answer_correctness,
                "faithfulness": faithfulness,
                "judge_fallback_rate": judge_fallback_rate,
                # P1: RAGAS-aligned dataset-level context quality.
                # context_precision = mean(weighted P@k where relevance =
                # gold substring or expected keyword in chunk). Tells you
                # how much of the retrieved top-k is signal vs. noise.
                # context_recall = mean(fraction of expected keywords
                # found in the union of retrieved chunks). Tells you
                # whether retrieval ever reached the atoms the answer
                # needs.
                "context_precision": mean_context_precision,
                "context_recall": mean_context_recall,
                # P2: judge-only token / cost totals. Lets ops decide
                # "is the judge worth the extra USD?" alongside the
                # judge_answer_correctness lift it produces. Per-sample
                # judge_prompt_tokens / judge_completion_tokens / judge_cost_usd
                # live in the per-detail row for drill-down.
                "judge_prompt_tokens_total": judge_prompt_tokens_total,
                "judge_completion_tokens_total": judge_completion_tokens_total,
                "judge_cost_usd_total": round(judge_cost_usd_total, 6),
                # P3: cross-run regression diff. Empty deltas + pass
                # on the first run for a given dataset; populated with
                # per-metric delta entries + a regression_gate on every
                # subsequent run.
                "regression": regression_payload,
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
