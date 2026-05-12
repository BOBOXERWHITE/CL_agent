"""Unit tests for JSONL-backed eval dataset loading.

The legacy ``BUILTIN_DATASETS`` Python dict has been moved out into
``backend/data/eval/{name}.jsonl`` so non-engineers can edit, version,
and review eval cases without touching code. The loader keeps a small
in-code registry of ``name -> (description, file path)`` for the UI
labels and discovery, but the question samples themselves live in JSONL.

Critical invariants under test:

1. **Each line is one sample.** Blank lines are tolerated; malformed
   JSON raises so we don't silently drop cases.
2. **Existing API stays the same.** ``ensure_builtin_eval_dataset`` is
   the only public entry point used by the route + the runner; its
   signature and DB write behaviour must not change.
3. **Unknown names raise LookupError.** Same error type as before so
   the FastAPI route maps it to the same HTTP 404.
4. **Loader supports an arbitrary on-disk path** for future custom
   uploads, not just the builtins.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from app.db.session import SessionLocal, init_db
from app.services.eval.dataset_loader import (
    BUILTIN_DATASET_REGISTRY,
    ensure_builtin_eval_dataset,
    load_jsonl_samples,
)


def _write_jsonl(path: Path, lines: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_jsonl_samples_reads_each_line_as_dict(tmp_path: Path) -> None:
    file_path = _write_jsonl(
        tmp_path / "tiny.jsonl",
        [
            {"question": "Q1", "expected_citation": "C1"},
            {"question": "Q2", "expected_citation": "C2"},
        ],
    )

    samples = load_jsonl_samples(file_path)

    assert len(samples) == 2
    assert samples[0]["question"] == "Q1"
    assert samples[1]["expected_citation"] == "C2"


def test_load_jsonl_samples_skips_blank_lines(tmp_path: Path) -> None:
    file_path = tmp_path / "padded.jsonl"
    file_path.write_text(
        textwrap.dedent(
            """
            {"question": "Q1"}

            {"question": "Q2"}
              \t
            {"question": "Q3"}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    samples = load_jsonl_samples(file_path)

    assert [s["question"] for s in samples] == ["Q1", "Q2", "Q3"]


def test_load_jsonl_samples_raises_on_invalid_json(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.jsonl"
    file_path.write_text(
        '{"question": "OK"}\n{this is not json}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        load_jsonl_samples(file_path)

    # Error must point at the offending line so an editor can fix it
    assert "line 2" in str(excinfo.value).lower() or "2" in str(excinfo.value)


def test_load_jsonl_samples_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_jsonl_samples(tmp_path / "absent.jsonl")


def test_builtin_registry_lists_three_datasets() -> None:
    assert "zh-policy-smoke" in BUILTIN_DATASET_REGISTRY
    assert "zh-policy-mixed-domain" in BUILTIN_DATASET_REGISTRY
    assert "zh-policy-hotel-multihop" in BUILTIN_DATASET_REGISTRY


def test_builtin_registry_entries_carry_description_and_path() -> None:
    for name, entry in BUILTIN_DATASET_REGISTRY.items():
        assert entry.description, f"{name} missing description"
        assert entry.path.exists(), f"{name} JSONL not found at {entry.path}"
        assert entry.path.suffix == ".jsonl"


def test_ensure_builtin_eval_dataset_loads_samples_from_jsonl() -> None:
    init_db()
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-smoke")

    assert dataset.name == "zh-policy-smoke"
    # 3 samples in zh-policy-smoke; new loader must produce the same count
    assert len(dataset.samples_json) == 3
    # Field shape preserved end-to-end (same keys the runner relies on)
    sample = dataset.samples_json[0]
    assert "question" in sample
    assert "expected_citation" in sample
    assert "expected_answer_keywords" in sample


def test_ensure_builtin_eval_dataset_unknown_name_raises_lookup_error() -> None:
    init_db()
    with SessionLocal() as session:
        with pytest.raises(LookupError):
            ensure_builtin_eval_dataset(session, dataset_name="does-not-exist")


def test_hotel_multihop_dataset_keeps_six_samples() -> None:
    init_db()
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-hotel-multihop")
    # 5 atomic hops + 1 composed → exactly 6
    assert len(dataset.samples_json) == 6


def test_mixed_domain_dataset_keeps_three_samples() -> None:
    init_db()
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-mixed-domain")
    assert len(dataset.samples_json) == 3


def test_hotel_full_dataset_has_at_least_50_samples() -> None:
    """The expanded P1 dataset is the one users should run for
    statistically meaningful A/B comparisons. Guard the line count so
    a stray missing newline can't silently drop us back under 50."""
    init_db()
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-hotel-full")
    assert len(dataset.samples_json) >= 50


def test_hotel_full_samples_carry_required_keys() -> None:
    """Every sample must carry the keys the runner reads. Missing
    ``tenant_id`` / ``customer_id`` would silently route the eval to
    the wrong RLS scope and produce a 0-citation run."""
    init_db()
    with SessionLocal() as session:
        dataset = ensure_builtin_eval_dataset(session, dataset_name="zh-policy-hotel-full")
    required = {"question", "tenant_id", "customer_id", "expected_citation"}
    for index, sample in enumerate(dataset.samples_json):
        missing = required - set(sample.keys())
        assert not missing, f"sample #{index} is missing required keys: {missing}"
        # expected_answer_keywords is optional but, when present, must be a list
        kws = sample.get("expected_answer_keywords")
        assert kws is None or isinstance(kws, list), (
            f"sample #{index} expected_answer_keywords must be a list, got {type(kws).__name__}"
        )
