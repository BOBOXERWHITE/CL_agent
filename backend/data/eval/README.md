# Evaluation datasets

Each `*.jsonl` file is one eval dataset. One JSON object per line. Blank
lines are ignored. The loader (`backend/app/services/eval/dataset_loader.py`)
registers each file under a stable name plus a short description; the runner
(`backend/app/services/eval/runner.py`) reads the samples line by line.

## Sample schema

```json
{
  "question": "...",                        // required
  "tenant_id": "t1",                        // required
  "customer_id": "c1",                      // required
  "expected_citation": "substring of the gold chunk's full text",
  "expected_answer_keywords": ["k1", "k2"]   // grading: keyword AND-match (fallback)
}
```

When `EVAL_JUDGE_ENABLED=true` the runner additionally calls an LLM judge
to grade `answer_correct` and `faithfulness` semantically; the keywords
become the safety-net fallback for when the judge gateway is down.

## Adding a new dataset

1. Drop a new `*.jsonl` file in this directory.
2. Register it in `BUILTIN_DATASET_REGISTRY` in `dataset_loader.py` with a
   description (shown in the eval panel UI).
3. Add a smoke test under `backend/tests/eval/` that loads the dataset and
   asserts the sample count is what you intended — guards against a stray
   line break silently dropping a case.

## Why JSONL not YAML / CSV

- Stable line-by-line diffs in PR review (one sample = one diff line).
- No nested structure to wrestle with; round-trips through `json.loads`.
- Tools love it: `jq`, `wc -l`, every BI tool.
