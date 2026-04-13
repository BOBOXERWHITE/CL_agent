import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import RuntimeLogsPage from "../../src/pages/RuntimeLogsPage";

vi.mock("../../src/api/logs", () => ({
  listRuntimeLogs: vi.fn().mockResolvedValue([
    {
      id: "log-1",
      request_id: "req-1",
      method: "POST",
      path: "/api/chat/ask",
      status_code: 500,
      latency_ms: 88,
      tenant_id: "演示租户",
      customer_id: "演示客户",
      session_id: "session-1",
      user_role: "operator",
      model_name: "deterministic-policy-client",
      token_usage_json: { input_tokens: 12, output_tokens: 18 },
      error_message: "boom",
      created_at: "2026-04-08T09:00:00Z",
    },
  ]),
  getRuntimeLogDetail: vi.fn().mockResolvedValue({
    id: "log-1",
    request_id: "req-1",
    method: "POST",
    path: "/api/chat/ask",
    status_code: 500,
    latency_ms: 88,
    tenant_id: "演示租户",
    customer_id: "演示客户",
    session_id: "session-1",
    user_role: "operator",
    model_name: "deterministic-policy-client",
    token_usage_json: { input_tokens: 12, output_tokens: 18 },
    error_message: "boom",
    created_at: "2026-04-08T09:00:00Z",
  }),
}));

test("filters runtime logs and opens detail view", async () => {
  render(<RuntimeLogsPage />);

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "运行日志" })).toBeInTheDocument();
  });

  expect(screen.getByText("/api/chat/ask")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("请求路径"), {
    target: { value: "/api/chat/ask" },
  });
  fireEvent.change(screen.getByLabelText("开始时间"), {
    target: { value: "2026-04-08T00:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: "查询日志" }));
  fireEvent.click(screen.getByRole("button", { name: "查看详情" }));

  await waitFor(() => {
    expect(screen.getByText("请求详情")).toBeInTheDocument();
  });

  expect(screen.getAllByText("req-1").length).toBeGreaterThan(0);
  expect(screen.getByText("boom")).toBeInTheDocument();
});
