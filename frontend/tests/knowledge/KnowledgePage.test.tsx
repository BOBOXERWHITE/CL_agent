import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import App from "../../src/app/App";
import * as chatApi from "../../src/api/chat";
import * as knowledgeApi from "../../src/api/knowledge";
import * as promptsApi from "../../src/api/prompts";


vi.mock("../../src/api/knowledge", () => ({
  listKnowledgeJobs: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
}));

vi.mock("../../src/api/chat", () => ({
  askPolicyQuestion: vi.fn(),
}));

vi.mock("../../src/api/prompts", () => ({
  createPromptTemplate: vi.fn(),
  listPromptTemplates: vi.fn(),
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

test("uploads a document and renders the returned job", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValueOnce([]);
  vi.mocked(knowledgeApi.uploadKnowledgeDocument).mockResolvedValue({
    job_id: "job-1",
    document_id: "doc-1",
    status: "completed",
  });
  vi.mocked(chatApi.askPolicyQuestion).mockResolvedValue({
    session_id: "session-1",
    answer: "根据当前政策证据，国内出差应优先预订 economy class。",
    confidence: 0.92,
    citations: [],
  });
  vi.mocked(promptsApi.listPromptTemplates).mockResolvedValue([]);
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValueOnce([
    {
      job_id: "job-1",
      document_id: "doc-1",
      filename: "policy.docx",
      status: "completed",
      chunk_count: 2,
      tenant_id: "t1",
      customer_id: "c1",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ]);

  render(<App />);

  fireEvent.change(screen.getByLabelText("租户 ID"), {
    target: { value: "t1" },
  });
  fireEvent.change(screen.getByLabelText("客户 ID"), {
    target: { value: "c1" },
  });
  fireEvent.change(screen.getByLabelText("文档文件"), {
    target: {
      files: [
        new File(["policy"], "policy.docx", {
          type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }),
      ],
    },
  });

  fireEvent.click(screen.getByRole("button", { name: "开始入库" }));

  await waitFor(() => {
    expect(screen.getByText("policy.docx")).toBeInTheDocument();
  });
  expect(screen.getByText("job-1")).toBeInTheDocument();
  expect(screen.getByText("已完成")).toBeInTheDocument();
  expect(knowledgeApi.uploadKnowledgeDocument).toHaveBeenCalled();
});
