import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import App from "../../src/app/App";
import * as chatApi from "../../src/api/chat";
import * as evalsApi from "../../src/api/evals";
import * as knowledgeApi from "../../src/api/knowledge";
import * as promptsApi from "../../src/api/prompts";

vi.mock("../../src/api/knowledge", () => ({
  listKnowledgeJobs: vi.fn().mockResolvedValue([]),
  uploadKnowledgeDocument: vi.fn(),
  rebuildKnowledgeIndex: vi.fn(),
  deleteKnowledgeDocument: vi.fn(),
  checkKnowledgeEmbeddingReadiness: vi.fn().mockResolvedValue({
    provider: "deterministic",
    model_name: "deterministic-hash-embedding",
    configured: true,
    available: true,
    status: "ready",
    message: "deterministic embedding ready",
    endpoint: null,
  }),
  runKnowledgeEmbeddingSmokeTest: vi.fn().mockResolvedValue({
    provider: "deterministic",
    model_name: "deterministic-hash-embedding",
    configured: true,
    available: true,
    status: "ready",
    message: "embedding smoke test passed",
    endpoint: null,
    sample_text: "北京酒店报销上限",
    latency_ms: 12.5,
    vector_dimension: 16,
  }),
}));

vi.mock("../../src/api/chat", () => ({
  askPolicyQuestion: vi.fn(),
}));

vi.mock("../../src/api/prompts", () => ({
  createPromptTemplate: vi.fn(),
  listPromptTemplates: vi.fn().mockResolvedValue([]),
  activatePromptTemplate: vi.fn(),
}));

vi.mock("../../src/api/evals", () => ({
  listEvalRuns: vi.fn(),
  triggerEvalRun: vi.fn(),
}));

vi.mock("../../src/api/agents", () => ({
  listAgentRuns: vi.fn().mockResolvedValue([]),
  createAgentRun: vi.fn(),
}));

vi.mock("../../src/api/reviews", () => ({
  listReviewCases: vi.fn().mockResolvedValue([]),
}));

vi.mock("../../src/api/monitoring", () => ({
  getMonitoringOverview: vi.fn().mockResolvedValue({
    knowledge_summary: {
      document_total: 0,
      completed_total: 0,
      failed_total: 0,
      pending_reindex_total: 0,
    },
    chat_summary: {
      session_total: 0,
      message_total: 0,
    },
    review_summary: {
      open_total: 0,
    },
    agent_summary: {
      last_24h_total: 0,
    },
    eval_summary: {
      last_24h_total: 0,
    },
    request_summary: {
      last_hour_total: 0,
      last_hour_error_total: 0,
      last_hour_p95_latency_ms: 0,
    },
    recent_activity: {
      recent_failed_requests: [],
      recent_eval_runs: [],
      recent_agent_runs: [],
    },
  }),
}));

vi.mock("../../src/api/logs", () => ({
  listRuntimeLogs: vi.fn().mockResolvedValue([]),
  getRuntimeLogDetail: vi.fn(),
}));

vi.mock("../../src/api/settings", () => ({
  getSystemSettings: vi.fn().mockResolvedValue({
    editable_settings: {
      default_tenant_id: "demo-tenant",
      default_customer_id: "demo-customer",
      chat_top_k: 3,
      chat_confidence_threshold: 0.2,
      default_eval_dataset: "zh-policy-mixed-domain",
    },
    runtime_settings: {
      llm_provider: "deterministic",
      llm_model_name: "deterministic-policy-client",
      embedding_provider: "deterministic",
      embedding_model_name: "deterministic-hash-embedding",
      embedding_dimension: 16,
      vector_store_provider: "milvus",
      auth_enabled: false,
    },
  }),
  updateSystemSettings: vi.fn(),
}));

test("renders mixed-domain eval metrics and quality gate", async () => {
  const runs: Awaited<ReturnType<typeof evalsApi.listEvalRuns>> = [];
  const completedRun = {
    id: "eval-run-1",
    dataset_name: "zh-policy-mixed-domain",
    status: "completed",
    question_count: 3,
    metrics: {
      answer_correctness: 1,
      citation_hit_rate: 1,
      low_confidence_rate: 0,
      retrieval_mrr: 0.83,
      answer_pass_rate: 0.67,
      quality_gate: "warn",
      quality_gate_reasons: ["mixed-domain coverage below target"],
      provider_snapshot: {
        llm_provider: "openai-compatible",
        llm_model_name: "gpt-4o-mini",
        embedding_provider: "openai-compatible",
        embedding_model_name: "text-embedding-3-small",
        vector_store_provider: "milvus",
      },
    },
    details: [
      {
        question: "北京酒店 760 元含早，同时国内机票想订 business class，这张报销单是否合规？",
        answer: "酒店超标且机票需要审批。",
        expected_citation: "需要审批",
        expected_answer_keywords: ["审批"],
        confidence: 0.92,
        citation_hit: true,
        answer_correct: true,
        answer_pass: true,
        low_confidence: false,
        citations: ["需要审批"],
      },
    ],
    created_at: "2026-04-02T00:00:00Z",
    updated_at: "2026-04-02T00:00:00Z",
  };

  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([]);
  vi.mocked(chatApi.askPolicyQuestion).mockResolvedValue({
    thread_id: "thread-1",
    session_id: "session-1",
    answer: "根据证据回答。",
    confidence: 0.9,
    citations: [],
  });
  vi.mocked(promptsApi.listPromptTemplates).mockResolvedValue([]);
  vi.mocked(evalsApi.listEvalRuns).mockImplementation(async () => runs);
  vi.mocked(evalsApi.triggerEvalRun).mockImplementation(async () => {
    runs.splice(0, runs.length, completedRun);
    return completedRun;
  });

  render(<App />);

  fireEvent.click(screen.getByRole("tab", { name: "评测运行" }));
  fireEvent.click(screen.getByRole("button", { name: "运行评测" }));

  await screen.findByText("Retrieval MRR");
  expect(screen.getByText("Answer Pass Rate")).toBeInTheDocument();
  expect(screen.getByText("Quality Gate")).toBeInTheDocument();
  expect(screen.getByText("warn")).toBeInTheDocument();
  expect(screen.getByText("mixed-domain coverage below target")).toBeInTheDocument();
  expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0);
  expect(screen.getAllByText("text-embedding-3-small").length).toBeGreaterThan(0);
});

