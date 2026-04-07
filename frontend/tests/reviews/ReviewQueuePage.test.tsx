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
      status: "open",
      confidence: 0.38,
      reason: "超出酒店标准：当前金额 2200，阈值 1000。",
      suggested_action: "转人工复核",
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

test("renders review cases and rule results", async () => {
  render(<ReviewQueuePage />);

  await screen.findByRole("heading", { name: "人工复核队列" });
  await screen.findByText("review-case-1");
  expect(screen.getByText("hotel_amount_tier_1")).toBeInTheDocument();
  expect(screen.getAllByText("转人工复核")[0]).toBeInTheDocument();
});
