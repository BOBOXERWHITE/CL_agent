import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import App from "../../src/app/App";
import * as chatApi from "../../src/api/chat";
import * as knowledgeApi from "../../src/api/knowledge";


vi.mock("../../src/api/knowledge", () => ({
  listKnowledgeJobs: vi.fn().mockResolvedValue([]),
  uploadKnowledgeDocument: vi.fn(),
}));

vi.mock("../../src/api/chat", () => ({
  askPolicyQuestion: vi.fn(),
}));


test("renders policy answer with citations and confidence", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([]);
  vi.mocked(chatApi.askPolicyQuestion).mockResolvedValue({
    session_id: "session-1",
    answer: "根据当前政策证据，国内差旅应优先预订 economy class。",
    confidence: 0.92,
    citations: [
      {
        chunk_id: "chunk-1",
        document_id: "doc-1",
        document_title: "差旅政策",
        snippet: "员工在国内差旅场景下应优先预订 economy class。",
        score: 0.92,
      },
    ],
  });

  render(<App />);

  fireEvent.change(screen.getByLabelText("政策问题"), {
    target: { value: "我可以预订 business class 吗？" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交问答" }));

  await waitFor(() => {
    expect(screen.getByText(/国内差旅应优先预订 economy class/i)).toBeInTheDocument();
  });

  expect(screen.getByText("置信度 92%")).toBeInTheDocument();
  expect(screen.getByText("差旅政策")).toBeInTheDocument();
  expect(
    screen.getByText("根据当前政策证据，国内差旅应优先预订 economy class。"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("员工在国内差旅场景下应优先预订 economy class。"),
  ).toBeInTheDocument();
  expect(screen.getByText("引用依据")).toBeInTheDocument();
});
