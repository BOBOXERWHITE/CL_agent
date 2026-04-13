import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import SystemSettingsPage from "../../src/pages/SystemSettingsPage";

vi.mock("../../src/api/settings", () => ({
  getSystemSettings: vi.fn().mockResolvedValue({
    editable_settings: {
      default_tenant_id: "演示租户",
      default_customer_id: "演示客户",
      chat_top_k: 3,
      chat_confidence_threshold: 0.2,
      default_eval_dataset: "zh-policy-smoke",
    },
    runtime_settings: {
      llm_provider: "deterministic",
      llm_model_name: "deterministic-policy-client",
      embedding_provider: "deterministic",
      embedding_model_name: "deterministic-hash-embedding",
      embedding_dimension: 16,
      vector_store_provider: "milvus",
      auth_enabled: false,
    },
  }),
  updateSystemSettings: vi.fn().mockResolvedValue({
    editable_settings: {
      default_tenant_id: "企业租户",
      default_customer_id: "企业客户",
      chat_top_k: 5,
      chat_confidence_threshold: 0.35,
      default_eval_dataset: "zh-policy-smoke",
    },
    runtime_settings: {
      llm_provider: "deterministic",
      llm_model_name: "deterministic-policy-client",
      embedding_provider: "deterministic",
      embedding_model_name: "deterministic-hash-embedding",
      embedding_dimension: 16,
      vector_store_provider: "milvus",
      auth_enabled: false,
    },
  }),
}));

test("loads and saves system settings while showing runtime config", async () => {
  render(<SystemSettingsPage />);

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "系统设置" })).toBeInTheDocument();
  });

  expect(screen.getByDisplayValue("演示租户")).toBeInTheDocument();
  expect(screen.getByText("运行配置")).toBeInTheDocument();
  expect(screen.getByText("deterministic-policy-client")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("默认租户 ID"), {
    target: { value: "企业租户" },
  });
  fireEvent.change(screen.getByLabelText("默认客户 ID"), {
    target: { value: "企业客户" },
  });
  fireEvent.change(screen.getByLabelText("问答召回数量"), {
    target: { value: "5" },
  });
  fireEvent.change(screen.getByLabelText("低置信度阈值"), {
    target: { value: "0.35" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存设置" }));

  await waitFor(() => {
    expect(screen.getByText("系统设置已保存。")).toBeInTheDocument();
  });

  expect(screen.getByDisplayValue("企业租户")).toBeInTheDocument();
});