test("renders P0/P1/P2/P3 metric cards, judge cost and regression gate", async () => {
  // A 2nd-generation eval run carrying the full P0-P3 metric set.
  const runs: Awaited<ReturnType<typeof evalsApi.listEvalRuns>> = [];
  const completedRun = {
    id: "eval-run-2",
    dataset_name: "zh-policy-hotel-full",
    status: "completed",
    question_count: 2,
    metrics: {
      answer_correctness: 1,
      citation_hit_rate: 1,
      low_confidence_rate: 0,
      retrieval_mrr: 1,
      answer_pass_rate: 1,
      quality_gate: "pass",
      quality_gate_reasons: [],
      // P0 LLM-as-judge
      judge_answer_correctness: 0.95,
      faithfulness: 0.88,
      judge_fallback_rate: 0,
      // P1 RAGAS context
      context_precision: 0.82,
      context_recall: 0.9,
      // P2 token + cost
      judge_prompt_tokens_total: 1200,
      judge_completion_tokens_total: 240,
      judge_cost_usd_total: 0.0012,
      // P3 regression diff
      regression: {
        has_previous: true,
        previous_run_id: "eval-run-1",
        regression_gate: "warn",
        regression_reasons: [
          "context_precision: 0.9000 → 0.8200 (Δ -0.0800)",
        ],
        deltas: [
          {
            name: "judge_answer_correctness",
            current: 0.95,
            previous: 0.92,
            delta: 0.03,
            direction: "higher_is_better",
            regressed: false,
            threshold: 0.05,
          },
          {
            name: "context_precision",
            current: 0.82,
            previous: 0.9,
            delta: -0.08,
            direction: "higher_is_better",
            regressed: true,
            threshold: 0.05,
          },
          {
            name: "judge_cost_usd_total",
            current: 0.0012,
            previous: 0.001,
            delta: 0.0002,
            direction: "informational",
            regressed: false,
            threshold: 0,
          },
        ],
      },
      provider_snapshot: {
        llm_provider: "openai-compatible",
        llm_model_name: "deepseek-v3-2-251201",
        embedding_provider: "openai-compatible",
        embedding_model_name: "text-embedding-v4",
        vector_store_provider: "milvus",
      },
    },
    details: [
      {
        question: "L4 经理上海差标？",
        answer: "L4 上海标准是 1200 元/晚。",
        expected_citation: "L4 经理",
        expected_answer_keywords: ["L4", "1200"],
        confidence: 0.9,
        citation_hit: true,
        answer_correct: true,
        answer_pass: true,
        low_confidence: false,
        citations: ["L4 经理 上海 1200"],
        judge_answer_correct: true,
        judge_faithfulness: 0.95,
        judge_reasoning: "答案与引用的 1200 元/晚标准一致。",
        judge_fallback_used: false,
        context_precision: 1,
        context_recall: 1,
        judge_prompt_tokens: 600,
        judge_completion_tokens: 120,
        judge_cost_usd: 0.0006,
      },
    ],
    created_at: "2026-05-13T00:00:00Z",
    updated_at: "2026-05-13T00:00:00Z",
  };

  vi.mocked(evalsApi.listEvalRuns).mockImplementation(async () => runs);
  vi.mocked(evalsApi.triggerEvalRun).mockImplementation(async () => {
    runs.splice(0, runs.length, completedRun);
    return completedRun;
  });

  render(<App />);

  fireEvent.click(screen.getByRole("tab", { name: "评测运行" }));
  fireEvent.click(screen.getByRole("button", { name: "运行评测" }));

  // P0/P1 metric cards present in the top grid.
  await screen.findByText("LLM 判定正确率");
  expect(screen.getByText("Faithfulness")).toBeInTheDocument();
  expect(screen.getByText("Context Precision")).toBeInTheDocument();
  expect(screen.getByText("Context Recall")).toBeInTheDocument();

  // P2 judge cost section.
  expect(screen.getByText("LLM 裁判成本")).toBeInTheDocument();
  // $0.0012 appears twice (cost card + regression row); just ensure ≥1.
  expect(screen.getAllByText("$0.0012").length).toBeGreaterThan(0);
  expect(screen.getByText("1,200")).toBeInTheDocument(); // prompt tokens

  // P3 regression card.
  expect(screen.getByText("回归门禁")).toBeInTheDocument();
  expect(screen.getByText("存在轻微退化")).toBeInTheDocument();
  expect(screen.getByText("eval-run-1")).toBeInTheDocument();
  // The regressed row surfaces the metric name + its signed delta.
  expect(screen.getByText("context_precision")).toBeInTheDocument();
  expect(screen.getByText("-0.0800")).toBeInTheDocument();

  // Per-sample judge breakdown appears once the details are expanded.
  fireEvent.click(screen.getByRole("button", { name: "查看明细" }));
  expect(await screen.findByText("LLM 裁判判定")).toBeInTheDocument();
  expect(screen.getByText("Faithfulness 0.95")).toBeInTheDocument();
  expect(screen.getByText("答案与引用的 1200 元/晚标准一致。")).toBeInTheDocument();
});
