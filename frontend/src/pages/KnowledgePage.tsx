import { startTransition, useEffect, useState } from "react";

import { type KnowledgeJob, listKnowledgeJobs, uploadKnowledgeDocument } from "../api/knowledge";
import DocumentUploader from "../components/DocumentUploader";


const STATUS_LABELS: Record<string, string> = {
  uploaded: "已上传",
  processing: "处理中",
  completed: "已完成",
  failed: "失败",
};


export default function KnowledgePage() {
  const [jobs, setJobs] = useState<KnowledgeJob[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

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

    try {
      await uploadKnowledgeDocument(input);
      await loadJobs();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "入库请求失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="panel panel--knowledge">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">知识入库</p>
          <h2>文档进入系统的第一站</h2>
        </div>
        <span className="panel__tag">DOCX / PDF</span>
      </div>
      <p className="panel__description">
        上传制度文档后，系统会完成解析、切块、对象存储和向量写入。
        你可以直接在这里观察每一份资料的处理状态与分块结果。
      </p>
      <DocumentUploader disabled={isSubmitting} onSubmit={handleUpload} />
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      <div className="data-card">
        <div className="data-card__header">
          <h3>任务看板</h3>
          <span>{jobs.length} 条记录</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>任务 ID</th>
              <th>文件名</th>
              <th>状态</th>
              <th>分块数</th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 ? (
              <tr>
                <td colSpan={4} className="data-table__empty">
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
                  <td>{job.chunk_count}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
