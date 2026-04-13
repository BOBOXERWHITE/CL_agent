import { FormEvent, useEffect, useState } from "react";

import { ChatAnswer, askPolicyQuestion } from "../api/chat";
import CitationPanel from "../components/CitationPanel";
import ConfidenceBadge from "../components/ConfidenceBadge";
import RetrievalTraceDrawer from "../components/RetrievalTraceDrawer";

interface ChatPageProps {
  defaultTenantId?: string;
  defaultCustomerId?: string;
}

export default function ChatPage({
  defaultTenantId = "演示租户",
  defaultCustomerId = "演示客户",
}: ChatPageProps) {
  const [tenantId, setTenantId] = useState(defaultTenantId);
  const [customerId, setCustomerId] = useState(defaultCustomerId);
  const [question, setQuestion] = useState("");
  const [chatAnswer, setChatAnswer] = useState<ChatAnswer | null>(null);
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
    try {
      const response = await askPolicyQuestion({
        question: nextQuestion,
        tenantId,
        customerId,
        sessionId: chatAnswer?.session_id,
      });
      setChatAnswer(response);
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "问答请求失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="panel panel--chat">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">政策问答</p>
          <h2>先看依据，再看结论</h2>
        </div>
        <span className="panel__tag">证据优先</span>
      </div>
      <p className="panel__description">
        适合做政策核对、口径确认和制度问询。当前版本会展示引用依据、检索 Trace 和置信度，便于你边提问边判断结果是否可信。
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
        <p className="upload-form__caption">这里的租户和客户必须与知识入库时保持一致，否则检索会因为隔离条件不匹配而拿不到证据。</p>
        <label htmlFor="policy-question">政策问题</label>
        <textarea
          id="policy-question"
          rows={5}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：我可以预订 business class 吗？"
        />
        <button type="submit" disabled={isSubmitting}>
          提交问答
        </button>
      </form>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      {chatAnswer ? (
        <div className="answer-card">
          <div className="answer-card__header">
            <h3>当前答复</h3>
            <ConfidenceBadge confidence={chatAnswer.confidence} />
          </div>
          <p className="answer-card__body">{chatAnswer.answer}</p>
          <CitationPanel citations={chatAnswer.citations} />
          {chatAnswer.retrieval_trace ? <RetrievalTraceDrawer trace={chatAnswer.retrieval_trace} /> : null}
        </div>
      ) : null}
    </section>
  );
}
