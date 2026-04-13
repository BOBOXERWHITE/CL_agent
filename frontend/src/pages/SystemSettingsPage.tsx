import { FormEvent, useEffect, useState } from "react";

import {
  getSystemSettings,
  updateSystemSettings,
  type EditableSystemSettings,
  type RuntimeSystemSettings,
} from "../api/settings";

interface SystemSettingsPageProps {
  onSaved?: (settings: EditableSystemSettings) => void;
}

const EMPTY_EDITABLE_SETTINGS: EditableSystemSettings = {
  default_tenant_id: "",
  default_customer_id: "",
  chat_top_k: 3,
  chat_confidence_threshold: 0.2,
  default_eval_dataset: "zh-policy-smoke",
};

export default function SystemSettingsPage({ onSaved }: SystemSettingsPageProps) {
  const [editableSettings, setEditableSettings] = useState<EditableSystemSettings>(EMPTY_EDITABLE_SETTINGS);
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSystemSettings | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  async function loadSettings() {
    setIsLoading(true);
    setErrorMessage("");
    try {
      const response = await getSystemSettings();
      setEditableSettings(response.editable_settings);
      setRuntimeSettings(response.runtime_settings);
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "系统设置加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadSettings();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      const response = await updateSystemSettings(editableSettings);
      setEditableSettings(response.editable_settings);
      setRuntimeSettings(response.runtime_settings);
      setSuccessMessage("系统设置已保存。");
      onSaved?.(response.editable_settings);
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "系统设置保存失败。");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">参数治理</p>
          <h2>系统设置</h2>
        </div>
        <span className="panel__tag">admin only</span>
      </div>
      <p className="panel__description">
        这里仅维护业务安全配置。基础设施地址、密钥、模型网关和 `.env`
        不在面板内编辑，仍然由部署环境控制。
      </p>

      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      {successMessage ? <p className="panel__success">{successMessage}</p> : null}

      <div className="settings-layout">
        <form className="data-card settings-form" onSubmit={(event) => void handleSubmit(event)}>
          <div className="data-card__header">
            <div>
              <h3>可编辑业务设置</h3>
              <span>{isLoading ? "加载中..." : "保存后即时生效"}</span>
            </div>
          </div>

          <div className="prompt-form__grid">
            <div className="field-group">
              <label htmlFor="default-tenant-id">默认租户 ID</label>
              <input
                id="default-tenant-id"
                value={editableSettings.default_tenant_id}
                onChange={(event) =>
                  setEditableSettings((current) => ({
                    ...current,
                    default_tenant_id: event.target.value,
                  }))
                }
              />
            </div>
            <div className="field-group">
              <label htmlFor="default-customer-id">默认客户 ID</label>
              <input
                id="default-customer-id"
                value={editableSettings.default_customer_id}
                onChange={(event) =>
                  setEditableSettings((current) => ({
                    ...current,
                    default_customer_id: event.target.value,
                  }))
                }
              />
            </div>
            <div className="field-group">
              <label htmlFor="chat-top-k">问答召回数量</label>
              <input
                id="chat-top-k"
                type="number"
                min={1}
                max={20}
                value={String(editableSettings.chat_top_k)}
                onChange={(event) =>
                  setEditableSettings((current) => ({
                    ...current,
                    chat_top_k: Number(event.target.value || current.chat_top_k),
                  }))
                }
              />
            </div>
            <div className="field-group">
              <label htmlFor="chat-confidence-threshold">低置信度阈值</label>
              <input
                id="chat-confidence-threshold"
                type="number"
                min={0}
                max={1}
                step="0.01"
                value={String(editableSettings.chat_confidence_threshold)}
                onChange={(event) =>
                  setEditableSettings((current) => ({
                    ...current,
                    chat_confidence_threshold: Number(
                      event.target.value || current.chat_confidence_threshold,
                    ),
                  }))
                }
              />
            </div>
            <div className="field-group">
              <label htmlFor="default-eval-dataset">默认评测集</label>
              <input
                id="default-eval-dataset"
                value={editableSettings.default_eval_dataset}
                onChange={(event) =>
                  setEditableSettings((current) => ({
                    ...current,
                    default_eval_dataset: event.target.value,
                  }))
                }
              />
            </div>
          </div>

          <div className="prompt-form__footer">
            <p className="upload-form__caption">
              修改后，问答默认参数、页面默认租户 / 客户和默认评测集会优先读取这里的配置。
            </p>
            <button type="submit" disabled={isSaving || isLoading}>
              {isSaving ? "保存中..." : "保存设置"}
            </button>
          </div>
        </form>

        <article className="data-card">
          <div className="data-card__header">
            <div>
              <h3>运行配置</h3>
              <span>只读展示</span>
            </div>
          </div>
          {runtimeSettings ? (
            <div className="detail-grid">
              <div className="detail-item">
                <span>LLM Provider</span>
                <strong>{runtimeSettings.llm_provider}</strong>
              </div>
              <div className="detail-item">
                <span>LLM Model</span>
                <strong>{runtimeSettings.llm_model_name}</strong>
              </div>
              <div className="detail-item">
                <span>Embedding Provider</span>
                <strong>{runtimeSettings.embedding_provider}</strong>
              </div>
              <div className="detail-item">
                <span>Embedding Model</span>
                <strong>{runtimeSettings.embedding_model_name}</strong>
              </div>
              <div className="detail-item">
                <span>Embedding 维度</span>
                <strong>{runtimeSettings.embedding_dimension}</strong>
              </div>
              <div className="detail-item">
                <span>向量存储</span>
                <strong>{runtimeSettings.vector_store_provider}</strong>
              </div>
              <div className="detail-item">
                <span>鉴权开关</span>
                <strong>{runtimeSettings.auth_enabled ? "已开启" : "未开启"}</strong>
              </div>
            </div>
          ) : (
            <p className="data-table__empty">正在加载运行配置...</p>
          )}
        </article>
      </div>
    </section>
  );
}
