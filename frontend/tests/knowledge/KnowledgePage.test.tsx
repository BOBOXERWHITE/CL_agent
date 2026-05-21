import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, vi } from "vitest";

import * as knowledgeApi from "../../src/api/knowledge";
import KnowledgePage from "../../src/pages/KnowledgePage";

vi.mock("../../src/api/knowledge", () => ({
  listKnowledgeJobs: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
  rebuildKnowledgeIndex: vi.fn(),
  rechunkKnowledgeDocuments: vi.fn(),
  deleteKnowledgeDocument: vi.fn(),
  checkKnowledgeEmbeddingReadiness: vi.fn(),
  runKnowledgeEmbeddingSmokeTest: vi.fn(),
}));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([]);
  vi.mocked(knowledgeApi.checkKnowledgeEmbeddingReadiness).mockResolvedValue({
    provider: "deterministic",
    model_name: "deterministic-hash-embedding",
    configured: true,
    available: true,
    status: "ready",
    message: "当前使用本地 deterministic embedding，无需额外连通性检查。",
    endpoint: null,
  });
  vi.mocked(knowledgeApi.runKnowledgeEmbeddingSmokeTest).mockResolvedValue({
    provider: "deterministic",
    model_name: "deterministic-hash-embedding",
    configured: true,
    available: true,
    status: "ready",
    message: "Embedding 烟雾测试通过。",
    endpoint: null,
    sample_text: "北京酒店报销上限",
    latency_ms: 12.5,
    vector_dimension: 16,
  });
});

test("uploads a document and renders the returned job", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValueOnce([]);
  vi.mocked(knowledgeApi.uploadKnowledgeDocument).mockResolvedValue({
    job_id: "job-1",
    document_id: "doc-1",
    status: "completed",
  });
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValueOnce([
    {
      job_id: "job-1",
      document_id: "doc-1",
      filename: "policy.docx",
      status: "completed",
      chunk_count: 2,
      tenant_id: "t1",
      customer_id: "c1",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ]);

  render(<KnowledgePage />);

  fireEvent.change(screen.getByLabelText("租户 ID"), {
    target: { value: "t1" },
  });
  fireEvent.change(screen.getByLabelText("客户 ID"), {
    target: { value: "c1" },
  });
  fireEvent.change(screen.getByLabelText("文档文件"), {
    target: {
      files: [
        new File(["policy"], "policy.docx", {
          type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }),
      ],
    },
  });

  fireEvent.click(screen.getByRole("button", { name: "开始入库" }));

  await waitFor(() => {
    expect(screen.getByText("policy.docx")).toBeInTheDocument();
  });
  expect(screen.getByText("job-1")).toBeInTheDocument();
  expect(screen.getByText("已完成")).toBeInTheDocument();
  expect(knowledgeApi.uploadKnowledgeDocument).toHaveBeenCalled();
});

test("rebuilds knowledge vectors and shows the result summary", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([
    {
      job_id: "job-1",
      document_id: "doc-1",
      filename: "policy.docx",
      status: "completed",
      chunk_count: 2,
      tenant_id: "t1",
      customer_id: "c1",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ]);
  vi.mocked(knowledgeApi.rebuildKnowledgeIndex).mockResolvedValue({
    scope: "all",
    document_count: 1,
    chunk_count: 2,
    document_ids: ["doc-1"],
  });

  render(<KnowledgePage />);

  fireEvent.click(screen.getByRole("button", { name: "重建向量索引" }));

  await waitFor(() => {
    expect(screen.getByText("已完成 1 份文档、2 个分块的向量重建。")).toBeInTheDocument();
  });

  expect(knowledgeApi.rebuildKnowledgeIndex).toHaveBeenCalledWith({});
});

