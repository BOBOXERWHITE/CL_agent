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

  fireEvent.click(screen.getByRole("button", { name: "运行评测" }));

  await waitFor(() => {
    expect(screen.getByText("3 个问题")).toBeInTheDocument();
  });

  expect(screen.getByText("评测运行")).toBeInTheDocument();
  expect(screen.getByText("答案正确率")).toBeInTheDocument();
  expect(screen.getByText("引用命中率")).toBeInTheDocument();
  expect(screen.getByText("低置信度占比")).toBeInTheDocument();
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
