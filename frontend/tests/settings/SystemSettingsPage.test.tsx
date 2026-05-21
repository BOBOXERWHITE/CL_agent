import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import * as settingsApi from "../../src/api/settings";
import SystemSettingsPage from "../../src/pages/SystemSettingsPage";

vi.mock("../../src/api/chat", () => ({
  getLlmReadiness: vi.fn().mockResolvedValue({
    provider: "openai-compatible",
    model_name: "gpt-4o-mini",
    configured: true,
    available: true,
    status: "ready",
    message: "LLM 网关连通正常。",
    endpoint: "https://gateway.example.com/v1",
  }),
  runLlmSmokeTest: vi.fn().mockResolvedValue({
    provider: "openai-compatible",
    model_name: "gpt-4o-mini",
    configured: true,
    available: true,
    status: "ready",
    message: "LLM 烟雾测试通过。",
    endpoint: "https://gateway.example.com/v1",
    sample_question: "北京酒店报销上限是多少？",
    sample_evidence: "北京酒店报销上限为每晚 650 元。",
    answer_preview: "根据当前证据，北京酒店报销上限为每晚 650 元。",
    latency_ms: 18.2,
    token_usage: {
      input_tokens: 12,
      output_tokens: 8,
    },
  }),
  askPolicyQuestion: vi.fn(),
}));

vi.mock("../../src/api/knowledge", () => ({
  getEmbeddingReadiness: vi.fn().mockResolvedValue({
    provider: "openai-compatible",
    model_name: "text-embedding-3-small",
    configured: true,
    available: true,
    status: "ready",
    message: "Embedding 网关连通正常。",
    endpoint: "https://gateway.example.com/v1",
  }),
  runEmbeddingSmokeTest: vi.fn().mockResolvedValue({
    provider: "openai-compatible",
    model_name: "text-embedding-3-small",
    configured: true,
    available: true,
    status: "ready",
    message: "Embedding 烟雾测试通过。",
    endpoint: "https://gateway.example.com/v1",
    sample_text: "北京酒店报销上限",
    latency_ms: 10.6,
    vector_dimension: 1536,
  }),
}));

vi.mock("../../src/api/settings", () => ({
  getSystemSettings: vi.fn().mockResolvedValue({
    editable_settings: {
      default_tenant_id: "演示租户",
      default_customer_id: "演示客户",
      chat_top_k: 3,
      chat_confidence_threshold: 0.2,
      default_eval_dataset: "zh-policy-smoke",
      agent_router_provider: "keyword",
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
      agent_router_provider: "embedding",
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
  fireEvent.change(screen.getByLabelText("Agent 路由策略（智能路由）"), {
    target: { value: "embedding" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存设置" }));

  await waitFor(() => {
  expect(screen.getByText("系统设置已保存。")).toBeInTheDocument();
  });

  expect(screen.getByDisplayValue("企业租户")).toBeInTheDocument();
  expect(vi.mocked(settingsApi.updateSystemSettings)).toHaveBeenCalledWith(
    expect.objectContaining({ agent_router_provider: "embedding" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "检查 LLM 网关" }));
  await waitFor(() => {
    expect(screen.getByText("LLM 网关连通正常。")).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: "执行 LLM 烟雾测试" }));
  await waitFor(() => {
    expect(screen.getByText("LLM 烟雾测试通过。")).toBeInTheDocument();
  });
  expect(screen.getByText(/gpt-4o-mini/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "检查 Embedding 网关" }));
  await waitFor(() => {
    expect(screen.getByText("Embedding 网关连通正常。")).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: "执行 Embedding 烟雾测试" }));
  await waitFor(() => {
    expect(screen.getByText("Embedding 烟雾测试通过。")).toBeInTheDocument();
  });
  expect(screen.getByText(/1536/)).toBeInTheDocument();
});
