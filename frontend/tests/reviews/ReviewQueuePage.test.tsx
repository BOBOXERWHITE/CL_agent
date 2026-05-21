import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import ReviewQueuePage from "../../src/pages/ReviewQueuePage";

vi.mock("../../src/api/reviews", () => ({
  listReviewCases: vi.fn().mockResolvedValue([
    {
      id: "review-case-1",
      source: "agent",
      tenant_id: "t1",
      customer_id: "c1",
      thread_id: "thread-1",
      status: "open",
      confidence: 0.38,
      reason: "超出酒店标准，进入人工复核。",
      suggested_action: "转人工复核",
      pending_interrupt: {
        kind: "human_review",
        reason: "ticket routing requires operator review",
        queue_name: "finance-review",
        allowed_decisions: ["approve", "edit", "reject"],
      },
      trace_events: [
        {
          category: "interrupt",
          name: "human_review",
          status: "paused",
          detail: "ticket routing requires operator review",
          timestamp: "2026-04-02T00:00:00Z",
          metadata: {
            queue_name: "finance-review",
          },
        },
        {
          category: "review",
          name: "review_case",
          status: "open",
          detail: "review case is waiting in queue",
          timestamp: "2026-04-02T00:00:00Z",
          metadata: {
            source: "agent",
          },
        },
      ],
      latest_checkpoint: {
        id: "checkpoint-1",
        checkpoint_type: "engine_adapter_state",
        status: "paused",
        created_at: "2026-04-02T00:00:00Z",
      },
      payload: {
        question: "这张北京酒店报销单为什么还在排队？",
      },
      rule_result: {
        decision: "blocked",
        reason: "超出酒店标准：当前金额 2200，阈值 1000。",
        suggested_action: "转人工复核",
        rule_hits: [
          {
            rule_code: "hotel_amount_tier_1",
            decision: "blocked",
            threshold_amount: 1000,
            actual_amount: 2200,
            reason: "超出酒店标准：当前金额 2200，阈值 1000。",
          },
        ],
      },
      created_at: "2026-04-02T00:00:00Z",
      updated_at: "2026-04-02T00:00:00Z",
    },
  ]),
}));

test("renders review interrupt and checkpoint summary", async () => {
  render(<ReviewQueuePage />);

  await screen.findByRole("heading", { name: "人工复核队列" });
  await screen.findByText("review-case-1");
  expect(screen.getByText("hotel_amount_tier_1")).toBeInTheDocument();
  expect(screen.getByText("ticket routing requires operator review")).toBeInTheDocument();
  expect(screen.getByText("finance-review")).toBeInTheDocument();
  expect(screen.getByText("engine_adapter_state")).toBeInTheDocument();
  expect(screen.getByText("Trace 事件")).toBeInTheDocument();
  expect(screen.getByText("human_review")).toBeInTheDocument();
  expect(screen.getByText("review_case")).toBeInTheDocument();
  expect(screen.getByText("转人工复核")).toBeInTheDocument();
});
