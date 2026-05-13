from types import SimpleNamespace
from uuid import uuid4

from app.db.models.eval import EvalDataset
from app.db.session import SessionLocal, init_db
from app.services.eval.dataset_loader import ensure_builtin_eval_dataset
from app.services.eval.runner import run_eval


def test_builtin_mixed_domain_dataset_can_be_created() -> None:
    init_db()
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-mixed-domain")

    assert dataset.name == "zh-policy-mixed-domain"
    assert len(dataset.samples_json) == 3
    assert any("business class" in str(sample["question"]) for sample in dataset.samples_json)


def test_eval_runner_persists_metrics(seeded_multilingual_policy_chunks: None) -> None:
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-smoke")
        dataset_id = dataset.id

    result = run_eval(eval_dataset_id=dataset_id)

    assert result.metrics["answer_correctness"] >= 0
    assert result.metrics["citation_hit_rate"] >= 0
    assert result.question_count >= 1
    assert len(result.details) == result.question_count

    with SessionLocal() as session:
        run_row = session.get(type(result), result.id)

    assert run_row is not None


def test_eval_runner_separates_answer_correctness_from_citation_hits(monkeypatch) -> None:
    init_db()
    dataset_id = str(uuid4())
    with SessionLocal() as session:
        session.add(
            EvalDataset(
                id=dataset_id,
                name="custom-answer-metrics",
                description="custom dataset for eval metric split",
                samples_json=[
                    {
                        "question": "北京酒店报销上限是多少？",
                        "tenant_id": "t1",
                        "customer_id": "c1",
                        "expected_citation": "北京酒店报销上限为每晚 650 元",
                        "expected_answer_keywords": ["北京", "650"],
                    },
                    {
                        "question": "business class 可以直接预订吗？",
                        "tenant_id": "t1",
                        "customer_id": "c1",
                        "expected_citation": "特殊情况需要审批",
                        "expected_answer_keywords": ["审批"],
                    },
                ],
            )
        )
        session.commit()

    fake_results = iter(
        [
            SimpleNamespace(
                answer="北京酒店报销上限为每晚 650 元。",
                confidence=0.91,
                citations=[
                    SimpleNamespace(snippet="其他相关证据"),
                    SimpleNamespace(snippet="北京酒店报销上限为每晚 650 元。"),
                ],
            ),
            SimpleNamespace(
                answer="可以直接预订。",
                confidence=0.35,
                citations=[
                    SimpleNamespace(snippet="特殊情况需要审批。"),
                ],
            ),
        ]
    )

    monkeypatch.setattr(
        "app.services.eval.runner.answer_policy_question",
        lambda question, tenant_id, customer_id: next(fake_results),
    )

    result = run_eval(eval_dataset_id=dataset_id)

    assert result.metrics["answer_correctness"] == 0.5
    assert result.metrics["citation_hit_rate"] == 1.0
    assert result.metrics["retrieval_hit_rate"] == 1.0
    assert result.metrics["retrieval_mrr"] == 0.75
    assert result.metrics["low_confidence_rate"] == 0.5
    assert result.metrics["answer_pass_rate"] == 0.5
    assert result.metrics["quality_gate"] == "fail"
    assert result.metrics["quality_gate_reasons"]
    assert result.details[0]["answer_correct"] is True
    assert result.details[0]["expected_citation_rank"] == 2
    assert result.details[1]["citation_hit"] is True
    assert result.details[1]["low_confidence"] is True


def test_first_run_has_no_regression_diff_but_subsequent_runs_do(monkeypatch) -> None:
    """End-to-end check for P3: the very first run on a dataset should
    have ``regression.has_previous=False``; a second run should diff
    against the first and surface ``previous_run_id`` plus per-metric
    deltas.

    We monkey-patch ``answer_policy_question`` so the test is
    deterministic across runs — the first run answers cleanly, the
    second deliberately answers worse so the diff has signal."""
    init_db()
    dataset_id = str(uuid4())
    with SessionLocal() as session:
        session.add(
            EvalDataset(
                id=dataset_id,
                name="regression-smoke-fixture",
                description="fixture for P3 regression diff test",
                samples_json=[
                    {
                        "question": "Q1",
                        "tenant_id": "t1",
                        "customer_id": "c1",
                        "expected_citation": "答案 A",
                        "expected_answer_keywords": ["A"],
                    },
                    {
                        "question": "Q2",
                        "tenant_id": "t1",
                        "customer_id": "c1",
                        "expected_citation": "答案 B",
                        "expected_answer_keywords": ["B"],
                    },
                ],
            )
        )
        session.commit()

    # Pass 1: both answers cite the gold chunk and confidence is high.
    pass1 = iter(
        [
            SimpleNamespace(
                answer="A",
                confidence=0.9,
                citations=[SimpleNamespace(snippet="答案 A", full_content="答案 A")],
            ),
            SimpleNamespace(
                answer="B",
                confidence=0.9,
                citations=[SimpleNamespace(snippet="答案 B", full_content="答案 B")],
            ),
        ]
    )
    monkeypatch.setattr(
        "app.services.eval.runner.answer_policy_question",
        lambda question, tenant_id, customer_id: next(pass1),
    )
    first = run_eval(eval_dataset_id=dataset_id)

    assert "regression" in first.metrics_json
    regression_1 = first.metrics_json["regression"]
    assert regression_1["has_previous"] is False
    assert regression_1["previous_run_id"] is None
    assert regression_1["deltas"] == []
    assert regression_1["regression_gate"] == "pass"

    # Pass 2: answers degrade — wrong keyword, no citation, low confidence.
    pass2 = iter(
        [
            SimpleNamespace(answer="wrong", confidence=0.2, citations=[]),
            SimpleNamespace(answer="wrong", confidence=0.2, citations=[]),
        ]
    )
    monkeypatch.setattr(
        "app.services.eval.runner.answer_policy_question",
        lambda question, tenant_id, customer_id: next(pass2),
    )
    second = run_eval(eval_dataset_id=dataset_id)

    regression_2 = second.metrics_json["regression"]
    assert regression_2["has_previous"] is True
    assert regression_2["previous_run_id"] == first.id
    assert regression_2["deltas"]  # populated
    # The first run had answer_correctness=1.0; second has 0.0 → must be flagged.
    correctness = next(d for d in regression_2["deltas"] if d["name"] == "answer_correctness")
    assert correctness["previous"] == 1.0
    assert correctness["current"] == 0.0
    assert correctness["regressed"] is True
    # Multiple metrics regressed (correctness, citation_hit_rate, retrieval_mrr,
    # judge_answer_correctness, faithfulness, context_precision, context_recall,
    # low_confidence_rate all moved in the wrong direction) — gate must fail.
    assert regression_2["regression_gate"] == "fail"
    assert regression_2["regression_reasons"]


def test_eval_runner_persists_provider_snapshot(seeded_multilingual_policy_chunks: None) -> None:
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-smoke")

    result = run_eval(eval_dataset_id=dataset.id)

    provider_snapshot = result.metrics.get("provider_snapshot")
    assert provider_snapshot is not None
    assert provider_snapshot["llm_provider"]
    assert provider_snapshot["embedding_provider"]
    assert provider_snapshot["vector_store_provider"]
