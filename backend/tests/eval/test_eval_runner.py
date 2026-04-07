from types import SimpleNamespace
from uuid import uuid4

from app.db.models.eval import EvalDataset
from app.db.session import SessionLocal, init_db
from app.services.eval.dataset_loader import ensure_builtin_eval_dataset
from app.services.eval.runner import run_eval


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
    assert result.metrics["low_confidence_rate"] == 0.5
    assert result.details[0]["answer_correct"] is True
    assert result.details[1]["citation_hit"] is True
    assert result.details[1]["low_confidence"] is True
