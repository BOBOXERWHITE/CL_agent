import { FormEvent, useEffect, useState } from "react";

import { getLlmReadiness, runLlmSmokeTest, type LlmReadiness, type LlmSmokeTest } from "../api/chat";
import {
  getEmbeddingReadiness,
  runEmbeddingSmokeTest,
  type KnowledgeEmbeddingReadiness,
  type KnowledgeEmbeddingSmokeTest,
} from "../api/knowledge";
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

function formatLatency(latencyMs: number): string {
  return `${latencyMs.toFixed(1)} ms`;
}

export default function SystemSettingsPage({ onSaved }: SystemSettingsPageProps) {
  const [editableSettings, setEditableSettings] = useState<EditableSystemSettings>(EMPTY_EDITABLE_SETTINGS);
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSystemSettings | null>(null);
  const [llmReadiness, setLlmReadiness] = useState<LlmReadiness | null>(null);
  const [llmSmokeTest, setLlmSmokeTest] = useState<LlmSmokeTest | null>(null);
  const [embeddingReadiness, setEmbeddingReadiness] = useState<KnowledgeEmbeddingReadiness | null>(null);
  const [embeddingSmokeTest, setEmbeddingSmokeTest] = useState<KnowledgeEmbeddingSmokeTest | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isCheckingLlm, setIsCheckingLlm] = useState(false);
  const [isRunningLlmSmokeTest, setIsRunningLlmSmokeTest] = useState(false);
  const [isCheckingEmbedding, setIsCheckingEmbedding] = useState(false);
  const [isRunningEmbeddingSmokeTest, setIsRunningEmbeddingSmokeTest] = useState(false);

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

  async function handleCheckLlmReadiness() {
    setIsCheckingLlm(true);
    setErrorMessage("");
    try {
      setLlmReadiness(await getLlmReadiness());
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "LLM 网关检查失败。");
    } finally {
      setIsCheckingLlm(false);
    }
  }

  async function handleRunLlmSmokeTest() {
    setIsRunningLlmSmokeTest(true);
    setErrorMessage("");
    try {
      setLlmSmokeTest(await runLlmSmokeTest());
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "LLM 烟雾测试失败。");
    } finally {
      setIsRunningLlmSmokeTest(false);
    }
  }

  async function handleCheckEmbeddingReadiness() {
    setIsCheckingEmbedding(true);
    setErrorMessage("");
    try {
      setEmbeddingReadiness(await getEmbeddingReadiness());
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "Embedding 网关检查失败。");
    } finally {
      setIsCheckingEmbedding(false);
    }
  }

  async function handleRunEmbeddingSmokeTest() {
    setIsRunningEmbeddingSmokeTest(true);
    setErrorMessage("");
    try {
      setEmbeddingSmokeTest(await runEmbeddingSmokeTest());
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "Embedding 烟雾测试失败。");
    } finally {
      setIsRunningEmbeddingSmokeTest(false);
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
        这里只维护业务安全配置和模型网关联调结果。基础设施地址、密钥和 `.env`
        仍由部署环境控制，不在页面内直接编辑。
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
              这些值会覆盖页面默认租户、默认客户、问答检索阈值和默认评测集。
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

      <div className="settings-layout">
        <article className="data-card">
          <div className="data-card__header">
            <div>
              <h3>LLM 网关联调</h3>
              <span>检查模型列表与对话生成</span>
            </div>
          </div>
          <div className="eval-detail-toolbar__actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => void handleCheckLlmReadiness()}
              disabled={isCheckingLlm}
            >
              {isCheckingLlm ? "检查中..." : "检查 LLM 网关"}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void handleRunLlmSmokeTest()}
              disabled={isRunningLlmSmokeTest}
            >
              {isRunningLlmSmokeTest ? "执行中..." : "执行 LLM 烟雾测试"}
            </button>
          </div>
          {llmReadiness ? (
            <div className="detail-grid">
              <div className="detail-item">
                <span>状态</span>
                <strong>{llmReadiness.status}</strong>
              </div>
              <div className="detail-item">
                <span>模型</span>
                <strong>{llmReadiness.model_name}</strong>
              </div>
              <div className="detail-item detail-item--full">
                <span>结果</span>
                <strong>{llmReadiness.message}</strong>
              </div>
              {llmReadiness.endpoint ? (
                <div className="detail-item detail-item--full">
                  <span>网关地址</span>
                  <strong>{llmReadiness.endpoint}</strong>
                </div>
              ) : null}
            </div>
          ) : null}
          {llmSmokeTest ? (
            <div className="detail-grid">
              <div className="detail-item">
                <span>延迟</span>
                <strong>{formatLatency(llmSmokeTest.latency_ms)}</strong>
              </div>
              <div className="detail-item">
                <span>Token 用量</span>
                <strong>
                  {llmSmokeTest.token_usage.input_tokens} / {llmSmokeTest.token_usage.output_tokens}
                </strong>
              </div>
              <div className="detail-item detail-item--full">
                <span>结果</span>
                <strong>{llmSmokeTest.message}</strong>
              </div>
              <div className="detail-item detail-item--full">
                <span>答案预览</span>
                <strong>{llmSmokeTest.answer_preview || "无"}</strong>
              </div>
            </div>
          ) : null}
        </article>

        <article className="data-card">
          <div className="data-card__header">
            <div>
              <h3>Embedding 网关联调</h3>
              <span>检查模型列表与向量生成</span>
            </div>
          </div>
          <div className="eval-detail-toolbar__actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => void handleCheckEmbeddingReadiness()}
              disabled={isCheckingEmbedding}
            >
              {isCheckingEmbedding ? "检查中..." : "检查 Embedding 网关"}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void handleRunEmbeddingSmokeTest()}
              disabled={isRunningEmbeddingSmokeTest}
            >
              {isRunningEmbeddingSmokeTest ? "执行中..." : "执行 Embedding 烟雾测试"}
            </button>
          </div>
          {embeddingReadiness ? (
            <div className="detail-grid">
              <div className="detail-item">
                <span>状态</span>
                <strong>{embeddingReadiness.status}</strong>
              </div>
              <div className="detail-item">
                <span>模型</span>
                <strong>{embeddingReadiness.model_name}</strong>
              </div>
              <div className="detail-item detail-item--full">
                <span>结果</span>
                <strong>{embeddingReadiness.message}</strong>
              </div>
              {embeddingReadiness.endpoint ? (
                <div className="detail-item detail-item--full">
                  <span>网关地址</span>
                  <strong>{embeddingReadiness.endpoint}</strong>
                </div>
              ) : null}
            </div>
          ) : null}
          {embeddingSmokeTest ? (
            <div className="detail-grid">
              <div className="detail-item">
                <span>延迟</span>
                <strong>{formatLatency(embeddingSmokeTest.latency_ms)}</strong>
              </div>
              <div className="detail-item">
                <span>向量维度</span>
                <strong>{embeddingSmokeTest.vector_dimension}</strong>
              </div>
              <div className="detail-item detail-item--full">
                <span>结果</span>
                <strong>{embeddingSmokeTest.message}</strong>
              </div>
            </div>
          ) : null}
        </article>
      </div>
    </section>
  );
}
