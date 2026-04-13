import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import MonitoringPage from "../../src/pages/MonitoringPage";

vi.mock("../../src/api/monitoring", () => ({
  getMonitoringOverview: vi.fn().mockResolvedValue({
    knowledge_summary: {
      document_total: 12,
      completed_total: 10,
      failed_total: 1,
      pending_reindex_total: 3,
    },
    chat_summary: {
      session_total: 5,
      message_total: 18,
    },
    review_summary: {
      open_total: 2,
    },
    agent_summary: {
      last_24h_total: 4,
    },
    eval_summary: {
      last_24h_total: 1,
    },
    request_summary: {
      last_hour_total: 20,
      last_hour_error_total: 2,
      last_hour_p95_latency_ms: 82,
    },
    recent_activity: {
      recent_failed_requests: [
        {
          id: "log-1",
          request_id: "req-1",
          path: "/api/chat/ask",
          status_code: 500,
          created_at: "2026-04-08T09:00:00Z",
          error_message: "boom",
        },
      ],
      recent_eval_runs: [
        {
          id: "eval-1",
          dataset_name: "zh-policy-smoke",
          status: "completed",
          created_at: "2026-04-08T08:00:00Z",
        },
      ],
      recent_agent_runs: [
        {
          id: "agent-1",
          agent_name: "ticket_router_agent",
          status: "completed",
          created_at: "2026-04-08T07:00:00Z",
        },
      ],
    },
  }),
}));

test("renders monitoring summary cards and recent activity", async () => {
  render(<MonitoringPage />);

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "监控面板" })).toBeInTheDocument();
  });

  await waitFor(() => {
    expect(screen.getByText("知识库概览")).toBeInTheDocument();
  });
  expect(screen.getByText("待重建文档")).toBeInTheDocument();
  expect(screen.getByText("最近失败请求")).toBeInTheDocument();
  expect(screen.getByText("/api/chat/ask")).toBeInTheDocument();
  expect(screen.getByText("ticket_router_agent")).toBeInTheDocument();
});
