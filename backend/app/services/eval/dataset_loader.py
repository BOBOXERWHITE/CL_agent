from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.eval import EvalDataset

BUILTIN_DATASETS: dict[str, dict[str, object]] = {
    "zh-policy-smoke": {
        "description": "中文与中英混合差旅政策问答冒烟评测集",
        "samples": [
            {
                "question": "北京酒店报销上限是多少？",
                "tenant_id": "t1",
                "customer_id": "c1",
                "expected_citation": "北京酒店报销上限",
                "expected_answer_keywords": ["北京", "650"],
            },
            {
                "question": "business class 可以直接预订吗？",
                "tenant_id": "t1",
                "customer_id": "c1",
                "expected_citation": "需要审批",
                "expected_answer_keywords": ["审批"],
            },
            {
                "question": "Shanghai hotel reimbursement cap 是多少？",
                "tenant_id": "t1",
                "customer_id": "c1",
                "expected_citation": "550",
                "expected_answer_keywords": ["Shanghai", "550"],
            },
        ],
    }
}


def ensure_builtin_eval_dataset(session: Session, dataset_name: str) -> EvalDataset:
    dataset = session.execute(
        select(EvalDataset).where(EvalDataset.name == dataset_name)
    ).scalar_one_or_none()
    if dataset is not None:
        return dataset

    spec = BUILTIN_DATASETS.get(dataset_name)
    if spec is None:
        raise LookupError(dataset_name)

    dataset = EvalDataset(
        id=str(uuid4()),
        name=dataset_name,
        description=str(spec["description"]),
        samples_json=list(spec["samples"]),
    )
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return dataset


def list_eval_datasets(session: Session) -> list[EvalDataset]:
    rows = session.execute(select(EvalDataset).order_by(EvalDataset.name.asc())).scalars()
    return list(rows)
