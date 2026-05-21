"""Baseline measurement for the hotel multi-hop eval set.

Runs ``zh-policy-hotel-multihop`` against the **real** ``docs/knowledge-base
/hotel`` corpus and prints per-sample diagnostics. The thresholds are
intentionally lax: this test exists to *measure* the current retrieval
floor, not to gate CI. A regression that drops MRR / citation hit-rate
below the floor is what we want to catch.
"""

from __future__ import annotations

from app.db.session import SessionLocal
from app.services.eval.dataset_loader import ensure_builtin_eval_dataset
from app.services.eval.runner import run_eval


def test_hotel_multihop_baseline(seeded_hotel_knowledge_base: None, capsys) -> None:
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-hotel-multihop")
        dataset_id = dataset.id

    result = run_eval(eval_dataset_id=dataset_id)

    metrics = result.metrics
    details = result.details
    assert len(details) == 6

    lines = [
        "",
        "=" * 72,
        "HOTEL MULTI-HOP BASELINE",
        "=" * 72,
        f"answer_correctness: {metrics['answer_correctness']}",
        f"citation_hit_rate:  {metrics['citation_hit_rate']}",
        f"retrieval_mrr:      {metrics['retrieval_mrr']}",
        f"low_confidence_rate:{metrics['low_confidence_rate']}",
        f"answer_pass_rate:   {metrics['answer_pass_rate']}",
        f"quality_gate:       {metrics['quality_gate']}",
        "-" * 72,
    ]
    for index, detail in enumerate(details, start=1):
        question = detail["question"][:60].replace("\n", " ")
        lines.append(
            f"#{index}  hit={detail['citation_hit']!s:5}  "
            f"correct={detail['answer_correct']!s:5}  "
            f"rank={detail['expected_citation_rank']}  "
            f"conf={detail['confidence']}  | {question}"
        )
    lines.append("=" * 72)
    print("\n".join(lines))
    # Force capsys to surface the print even when the test passes.
    captured = capsys.readouterr()
    print(captured.out)

    # Floor: at least one sample must produce *some* citation, otherwise
    # ingestion failed entirely and the run number is meaningless.
    any_citations = any(detail["citations"] for detail in details)
    assert any_citations, "no citations returned for any sample — ingestion likely failed"
