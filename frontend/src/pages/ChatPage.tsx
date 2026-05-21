import { FormEvent, useEffect, useState } from "react";

import { ChatAnswer, askPolicyQuestion } from "../api/chat";
import CitationPanel from "../components/CitationPanel";
import ConfidenceBadge from "../components/ConfidenceBadge";
import RetrievalTraceDrawer from "../components/RetrievalTraceDrawer";

interface ChatPageProps {
  defaultTenantId?: string;
  defaultCustomerId?: string;
}

// One row in the rendered conversation. ``user`` rows carry only the
// question text; ``assistant`` rows carry the full ChatAnswer so we can
// keep showing per-turn citations / confidence / trace below each reply.
interface ConversationTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
  answer?: ChatAnswer;
}

function newTurnId(prefix: "user" | "assistant"): string {
  // ``Date.now()`` is sufficient to keep React keys stable within a
  // single conversation; prefix avoids cross-role collisions.
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function ChatPage({
  defaultTenantId = "演示租户",
  defaultCustomerId = "演示客户",
}: ChatPageProps) {
  const [tenantId, setTenantId] = useState(defaultTenantId);
  const [customerId, setCustomerId] = useState(defaultCustomerId);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setTenantId(defaultTenantId);
  }, [defaultTenantId]);

  useEffect(() => {
    setCustomerId(defaultCustomerId);
  }, [defaultCustomerId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion) {
      setErrorMessage("请先输入一个政策问题。");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");

    // Optimistically render the user turn so the UI feels responsive
    // even before the LLM responds.
    const userTurn: ConversationTurn = {
      id: newTurnId("user"),
      role: "user",
      text: nextQuestion,
    };
    setTurns((current) => [...current, userTurn]);
    setQuestion("");

    try {
      const response = await askPolicyQuestion({
        question: nextQuestion,
        tenantId,
        customerId,
        threadId: activeThreadId ?? undefined,
      });
      setActiveThreadId(response.thread_id);
      setTurns((current) => [
        ...current,
        {
          id: newTurnId("assistant"),
          role: "assistant",
          text: response.answer,
          answer: response,
        },
      ]);
    } catch (error: unknown) {
      // Roll the optimistic user turn back so the user can edit + retry.
      setTurns((current) => current.filter((turn) => turn.id !== userTurn.id));
      setQuestion(nextQuestion);
      setErrorMessage(error instanceof Error ? error.message : "问答请求失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleNewSession() {
    setTurns([]);
    setActiveThreadId(null);
    setQuestion("");
    setErrorMessage("");
  }

  return (
    <section className="panel panel--chat">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">政策问答</p>
          <h2>多轮对话 · 证据优先</h2>
        </div>
        <span className="panel__tag">证据优先</span>
      </div>
      <p className="panel__description">
        适合做政策核对、口径确认和制度问询。对话会持续累积上下文，可以用"那广州呢？"这样的省略式追问。每轮答复都会展示引用依据、检索 Trace 和置信度。
      </p>

      <form className="question-form" onSubmit={(event) => void handleSubmit(event)}>
        <div className="upload-form__grid">
          <div className="field-group">
            <label htmlFor="chat-tenant-id">租户 ID</label>
            <input
              id="chat-tenant-id"
              name="tenantId"
              type="text"
              value={tenantId}
              onChange={(event) => setTenantId(event.target.value)}
            />
          </div>
          <div className="field-group">
            <label htmlFor="chat-customer-id">客户 ID</label>
            <input
              id="chat-customer-id"
              name="customerId"
              type="text"
              value={customerId}
              onChange={(event) => setCustomerId(event.target.value)}
            />
          </div>
        </div>
        <p className="upload-form__caption">
          这里的租户和客户必须与知识入库时保持一致，否则检索会因为隔离条件不匹配而拿不到证据。
        </p>

        <div className="chat-toolbar">
          {activeThreadId ? (
            <p className="panel__meta">
              当前 thread: <strong>{activeThreadId}</strong>
            </p>
          ) : (
            <p className="panel__meta">尚未开启会话，提交后将自动建立 thread。</p>
          )}
          <button
            type="button"
            className="secondary-button"
            onClick={handleNewSession}
            disabled={isSubmitting || (turns.length === 0 && !activeThreadId)}
            title="清空当前对话并开启全新 thread；后端会创建新的 ChatSession。"
          >
            新建会话
          </button>
        </div>

        <label htmlFor="policy-question">政策问题</label>
        <textarea
          id="policy-question"
          rows={4}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={
            turns.length === 0
              ? "例如：北京 L2 普通员工酒店报销标准是多少？"
              : "继续追问，例如：那广州呢？"
          }
        />
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "提交中..." : "提交问答"}
        </button>
      </form>

      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}

      {turns.length > 0 ? (
        <div className="conversation">
          {turns.map((turn) =>
            turn.role === "user" ? (
              <article
                key={turn.id}
                className="conversation__turn conversation__turn--user"
              >
                <header className="conversation__role">你</header>
                <p className="conversation__body">{turn.text}</p>
              </article>
            ) : (
              <article
                key={turn.id}
                className="conversation__turn conversation__turn--assistant"
              >
                <header className="conversation__role">
                  <span>政策助手</span>
                  {turn.answer ? (
                    <ConfidenceBadge confidence={turn.answer.confidence} />
                  ) : null}
                </header>
                <p className="conversation__body">{turn.text}</p>
                {turn.answer ? (
                  <>
                    <CitationPanel citations={turn.answer.citations} />
                    {turn.answer.retrieval_trace ? (
                      <RetrievalTraceDrawer trace={turn.answer.retrieval_trace} />
                    ) : null}
                  </>
                ) : null}
              </article>
            ),
          )}
        </div>
      ) : null}
    </section>
  );
}
