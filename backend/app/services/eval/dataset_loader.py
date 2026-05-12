"""Eval dataset loading.

The legacy ``BUILTIN_DATASETS`` Python dict has been replaced by JSONL
files under ``backend/data/eval/``. The in-code registry below maps
each dataset name to its description (shown in the UI) and its on-disk
JSONL path. Samples themselves live in the JSONL files so non-engineers
can edit / version / review them in PRs without touching code.

Public API kept stable:
    - ``ensure_builtin_eval_dataset(session, dataset_name)`` — same
      signature, same return type, same ``LookupError`` on unknown name.
    - ``list_eval_datasets(session)`` — unchanged.

New helpers:
    - ``load_jsonl_samples(path)`` — generic loader; raises on bad JSON.
    - ``BUILTIN_DATASET_REGISTRY`` — name → ``DatasetSpec``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.eval import EvalDataset

# backend/app/services/eval/dataset_loader.py  →  backend/data/eval/
_EVAL_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "eval"


@dataclass(frozen=True)
class DatasetSpec:
    """In-code metadata for one builtin dataset.

    ``description`` shows up in the eval panel UI. ``path`` points at the
    JSONL file holding the actual samples. Splitting metadata (in code,
    versioned with the loader) from samples (in JSONL, editable without
    touching code) gives ops people a clean surface to add / tweak cases
    without needing a Python developer.
    """

    description: str
    path: Path


BUILTIN_DATASET_REGISTRY: dict[str, DatasetSpec] = {
    "zh-policy-smoke": DatasetSpec(
        description="中文与中英混合差旅政策问答冒烟评测集",
        path=_EVAL_DATA_DIR / "zh-policy-smoke.jsonl",
    ),
    "zh-policy-mixed-domain": DatasetSpec(
        description="酒店 / 机票 / 报销混合政策问题最小回归集",
        path=_EVAL_DATA_DIR / "zh-policy-mixed-domain.jsonl",
    ),
    # First 5 samples are the *atomic hops* the composed multi-hop
    # question on sample #6 must answer. Splitting them this way lets
    # the eval pinpoint which hop fails (room-rate table, breakfast
    # deduction, weekend-stay rule, invoice tax, over-budget tier)
    # instead of just reporting "the multi-hop case failed".
    "zh-policy-hotel-multihop": DatasetSpec(
        description="酒店知识库多跳问答评测集：5 个原子 hop + 1 个组合多跳问题",
        path=_EVAL_DATA_DIR / "zh-policy-hotel-multihop.jsonl",
    ),
    # P1 expansion (2026-05): 50+ atomic questions across 7 hotel-ops
    # domains — rate plans, cancellation, no-show, overbooking, China
    # invoicing tax, reimbursement compliance, loyalty programs, and
    # the consolidated decision tables. Big enough that A/B comparisons
    # between retrieval / model configurations are statistically
    # meaningful instead of noise.
    "zh-policy-hotel-full": DatasetSpec(
        description="酒店运营完整评测集：50+ 道原子题，覆盖房价/取消/超售/发票/差标/会员/决策表",
        path=_EVAL_DATA_DIR / "zh-policy-hotel-full.jsonl",
    ),
}


def load_jsonl_samples(path: Path) -> list[dict[str, object]]:
    """Read a JSONL file into a list of dicts.

    - Blank / whitespace-only lines are skipped.
    - Malformed JSON raises ``ValueError`` mentioning the line number so
      the editor can jump right to the broken record.
    - Missing file raises ``FileNotFoundError`` (caller decides what to do).
    """
    if not path.exists():
        raise FileNotFoundError(path)
    samples: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSON on line {line_number} of {path}: {exc.msg}"
                ) from exc
            if not isinstance(obj, dict):
                raise ValueError(f"line {line_number} of {path} did not decode to an object")
            samples.append(obj)
    return samples


def ensure_builtin_eval_dataset(session: Session, dataset_name: str) -> EvalDataset:
    """Look up or create a builtin dataset row in the database.

    On first call for a given ``dataset_name`` the JSONL is read into
    memory, persisted to ``EvalDataset``, and returned. Subsequent calls
    short-circuit on the existing row — content edits in the JSONL after
    the first call do NOT propagate (intentional: persisted runs must
    point at a stable snapshot, otherwise historical metric comparisons
    become apples-to-oranges).
    """
    dataset = session.execute(
        select(EvalDataset).where(EvalDataset.name == dataset_name)
    ).scalar_one_or_none()
    if dataset is not None:
        return dataset

    spec = BUILTIN_DATASET_REGISTRY.get(dataset_name)
    if spec is None:
        raise LookupError(dataset_name)

    samples = load_jsonl_samples(spec.path)

    dataset = EvalDataset(
        id=str(uuid4()),
        name=dataset_name,
        description=spec.description,
        samples_json=samples,
    )
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return dataset


def list_eval_datasets(session: Session) -> list[EvalDataset]:
    rows = session.execute(select(EvalDataset).order_by(EvalDataset.name.asc())).scalars()
    return list(rows)
