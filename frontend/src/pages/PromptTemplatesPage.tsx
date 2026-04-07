import { FormEvent, startTransition, useEffect, useState } from "react";

import {
  PromptTemplate,
  activatePromptTemplate,
  createPromptTemplate,
  listPromptTemplates,
} from "../api/prompts";


const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  active: "启用中",
};

export default function PromptTemplatesPage() {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [name, setName] = useState("默认政策问答 Prompt");
  const [template, setTemplate] = useState("你是差旅政策助手，请始终基于证据回答，并返回引用。");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function loadPrompts() {
    const nextPrompts = await listPromptTemplates();
    startTransition(() => {
      setPrompts(nextPrompts);
    });
  }

  useEffect(() => {
    void loadPrompts().catch((error: unknown) => {
      setErrorMessage(error instanceof Error ? error.message : "Prompt 列表加载失败。");
    });
  }, []);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !template.trim()) {
      setErrorMessage("请先填写完整的 Prompt 名称和模板内容。");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");
    try {
      await createPromptTemplate({
        name,
        taskType: "policy_answer",
        template,
      });
      await loadPrompts();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "Prompt 创建失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleActivate(promptTemplateId: string) {
    setIsSubmitting(true);
    setErrorMessage("");
    try {
      await activatePromptTemplate(promptTemplateId);
      await loadPrompts();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "Prompt 启用失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="panel panel--prompt">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">Prompt 管理</p>
          <h2>Prompt 模板</h2>
        </div>
        <span className="panel__tag">policy_answer</span>
      </div>
      <p className="panel__description">
        当前先管理政策问答主链路的 Prompt。每个任务类型同时只保留一个启用版本，
        方便回溯、对比和评测复盘。
      </p>
      <form className="prompt-form" onSubmit={(event) => void handleCreate(event)}>
        <div className="prompt-form__grid">
          <div className="field-group">
            <label htmlFor="prompt-name">Prompt 名称</label>
            <input
              id="prompt-name"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="field-group">
            <label htmlFor="prompt-task-type">任务类型</label>
            <input id="prompt-task-type" type="text" value="policy_answer" disabled readOnly />
          </div>
        </div>
        <div className="field-group">
          <label htmlFor="prompt-template">Prompt 模板内容</label>
          <textarea
            id="prompt-template"
            className="prompt-form__textarea"
            rows={6}
            value={template}
            onChange={(event) => setTemplate(event.target.value)}
          />
        </div>
        <div className="prompt-form__footer">
          <p>创建后默认是草稿，手动启用后才会进入问答主链路。</p>
          <button type="submit" disabled={isSubmitting}>
            创建 Prompt
          </button>
        </div>
      </form>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      <div className="data-card">
        <div className="data-card__header">
          <h3>版本列表</h3>
          <span>{prompts.length} 条记录</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>版本</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {prompts.length === 0 ? (
              <tr>
                <td colSpan={4} className="data-table__empty">
                  还没有 Prompt 版本，先创建一份模板。
                </td>
              </tr>
            ) : (
              prompts.map((prompt) => (
                <tr key={prompt.id}>
                  <td>{prompt.name}</td>
                  <td>v{prompt.version}</td>
                  <td>
                    <span className={`status-pill status-pill--${prompt.status}`}>
                      {STATUS_LABELS[prompt.status] ?? prompt.status}
                    </span>
                  </td>
                  <td className="prompt-actions">
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={isSubmitting || prompt.status === "active"}
                      onClick={() => void handleActivate(prompt.id)}
                    >
                      {prompt.status === "active" ? "当前启用" : "设为启用"}
                    </button>
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