test("shows stale vector status and rebuilds a single document", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([
    {
      job_id: "job-1",
      document_id: "doc-1",
      filename: "policy.docx",
      status: "completed",
      chunk_count: 2,
      tenant_id: "t1",
      customer_id: "c1",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
      requires_reindex: true,
      stored_embedding_profile: {
        provider: "deterministic",
        model_name: "deterministic-hash-embedding",
        dimension: 16,
        profile_key: "deterministic|deterministic-hash-embedding|16",
      },
      current_embedding_profile: {
        provider: "openai-compatible",
        model_name: "text-embedding-3-small",
        dimension: 1536,
        profile_key: "openai-compatible|text-embedding-3-small|1536|https://example.com/v1",
      },
    },
  ]);
  vi.mocked(knowledgeApi.rebuildKnowledgeIndex).mockResolvedValue({
    scope: "document",
    document_count: 1,
    chunk_count: 2,
    document_ids: ["doc-1"],
  });

  render(<KnowledgePage />);

  await waitFor(() => {
    expect(screen.getByText("待重建")).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: "重建此文档" }));

  await waitFor(() => {
    expect(screen.getByText("已完成 policy.docx 的向量重建，共 2 个分块。")).toBeInTheDocument();
  });

  expect(knowledgeApi.rebuildKnowledgeIndex).toHaveBeenCalledWith({ documentId: "doc-1" });
});

test("checks embedding readiness and rebuilds only stale documents", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([
    {
      job_id: "job-1",
      document_id: "doc-1",
      filename: "policy-old.docx",
      status: "completed",
      chunk_count: 2,
      tenant_id: "t1",
      customer_id: "c1",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
      requires_reindex: true,
      stored_embedding_profile: {
        provider: "deterministic",
        model_name: "deterministic-hash-embedding",
        dimension: 16,
        profile_key: "deterministic|deterministic-hash-embedding|16",
      },
      current_embedding_profile: {
        provider: "openai-compatible",
        model_name: "text-embedding-3-small",
        dimension: 1536,
        profile_key: "openai-compatible|text-embedding-3-small|1536|https://example.com/v1",
      },
    },
    {
      job_id: "job-2",
      document_id: "doc-2",
      filename: "policy-new.docx",
      status: "completed",
      chunk_count: 3,
      tenant_id: "t1",
      customer_id: "c1",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
      requires_reindex: false,
      stored_embedding_profile: {
        provider: "openai-compatible",
        model_name: "text-embedding-3-small",
        dimension: 1536,
        profile_key: "openai-compatible|text-embedding-3-small|1536|https://example.com/v1",
      },
      current_embedding_profile: {
        provider: "openai-compatible",
        model_name: "text-embedding-3-small",
        dimension: 1536,
        profile_key: "openai-compatible|text-embedding-3-small|1536|https://example.com/v1",
      },
    },
  ]);
  vi.mocked(knowledgeApi.checkKnowledgeEmbeddingReadiness).mockResolvedValue({
    provider: "openai-compatible",
    model_name: "text-embedding-3-small",
    configured: true,
    available: true,
    status: "ready",
    message: "Embedding 网关连通正常。",
    endpoint: "https://example.com/v1",
  });
  vi.mocked(knowledgeApi.rebuildKnowledgeIndex).mockResolvedValue({
    scope: "stale",
    document_count: 1,
    chunk_count: 2,
    document_ids: ["doc-1"],
  });

  render(<KnowledgePage />);

  fireEvent.click(screen.getByRole("button", { name: "检查模型网关" }));

  await waitFor(() => {
    expect(screen.getByText("Embedding 网关连通正常。")).toBeInTheDocument();
  });

  await waitFor(() => {
    expect(screen.getByText("待重建")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重建待重建文档" })).not.toBeDisabled();
  });

  fireEvent.click(screen.getByRole("button", { name: "重建待重建文档" }));

  await waitFor(() => {
    expect(knowledgeApi.rebuildKnowledgeIndex).toHaveBeenCalledWith({ staleOnly: true });
  });

  expect(knowledgeApi.checkKnowledgeEmbeddingReadiness).toHaveBeenCalled();
  expect(screen.getByText("待重建")).toBeInTheDocument();
});

