"""Unit tests for context_precision / context_recall.

These two metrics close the most-cited gap between this repo's eval and
the RAGAS / TruLens line of frameworks: ``citation_hit_rate`` only tells
us *whether* the gold chunk was found, not how much of the surrounding
top-k was noise (precision) or how much of the expected fact set ever
made it into context (recall).

context_precision (RAGAS-aligned):
    For each retrieved chunk in rank order, mark it relevant or not.
    The metric weights *high-ranked* relevant chunks more, exactly
    like AP @ k:

        context_precision = ( Σ_{k=1..K} P@k · v_k ) / max(Σ v_k, 1)

    where v_k = 1 if rank-k chunk is relevant. Pure binary relevance
    so the math is unit-testable; the runner is free to feed in
    relevance marks from a keyword match or an LLM judge.

context_recall:
    Of the expected atomic facts the gold answer must mention, how many
    appear in the *union* of the retrieved chunks. Bounds quality from
    the other side: even a 100% precise top-3 is useless if the answer
    needs an atom that lives in chunk 4.

All inputs are simple lists of bools / strings — pure functions, no
DB or LLM calls. Compatible with the rest of ``retrieval_metrics.py``.
"""

from __future__ import annotations

import pytest

from app.services.eval.retrieval_metrics import (
    context_precision,
    context_recall,
)

# ---------- context_precision -----------------------------------------


def test_context_precision_all_relevant_returns_one() -> None:
    # Three chunks, all relevant → precision is 1 at every rank → mean 1.
    assert context_precision([True, True, True]) == pytest.approx(1.0)


def test_context_precision_no_relevant_returns_zero() -> None:
    assert context_precision([False, False, False]) == pytest.approx(0.0)


def test_context_precision_rewards_high_ranked_relevance() -> None:
    # Same number of relevant chunks (1) but at different ranks. AP
    # decays with rank, so [T, F, F] must score strictly higher than
    # [F, F, T].
    front = context_precision([True, False, False])
    back = context_precision([False, False, True])
    assert front > back
    assert front == pytest.approx(1.0)  # 1/1 / 1
    assert back == pytest.approx(1 / 3)  # (1/3) / 1


def test_context_precision_averages_over_relevant_ranks_only() -> None:
    # [T, F, T] → P@1=1, P@3=2/3, both relevant → (1 + 2/3)/2 = 5/6
    assert context_precision([True, False, True]) == pytest.approx(5 / 6)


def test_context_precision_empty_input_is_zero() -> None:
    assert context_precision([]) == pytest.approx(0.0)


def test_context_precision_at_k_truncates_input() -> None:
    # [T, F, T] but k=2 → only [T, F] is graded → P@1=1, only one
    # relevant → context_precision = 1.0
    assert context_precision([True, False, True], k=2) == pytest.approx(1.0)


def test_context_precision_at_k_zero_returns_zero() -> None:
    assert context_precision([True, True], k=0) == pytest.approx(0.0)


def test_context_precision_at_k_larger_than_input_is_fine() -> None:
    # k=10 with 3 items behaves like k=3 (no padding).
    assert context_precision([True, False, True], k=10) == pytest.approx(5 / 6)


# ---------- context_recall --------------------------------------------


def test_context_recall_all_atoms_present_returns_one() -> None:
    chunks = ["北京酒店上限 650 元/晚，含早。"]
    assert context_recall(chunks, ["北京", "650"]) == pytest.approx(1.0)


def test_context_recall_partial_coverage() -> None:
    chunks = ["上海酒店上限 550 元/晚。"]
    # "550" present, "Shanghai" not present in this Chinese chunk
    assert context_recall(chunks, ["Shanghai", "550"]) == pytest.approx(0.5)


def test_context_recall_union_across_chunks() -> None:
    # Each atom lives in a different chunk; the union covers all.
    chunks = [
        "L2 普通员工北京标准为 700 元",
        "周五入住周一离店需要补交公务证明",
    ]
    keywords = ["L2", "700", "周五入住周一离店", "公务"]
    assert context_recall(chunks, keywords) == pytest.approx(1.0)


def test_context_recall_no_keywords_returns_one_by_convention() -> None:
    # No expected atoms → vacuously recalled. Avoids division by zero
    # without forcing the caller to special-case this in aggregations.
    assert context_recall(["anything"], []) == pytest.approx(1.0)


def test_context_recall_empty_chunks_returns_zero() -> None:
    assert context_recall([], ["北京", "650"]) == pytest.approx(0.0)


def test_context_recall_is_case_insensitive_for_ascii() -> None:
    chunks = ["The Shanghai cap is 550 per night"]
    assert context_recall(chunks, ["shanghai", "550"]) == pytest.approx(1.0)


def test_context_recall_ignores_whitespace_around_keyword() -> None:
    # The chunk's whitespace shouldn't break a match for a keyword that
    # itself is a contiguous substring — protects against editors
    # adding a stray space inside expected_answer_keywords.
    chunks = ["报销 上限 是 650 元"]
    assert context_recall(chunks, ["650"]) == pytest.approx(1.0)
