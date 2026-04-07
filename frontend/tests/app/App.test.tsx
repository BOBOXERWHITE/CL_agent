import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import App from "../../src/app/App";

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
  listEvalRuns: vi.fn().mockResolvedValue([]),
  triggerEvalRun: vi.fn(),
}));

vi.mock("../../src/api/agents", () => ({
  listAgentRuns: vi.fn().mockResolvedValue([]),
  createAgentRun: vi.fn(),
}));

vi.mock("../../src/api/reviews", () => ({
  listReviewCases: vi.fn().mockResolvedValue([]),
}));

test("renders app shell title", async () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "差旅智能运营台" })).toBeInTheDocument();
  await screen.findByRole("heading", { name: "文档进入系统的第一站" });
  await screen.findByRole("heading", { name: "先看依据，再看结论" });
  await screen.findByRole("heading", { name: "Prompt 模板" });
  await screen.findByRole("heading", { name: "评测运行" });
  await screen.findByRole("heading", { name: "Agent 运行记录" });
  await screen.findByRole("heading", { name: "人工复核队列" });
});
