import { FormEvent, useState } from "react";


interface DocumentUploaderProps {
  disabled?: boolean;
  onSubmit: (input: {
    tenantId: string;
    customerId: string;
    file: File;
  }) => Promise<void>;
}

export default function DocumentUploader({ disabled = false, onSubmit }: DocumentUploaderProps) {
  const [tenantId, setTenantId] = useState("演示租户");
  const [customerId, setCustomerId] = useState("演示客户");
  const [file, setFile] = useState<File | null>(null);
  const [errorMessage, setErrorMessage] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!file) {
      setErrorMessage("请先选择一份文档文件。");
      return;
    }

    setErrorMessage("");
    await onSubmit({
      tenantId,
      customerId,
      file,
    });
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
          accept=".docx,.pdf"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </div>
      <div className="upload-form__footer">
        <div className="upload-form__hint">
          <strong>入库提示</strong>
          <p>{file ? `当前文件：${file.name}` : "支持上传 DOCX / PDF，系统会自动解析并切块。"}</p>
        </div>
        <button type="submit" disabled={disabled}>
          开始入库
        </button>
      </div>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      <p className="upload-form__caption">
        租户和客户字段会一并写入元数据，用于后续检索隔离和追踪。
      </p>
    </form>
  );
}
