import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import AgentRunsPage from "../../src/pages/AgentRunsPage";


vi.mock("../../src/api/agents", () => ({
  listAgentRuns: vi.fn().mockResolvedValue([
    {
      id: "agent-run-1",
      agent_name: "ticket_router_agent",
      route_name: "ticket_triage",
      status: "completed",
      confidence: 0.86,
      requires_human_review: true,
      output: {
        queue_name: "finance-review",
        reason: "北京酒店费用超出酒店标准，需财务复核。",
      },
      timeline: [
        {
          node_name: "router",
          status: "completed",
          detail: "检测到工单语义。",
          timestamp: "2026-04-02T00:00:00Z",
        },
      ],
      tool_calls: [
        {
          tool_name: "ticket_queue_lookup",
          status: "completed",
          latency_ms: 3,
          input_payload: {
            ticket: {
              ticket_id: "ticket-001",
            },
          },
          output_payload: {
            queue_name: "finance-review",
          },
        },
      ],
      created_at: "2026-04-02T00:00:00Z",
      updated_at: "2026-04-02T00:00:00Z",
    },
  ]),
  createAgentRun: vi.fn(),
}));


test("renders agent run cards and timeline details", async () => {
  render(<AgentRunsPage />);

  await screen.findByRole("heading", { name: "Agent 运行记录" });
  await screen.findByText("ticket_router_agent");
  expect(screen.getByText("finance-review")).toBeInTheDocument();
  expect(screen.getByText("ticket_queue_lookup")).toBeInTheDocument();
});
