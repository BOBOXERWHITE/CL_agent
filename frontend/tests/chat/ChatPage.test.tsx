import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, vi } from "vitest";

import * as chatApi from "../../src/api/chat";
import ChatPage from "../../src/pages/ChatPage";

vi.mock("../../src/api/chat", () => ({
  askPolicyQuestion: vi.fn(),
}));

// Vitest does not reset mock call lists between tests in this project's
// config; without this hook a prior test's invocations bleed into
// ``mock.calls`` and break ordered assertions in the next test.
beforeEach(() => {
  vi.mocked(chatApi.askPolicyQuestion).mockReset();
});

test("submits tenant and customer ids with the policy question", async () => {
  vi.mocked(chatApi.askPolicyQuestion).mockResolvedValue({
    thread_id: "thread-1",
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
    expect(screen.getAllByText(/economy class/i).length).toBeGreaterThan(0);
  });

  expect(chatApi.askPolicyQuestion).toHaveBeenCalledWith({
    question: "我可以预订 business class 吗？",
    tenantId: "演示租户",
    customerId: "演示客户",
    threadId: undefined,
  });
  expect(screen.getByText("置信度 92%")).toBeInTheDocument();
  expect(screen.getByText("差旅政策")).toBeInTheDocument();
  expect(screen.getByText("引用依据")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看 Trace" })).toBeInTheDocument();
  expect(screen.getAllByText(/thread-1/i).length).toBeGreaterThan(0);
});

test("second turn carries the active thread id and renders both bubbles", async () => {
  vi.mocked(chatApi.askPolicyQuestion)
    .mockResolvedValueOnce({
      thread_id: "thread-multi",
      session_id: "thread-multi",
      answer: "L2 在 A 档城市是 700 元/晚。",
      confidence: 0.88,
      citations: [],
      retrieval_trace: null,
    })
    .mockResolvedValueOnce({
      thread_id: "thread-multi",
      session_id: "thread-multi",
      answer: "广州也属于 A 档，标准与北京一致。",
      confidence: 0.86,
      citations: [],
      retrieval_trace: null,
    });

  render(<ChatPage />);

  fireEvent.change(screen.getByLabelText("政策问题"), {
    target: { value: "北京 L2 住宿标准是多少？" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交问答" }));

  await waitFor(() => {
    expect(screen.getByText("L2 在 A 档城市是 700 元/晚。")).toBeInTheDocument();
  });

  fireEvent.change(screen.getByLabelText("政策问题"), {
    target: { value: "那广州呢？" },
  });
  // React 19 + RTL fireEvent: the controlled-input update doesn't always
  // flush before the next synchronous click in the same task. Confirm
  // the textarea state has settled to the new value before submitting,
  // otherwise the click handler closes over the previous question.
  await waitFor(() => {
    expect(screen.getByLabelText("政策问题")).toHaveValue("那广州呢？");
  });
  fireEvent.click(screen.getByRole("button", { name: "提交问答" }));

  await waitFor(() => {
    expect(screen.getByText("广州也属于 A 档，标准与北京一致。")).toBeInTheDocument();
  });

  // Both turns must remain visible — this is the core multi-turn UX promise.
  expect(screen.getByText("北京 L2 住宿标准是多少？")).toBeInTheDocument();
  expect(screen.getByText("L2 在 A 档城市是 700 元/晚。")).toBeInTheDocument();
  expect(screen.getByText("那广州呢？")).toBeInTheDocument();

  // Second call must reuse the thread_id from the first answer.
  const allCalls = vi.mocked(chatApi.askPolicyQuestion).mock.calls;
  // Surface the actual call sequence so a regression on closure capture
  // doesn't hide behind a generic "expected X to equal Y" message.
  expect(allCalls.map((c) => c[0]?.question)).toEqual([
    "北京 L2 住宿标准是多少？",
    "那广州呢？",
  ]);
  expect(allCalls[1]?.[0]?.threadId).toBe("thread-multi");
});

test("新建会话 clears the conversation and drops the thread id", async () => {
  vi.mocked(chatApi.askPolicyQuestion).mockResolvedValue({
    thread_id: "thread-cleanup",
    session_id: "thread-cleanup",
    answer: "first answer",
    confidence: 0.7,
    citations: [],
    retrieval_trace: null,
  });

  render(<ChatPage />);

  fireEvent.change(screen.getByLabelText("政策问题"), {
    target: { value: "first" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交问答" }));

  await waitFor(() => {
    expect(screen.getByText("first answer")).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: "新建会话" }));

  // Both bubbles disappear; thread id banner reverts to the empty state.
  expect(screen.queryByText("first")).not.toBeInTheDocument();
  expect(screen.queryByText("first answer")).not.toBeInTheDocument();
  expect(screen.getByText("尚未开启会话，提交后将自动建立 thread。")).toBeInTheDocument();
});
