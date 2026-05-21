import { FormEvent, useEffect, useState } from "react";


interface DocumentUploaderProps {
  disabled?: boolean;
  defaultTenantId?: string;
  defaultCustomerId?: string;
  onSubmit: (input: {
    tenantId: string;
    customerId: string;
    file: File;
  }) => Promise<void>;
}

export default function DocumentUploader({
  disabled = false,
  defaultTenantId = "演示租户",
  defaultCustomerId = "演示客户",
  onSubmit,
}: DocumentUploaderProps) {
  const [tenantId, setTenantId] = useState(defaultTenantId);
  const [customerId, setCustomerId] = useState(defaultCustomerId);
  const [files, setFiles] = useState<File[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  // Track sequential upload progress so users see "上传中 3/23" rather than a
  // frozen button. We submit one file at a time to stay under the backend
  // rate limit and keep error attribution clean.
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null);

  useEffect(() => {
    setTenantId(defaultTenantId);
  }, [defaultTenantId]);

  useEffect(() => {
    setCustomerId(defaultCustomerId);
  }, [defaultCustomerId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (files.length === 0) {
      setErrorMessage("请先选择至少一份文档文件。");
      return;
    }

    setErrorMessage("");
    const failed: string[] = [];
    for (let i = 0; i < files.length; i += 1) {
      const current = files[i];
      setProgress({ current: i + 1, total: files.length });
      try {
        await onSubmit({ tenantId, customerId, file: current });
      } catch (err) {
        // Collect failures but keep going so a single bad file doesn't block
        // a 23-file batch. Final summary surfaces all failures together.
        const reason = err instanceof Error ? err.message : String(err);
        failed.push(`${current.name}: ${reason}`);
      }
    }
    setProgress(null);
    setFiles([]);
    if (failed.length > 0) {
      setErrorMessage(`部分文件入库失败 (${failed.length}/${files.length}):\n${failed.join("\n")}`);
    }
  }

  return (
    <form className="upload-form" onSubmit={(event) => void handleSubmit(event)}>
      <div className="upload-form__grid">
        <div className="field-group">
          <label htmlFor="tenant-id">租户 ID</label>
          <input
            id="tenant-id"
            name="tenantId"
            type="text"
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
          />
        </div>
        <div className="field-group">
          <label htmlFor="customer-id">客户 ID</label>
          <input
            id="customer-id"
            name="customerId"
            type="text"
            value={customerId}
            onChange={(event) => setCustomerId(event.target.value)}
          />
        </div>
      </div>
      <div className="field-group field-group--file">
        <label htmlFor="document-file">文档文件</label>
        <input
          id="document-file"
          name="file"
          type="file"
          multiple
          accept=".docx,.pdf,.md,.markdown,.txt"
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
        />
      </div>
      <div className="upload-form__footer">
        <div className="upload-form__hint">
          <strong>入库提示</strong>
          {files.length === 0 ? (
            <p>支持上传 DOCX / PDF / Markdown (.md) / TXT，可多选；系统会自动解析、切块并写入向量库。</p>
          ) : (
            <p>
              已选择 {files.length} 份文件
              {progress ? `，正在上传 ${progress.current}/${progress.total}` : ""}：
              {files.slice(0, 5).map((f) => f.name).join("、")}
              {files.length > 5 ? ` 等 ${files.length} 份` : ""}
            </p>
          )}
        </div>
        <button type="submit" disabled={disabled || progress !== null}>
          {progress ? `上传中 ${progress.current}/${progress.total}` : "开始入库"}
        </button>
      </div>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      <p className="upload-form__caption">
        租户和客户字段会一并写入元数据，用于后续检索隔离和问题追踪。
      </p>
    </form>
  );
}
