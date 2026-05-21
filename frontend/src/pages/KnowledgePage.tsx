import { startTransition, useEffect, useState } from "react";

import {
  deleteKnowledgeDocument,
  type KnowledgeEmbeddingReadiness,
  type KnowledgeEmbeddingSmokeTest,
  type KnowledgeJob,
  checkKnowledgeEmbeddingReadiness,
  listKnowledgeJobs,
  rebuildKnowledgeIndex,
  rechunkKnowledgeDocuments,
  runKnowledgeEmbeddingSmokeTest,
  uploadKnowledgeDocument,
} from "../api/knowledge";
import DocumentUploader from "../components/DocumentUploader";

const STATUS_LABELS: Record<string, string> = {
  uploaded: "已上传",
  processing: "处理中",
  completed: "已完成",
  failed: "失败",
};

interface KnowledgePageProps {
  defaultTenantId?: string;
  defaultCustomerId?: string;
}

export default function KnowledgePage({
  defaultTenantId = "演示租户",
  defaultCustomerId = "演示客户",
}: KnowledgePageProps) {
  const [jobs, setJobs] = useState<KnowledgeJob[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRebuilding, setIsRebuilding] = useState(false);
  const [isRechunking, setIsRechunking] = useState(false);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const [isCheckingReadiness, setIsCheckingReadiness] = useState(false);
  const [isRunningSmokeTest, setIsRunningSmokeTest] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [embeddingReadiness, setEmbeddingReadiness] = useState<KnowledgeEmbeddingReadiness | null>(null);
  const [embeddingSmokeTest, setEmbeddingSmokeTest] = useState<KnowledgeEmbeddingSmokeTest | null>(null);
  const currentProfile = jobs[0]?.current_embedding_profile ?? null;
  const staleJobCount = jobs.filter((job) => job.requires_reindex).length;
  const completedJobCount = jobs.filter((job) => job.status === "completed").length;

  async function loadJobs() {
    const nextJobs = await listKnowledgeJobs();
    startTransition(() => {
      setJobs(nextJobs);
    });
  }

  useEffect(() => {
    void loadJobs().catch((error: unknown) => {
      setErrorMessage(error instanceof Error ? error.message : "任务列表加载失败。");
    });
  }, []);

  async function handleUpload(input: {
    tenantId: string;
    customerId: string;
    file: File;
  }) {
    setIsSubmitting(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      await uploadKnowledgeDocument(input);
      await loadJobs();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "入库请求失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRebuild(job?: KnowledgeJob) {
    setIsRebuilding(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      const result = await rebuildKnowledgeIndex(job ? { documentId: job.document_id } : {});
      setSuccessMessage(
        job
          ? `已完成 ${job.filename} 的向量重建，共 ${result.chunk_count} 个分块。`
          : `已完成 ${result.document_count} 份文档、${result.chunk_count} 个分块的向量重建。`,
      );
      await loadJobs();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "向量重建失败。");
    } finally {
      setIsRebuilding(false);
    }
  }

  async function handleRechunk(job?: KnowledgeJob) {
    setIsRechunking(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      const result = await rechunkKnowledgeDocuments(
        job ? { documentId: job.document_id } : {},
      );
      setSuccessMessage(
        job
          ? `已完成 ${job.filename} 的重切块，共 ${result.chunk_count} 个新分块。`
          : `已完成 ${result.document_count} 份文档、${result.chunk_count} 个分块的重切块。`,
      );
      await loadJobs();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "重新切块失败。");
    } finally {
      setIsRechunking(false);
    }
  }

  async function handleRebuildStaleJobs() {
    setIsRebuilding(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      const result = await rebuildKnowledgeIndex({ staleOnly: true });
      setSuccessMessage(`已完成 ${result.document_count} 份待重建文档、${result.chunk_count} 个分块的向量重建。`);
      await loadJobs();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "待重建文档向量重建失败。");
    } finally {
      setIsRebuilding(false);
    }
  }

  async function handleDelete(job: KnowledgeJob) {
    setDeletingDocumentId(job.document_id);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      const result = await deleteKnowledgeDocument(job.document_id);
      setSuccessMessage(`已删除 ${result.filename}，共清理 ${result.chunk_count} 个分块。`);
      await loadJobs();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "删除文档失败。");
    } finally {
      setDeletingDocumentId(null);
    }
  }

  async function handleCheckEmbeddingReadiness() {
    setIsCheckingReadiness(true);
    setErrorMessage("");

    try {
      const readiness = await checkKnowledgeEmbeddingReadiness();
      setEmbeddingReadiness(readiness);
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "模型网关检查失败。");
    } finally {
      setIsCheckingReadiness(false);
    }
  }

  async function handleRunEmbeddingSmokeTest() {
    setIsRunningSmokeTest(true);
    setErrorMessage("");

    try {
      const result = await runKnowledgeEmbeddingSmokeTest();
      setEmbeddingSmokeTest(result);
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "向量烟雾测试失败。");
    } finally {
      setIsRunningSmokeTest(false);
    }
  }

  return (
    <section className="panel panel--knowledge">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">知识入库</p>
          <h2>知识库管理</h2>
        </div>
        <span className="panel__tag">DOCX / PDF</span>
      </div>

      <p className="panel__description">
        上传制度文档后，系统会完成解析、切块、对象存储和向量写入。你可以直接在这里观察每一份资料的处理状态与分块结果。
      </p>

      <div className="overview-grid overview-grid--triple">
        <article className="overview-card">
          <span>文档总数</span>
          <strong>{jobs.length}</strong>
          <p>当前知识库已登记的文档数量。</p>
        </article>
        <article className="overview-card">
          <span>待重建文档</span>
          <strong>{staleJobCount}</strong>
          <p>向量配置发生变化后，需要重新生成向量的文档。</p>
        </article>
        <article className="overview-card">
          <span>已完成文档</span>
          <strong>{completedJobCount}</strong>
          <p>已完成解析、切块和向量写入的文档。</p>
        </article>
      </div>

      {currentProfile ? (
        <p className="panel__meta">
          当前向量配置：{currentProfile.provider} / {currentProfile.model_name} / {currentProfile.dimension} 维
        </p>
      ) : null}

      <div className="readiness-card">
        <div className="readiness-card__header">
          <div>
            <strong>模型网关检查</strong>
            <p>切换到真实 embedding 前，先确认网关配置、连通性和真实向量返回结果。</p>
          </div>
          <div className="readiness-card__actions">
            <button
              type="button"
              className="secondary-button"
              disabled={isCheckingReadiness || isRunningSmokeTest}
              onClick={() => void handleCheckEmbeddingReadiness()}
            >
              {isCheckingReadiness ? "检查中..." : "检查模型网关"}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={isCheckingReadiness || isRunningSmokeTest}
              onClick={() => void handleRunEmbeddingSmokeTest()}
            >
              {isRunningSmokeTest ? "测试中..." : "执行真实向量测试"}
            </button>
          </div>
        </div>

        {embeddingReadiness ? (
          <div className="readiness-card__body">
            <span
              className={`status-pill ${
                embeddingReadiness.available ? "status-pill--aligned" : "status-pill--failed"
              }`}
            >
              {embeddingReadiness.available ? "可用" : "不可用"}
            </span>
            <p>{embeddingReadiness.message}</p>
            <small>
              {embeddingReadiness.provider} / {embeddingReadiness.model_name}
              {embeddingReadiness.endpoint ? ` / ${embeddingReadiness.endpoint}` : ""}
            </small>
          </div>
        ) : null}

        {embeddingSmokeTest ? (
          <div className="readiness-card__body">
            <span
              className={`status-pill ${
                embeddingSmokeTest.available ? "status-pill--aligned" : "status-pill--failed"
              }`}
            >
              {embeddingSmokeTest.available ? "可用" : "不可用"}
            </span>
            <p>{embeddingSmokeTest.message}</p>
            <small>
              {embeddingSmokeTest.provider} / {embeddingSmokeTest.model_name}
              {embeddingSmokeTest.endpoint ? ` / ${embeddingSmokeTest.endpoint}` : ""}
            </small>
            <small>
              {embeddingSmokeTest.vector_dimension} 维 / {embeddingSmokeTest.latency_ms} ms / 样本文本：
              {embeddingSmokeTest.sample_text}
            </small>
          </div>
        ) : null}
      </div>

      <DocumentUploader
        disabled={isSubmitting}
        defaultTenantId={defaultTenantId}
        defaultCustomerId={defaultCustomerId}
        onSubmit={handleUpload}
      />

      {successMessage ? <p className="panel__success">{successMessage}</p> : null}
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}

      <div className="data-card">
        <div className="data-card__header">
          <div>
            <h3>任务看板</h3>
            <span>{jobs.length} 条记录</span>
          </div>
          <div className="data-card__actions">
            <button
              type="button"
              className="secondary-button"
              disabled={
                isSubmitting ||
                isRebuilding ||
                isRechunking ||
                deletingDocumentId !== null ||
                staleJobCount === 0
              }
              onClick={() => void handleRebuildStaleJobs()}
            >
              {isRebuilding ? "重建中..." : "重建待重建文档"}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={
                isSubmitting || isRebuilding || isRechunking || deletingDocumentId !== null
              }
              onClick={() => void handleRebuild()}
            >
              {isRebuilding ? "重建中..." : "重建向量索引"}
            </button>
            <button
              type="button"
              className="secondary-button"
              title="读取原文件，按当前 chunker 逻辑重新切块（适用于 chunker 升级后）"
              disabled={
                isSubmitting ||
                isRebuilding ||
                isRechunking ||
                deletingDocumentId !== null ||
                completedJobCount === 0
              }
              onClick={() => void handleRechunk()}
            >
              {isRechunking ? "重切块中..." : "重新切块（全部）"}
            </button>
          </div>
        </div>

        <table className="data-table">
          <thead>
            <tr>
              <th>任务 ID</th>
              <th>文件名</th>
              <th>状态</th>
              <th>向量状态</th>
              <th>分块数</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 ? (
              <tr>
                <td colSpan={6} className="data-table__empty">
                  还没有入库任务，先上传一份政策文档。
                </td>
              </tr>
            ) : (
              jobs.map((job) => (
                <tr key={job.job_id}>
                  <td className="data-table__mono">{job.job_id}</td>
                  <td>{job.filename}</td>
                  <td>
                    <span className={`status-pill status-pill--${job.status}`}>
                      {STATUS_LABELS[job.status] ?? job.status}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`status-pill ${
                        job.requires_reindex ? "status-pill--stale" : "status-pill--aligned"
                      }`}
                    >
                      {job.requires_reindex ? "待重建" : "已对齐"}
                    </span>
                  </td>
                  <td>{job.chunk_count}</td>
                  <td>
                    <div className="data-card__actions">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={
                          isSubmitting ||
                          isRebuilding ||
                          isRechunking ||
                          deletingDocumentId !== null ||
                          job.status !== "completed"
                        }
                        onClick={() => void handleRebuild(job)}
                      >
                        重建此文档
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        title="读取原文件，按当前 chunker 逻辑重新切块"
                        disabled={
                          isSubmitting ||
                          isRebuilding ||
                          isRechunking ||
                          deletingDocumentId !== null ||
                          job.status !== "completed"
                        }
                        onClick={() => void handleRechunk(job)}
                      >
                        {isRechunking ? "重切块中..." : "重新切块"}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={
                          isSubmitting || isRebuilding || isRechunking || deletingDocumentId !== null
                        }
                        onClick={() => void handleDelete(job)}
                      >
                        {deletingDocumentId === job.document_id ? "删除中..." : "删除此文档"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