test("runs embedding smoke test and shows latency with vector dimension", async () => {
  vi.mocked(knowledgeApi.runKnowledgeEmbeddingSmokeTest).mockResolvedValue({
    provider: "openai-compatible",
    model_name: "text-embedding-3-small",
    configured: true,
    available: true,
    status: "ready",
    message: "Embedding 烟雾测试通过。",
    endpoint: "https://example.com/v1",
    sample_text: "北京酒店报销上限",
    latency_ms: 28.4,
    vector_dimension: 1536,
  });

  render(<KnowledgePage />);

  fireEvent.click(screen.getByRole("button", { name: "执行真实向量测试" }));

  await waitFor(() => {
    expect(screen.getByText("Embedding 烟雾测试通过。")).toBeInTheDocument();
  });

  expect(screen.getByText(/1536 维/)).toBeInTheDocument();
  expect(screen.getByText(/28\.4 ms/)).toBeInTheDocument();
  expect(knowledgeApi.runKnowledgeEmbeddingSmokeTest).toHaveBeenCalled();
});

test("deletes a document and refreshes the job list", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs)
    .mockResolvedValueOnce([
      {
        job_id: "job-1",
        document_id: "doc-1",
        filename: "policy.docx",
        status: "completed",
        chunk_count: 2,
        tenant_id: "t1",
        customer_id: "c1",
        created_at: "2026-04-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
        requires_reindex: false,
        current_embedding_profile: {
          provider: "deterministic",
          model_name: "deterministic-hash-embedding",
          dimension: 16,
          profile_key: "deterministic|deterministic-hash-embedding|16",
        },
      },
    ])
    .mockResolvedValueOnce([]);
  vi.mocked(knowledgeApi.deleteKnowledgeDocument).mockResolvedValue({
    document_id: "doc-1",
    filename: "policy.docx",
    chunk_count: 2,
  });

  render(<KnowledgePage />);

  await waitFor(() => {
    expect(screen.getByText("policy.docx")).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: "删除此文档" }));

  await waitFor(() => {
    expect(screen.getByText("已删除 policy.docx，共清理 2 个分块。")).toBeInTheDocument();
  });

  await waitFor(() => {
    expect(screen.getByText("还没有入库任务，先上传一份政策文档。")).toBeInTheDocument();
  });

  expect(knowledgeApi.deleteKnowledgeDocument).toHaveBeenCalledWith("doc-1");
});

test("rechunks all completed documents from the header button", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([
    {
      job_id: "job-1",
      document_id: "doc-1",
      filename: "policy.docx",
      status: "completed",
      chunk_count: 2,
      tenant_id: "t1",
      customer_id: "c1",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ]);
  vi.mocked(knowledgeApi.rechunkKnowledgeDocuments).mockResolvedValue({
    scope: "all",
    document_count: 1,
    chunk_count: 5,
    document_ids: ["doc-1"],
  });

  render(<KnowledgePage />);

  await waitFor(() => {
    expect(screen.getByText("policy.docx")).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: "重新切块（全部）" }));

  await waitFor(() => {
    expect(
      screen.getByText("已完成 1 份文档、5 个分块的重切块。"),
    ).toBeInTheDocument();
  });

  expect(knowledgeApi.rechunkKnowledgeDocuments).toHaveBeenCalledWith({});
});

test("rechunks a single document from its row action", async () => {
  vi.mocked(knowledgeApi.listKnowledgeJobs).mockResolvedValue([
    {
      job_id: "job-1",
      document_id: "doc-1",
      filename: "policy.docx",
      status: "completed",
      chunk_count: 2,
      tenant_id: "t1",
      customer_id: "c1",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ]);
  vi.mocked(knowledgeApi.rechunkKnowledgeDocuments).mockResolvedValue({
    scope: "document",
    document_count: 1,
    chunk_count: 4,
    document_ids: ["doc-1"],
  });

  render(<KnowledgePage />);

  await waitFor(() => {
    expect(screen.getByText("policy.docx")).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole("button", { name: "重新切块" }));

  await waitFor(() => {
    expect(
      screen.getByText("已完成 policy.docx 的重切块，共 4 个新分块。"),
    ).toBeInTheDocument();
  });

  expect(knowledgeApi.rechunkKnowledgeDocuments).toHaveBeenCalledWith({
    documentId: "doc-1",
  });
});
