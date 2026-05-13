import { postJson, requestJson } from "./client";

export interface EvalProviderSnapshot {
  llm_provider: string;
  llm_model_name: string;
  embedding_provider: string;
  embedding_model_name: string;
  vector_store_provider: string;
}

// P3: cross-run regression diff. One entry per tracked metric.
export interface RegressionDelta {
  name: string;
  current: number;
  previous: number;
  delta: number;
  // "higher_is_better" | "lower_is_better" | "informational"
  direction: string;
  regressed: boolean;
  threshold: number;
}

export interface RegressionDiff {
  has_previous: boolean;
  previous_run_id: string | null;
  // "pass" | "warn" | "fail"
  regression_gate: string;
  regression_reasons: string[];
  deltas: RegressionDelta[];
}

export interface EvalRunMetrics {
  // P0 baseline
  answer_correctness?: number;
  answer_recall?: number;
  citation_hit_rate: number;
  retrieval_hit_rate?: number;
  retrieval_mrr?: number;
  low_confidence_rate: number;
  answer_pass_rate?: number;
  quality_gate?: string | null;
  quality_gate_reasons?: string[];
  provider_snapshot?: EvalProviderSnapshot | null;
  // P0: LLM-as-judge dataset-level metrics
  judge_answer_correctness?: number;
  faithfulness?: number;
  judge_fallback_rate?: number;
  // P1: RAGAS-aligned context quality metrics
  context_precision?: number;
  context_recall?: number;
  // P2: judge-only token + cost totals
  judge_prompt_tokens_total?: number;
  judge_completion_tokens_total?: number;
  judge_cost_usd_total?: number;
  // P3: cross-run regression diff (null on legacy rows)
  regression?: RegressionDiff | null;
}

export interface EvalRunDetail {
  question: string;
  answer: string;
  expected_citation: string;
  expected_answer_keywords: string[];
  confidence: number;
  citation_hit: boolean;
  answer_correct: boolean;
  answer_pass?: boolean;
  expected_citation_rank?: number | null;
  low_confidence: boolean;
  citations: string[];
  // P0: per-sample LLM-as-judge breakdown
  judge_answer_correct?: boolean;
  judge_faithfulness?: number;
  judge_reasoning?: string;
  judge_fallback_used?: boolean;
  // P1: per-sample context quality
  context_precision?: number;
  context_recall?: number;
  // P2: per-sample judge cost
  judge_prompt_tokens?: number;
  judge_completion_tokens?: number;
  judge_cost_usd?: number;
}

export interface EvalRun {
  id: string;
  dataset_name: string;
  status: string;
  question_count: number;
  metrics: EvalRunMetrics;
  details: EvalRunDetail[];
  created_at: string;
  updated_at: string;
}

interface EvalRunListResponse {
  items: EvalRun[];
}

interface TriggerEvalRunInput {
  datasetName?: string;
}

export async function listEvalRuns(): Promise<EvalRun[]> {
  const response = await requestJson<EvalRunListResponse>("/api/evals/runs");
  return response.items;
}

export async function triggerEvalRun(input?: TriggerEvalRunInput): Promise<EvalRun> {
  return postJson<EvalRun>("/api/evals/runs", {
    dataset_name: input?.datasetName ?? "zh-policy-smoke",
  });
}
