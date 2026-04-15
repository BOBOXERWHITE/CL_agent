import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    message: "当前使用本地 deterministic embedding，无需额外连通性检查。",
    endpoint: null,
  }),
  runKnowledgeEmbeddingSmokeTest: vi.fn().mockResolvedValue({
    provider: "deterministic",
    model_name: "deterministic-hash-embedding",
    configured: true,
    available: true,
    status: "ready",
    message: "Embedding 烟雾测试通过。",
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
      default_tenant_id: "演示租户",
      default_customer_id: "演示客户",
      chat_top_k: 3,
      chat_confidence_threshold: 0.2,
      default_eval_dataset: "zh-policy-smoke",
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

test("triggers eval run and renders metrics", async () => {
  const runs: Awaited<ReturnType<typeof evalsApi.listEvalRuns>> = [];
  const completedRun = {
    id: "eval-run-1",
    dataset_name: "zh-policy-smoke",
    status: "completed",
    question_count: 3,
    metrics: {
      answer_correctness: 1,
      citation_hit_rate: 1,
      low_confidence_rate: 0,
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
        question: "北京酒店报销上限是多少？",
        answer: "北京酒店报销上限为每晚 650 元。",
        expected_citation: "北京酒店报销上限",
        expected_answer_keywords: ["北京", "650"],
        confidence: 0.92,
        citation_hit: true,
        answer_correct: true,
        low_confidence: false,
        citations: ["北京酒店报销上限为每晚 650 元。"],
      },
      {
        question: "business class 可以直接预订吗？",
        answer: "可以直接预订。",
        expected_citation: "需要审批",
        expected_answer_keywords: ["审批"],
        confidence: 0.35,
        citation_hit: false,
        answer_correct: false,
        low_confidence: true,
        citations: [],
      },
    ],
    created_at: "2026-04-02T00:00:00Z",
    updated_at: "2026-04-02T00:00:00Z",
  };

  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([]);
  vi.mocked(chatApi.askPolicyQuestion).mockResolvedValue({
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

  await waitFor(() => {
    expect(screen.getByText("3 个问题")).toBeInTheDocument();
  });

  expect(screen.getByRole("heading", { name: "评测运行" })).toBeInTheDocument();
  expect(screen.getByText("答案正确率")).toBeInTheDocument();
  expect(screen.getByText("引用命中率")).toBeInTheDocument();
  expect(screen.getByText("低置信度占比")).toBeInTheDocument();
  expect(screen.getByText("本次评测配置")).toBeInTheDocument();
  expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0);
  expect(screen.getAllByText("text-embedding-3-small").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "查看明细" }));
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "仅看失败项" })).toBeInTheDocument();
  });
  expect(screen.getByText("失败原因汇总")).toBeInTheDocument();
  expect(screen.getByText("失败题数")).toBeInTheDocument();
  expect(screen.getAllByText("答案未命中").length).toBeGreaterThan(0);
  expect(screen.getAllByText("引用未命中").length).toBeGreaterThan(0);
  expect(screen.getAllByText("低置信度").length).toBeGreaterThan(0);
  expect(screen.getByText("无引用返回")).toBeInTheDocument();
  expect(screen.getByText("1 / 2 题")).toBeInTheDocument();
  expect(screen.getByText("北京酒店报销上限是多少？")).toBeInTheDocument();
  expect(screen.getByText("business class 可以直接预订吗？")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "仅看失败项" }));
  expect(screen.queryByText("北京酒店报销上限是多少？")).not.toBeInTheDocument();
  expect(screen.queryByText("北京酒店报销上限为每晚 650 元。")).not.toBeInTheDocument();
  expect(screen.getByText("business class 可以直接预订吗？")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "导出 CSV" })).toBeInTheDocument();
  expect(screen.getAllByText("100%").length).toBeGreaterThan(0);
});
