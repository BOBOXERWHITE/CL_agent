import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import * as chatApi from "../../src/api/chat";
import ChatPage from "../../src/pages/ChatPage";

vi.mock("../../src/api/chat", () => ({
  askPolicyQuestion: vi.fn(),
}));

test("submits tenant and customer ids with the policy question", async () => {
  vi.mocked(chatApi.askPolicyQuestion).mockResolvedValue({
    session_id: "session-1",
    answer: "根据当前政策证据，国内出差应优先预订 economy class。",
    confidence: 0.92,
    citations: [
      {
        chunk_id: "chunk-1",
        document_id: "doc-1",
        document_title: "差旅政策",
        snippet: "员工在国内出差场景下应优先预订 economy class。",
        score: 0.92,
      },
    ],
    retrieval_trace: {
      mode: "hybrid",
      prompt_name: "默认政策问答 Prompt",
      prompt_version: 1,
      model_name: "deterministic-policy-client",
      token_usage: {
        input_tokens: 12,
        output_tokens: 8,
      },
      selected_chunks: [
        {
          chunk_id: "chunk-1",
          document_id: "doc-1",
          document_title: "差旅政策",
          score: 0.92,
        },
      ],
    },
  });

  render(<ChatPage />);

  fireEvent.change(screen.getByLabelText("租户 ID"), {
    target: { value: "演示租户" },
  });
  fireEvent.change(screen.getByLabelText("客户 ID"), {
    target: { value: "演示客户" },
  });
  fireEvent.change(screen.getByLabelText("政策问题"), {
    target: { value: "我可以预订 business class 吗？" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交问答" }));

  await waitFor(() => {
    expect(screen.getByText(/国内出差应优先预订 economy class/i)).toBeInTheDocument();
  });

  expect(chatApi.askPolicyQuestion).toHaveBeenCalledWith({
    question: "我可以预订 business class 吗？",
    tenantId: "演示租户",
    customerId: "演示客户",
    sessionId: undefined,
  });
  expect(screen.getByText("置信度 92%")).toBeInTheDocument();
  expect(screen.getByText("差旅政策")).toBeInTheDocument();
  expect(screen.getByText("引用依据")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看检索 Trace" })).toBeInTheDocument();
});
