import { postJson, requestJson } from "./client";

export interface EvalRun {
  id: string;
  dataset_name: string;
  status: string;
  question_count: number;
  metrics: {
    answer_correctness?: number;
    answer_recall?: number;
    citation_hit_rate: number;
    low_confidence_rate: number;
  };
  details: {
    question: string;
    answer: string;
    expected_citation: string;
    expected_answer_keywords: string[];
    confidence: number;
    citation_hit: boolean;
    answer_correct: boolean;
    low_confidence: boolean;
    citations: string[];
  }[];
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
