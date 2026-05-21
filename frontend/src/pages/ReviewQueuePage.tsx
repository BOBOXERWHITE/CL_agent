import { startTransition, useEffect, useState } from "react";

import { resumeAgentRun } from "../api/agents";
import { RetrievalTraceEvent } from "../api/chat";
import { ReviewCase, ReviewCheckpoint, ReviewInterrupt, RuleResult, listReviewCases } from "../api/reviews";
import ConfidenceBadge from "../components/ConfidenceBadge";
import RuleResultPanel from "../components/RuleResultPanel";

const STATUS_LABELS: Record<string, string> = {
  open: "待处理",
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function readQuestion(payload: Record<string, unknown>): string {
  const question = payload.question;
  return typeof question === "string" && question.trim() ? question : "暂无问题摘要";
}

function readAgentRunId(reviewCase: ReviewCase): string | null {
  if (typeof reviewCase.agent_run_id === "string" && reviewCase.agent_run_id.trim()) {
    return reviewCase.agent_run_id;
  }
  const legacyRunId = reviewCase.payload.agent_run_id;
  return typeof legacyRunId === "string" && legacyRunId.trim() ? legacyRunId : null;
}

function readThreadId(reviewCase: ReviewCase): string | null {
  if (typeof reviewCase.thread_id === "string" && reviewCase.thread_id.trim()) {
    return reviewCase.thread_id;
  }
  const legacyThreadId = reviewCase.payload.thread_id;
  return typeof legacyThreadId === "string" && legacyThreadId.trim() ? legacyThreadId : null;
}

function readPendingInterrupt(reviewCase: ReviewCase): ReviewInterrupt | null {
  if (reviewCase.pending_interrupt && typeof reviewCase.pending_interrupt === "object") {
    return reviewCase.pending_interrupt;
  }
  const legacyInterrupt = reviewCase.payload.interrupt;
  return legacyInterrupt && typeof legacyInterrupt === "object"
    ? (legacyInterrupt as ReviewInterrupt)
    : null;
}

function readLatestCheckpoint(reviewCase: ReviewCase): ReviewCheckpoint | null {
  return reviewCase.latest_checkpoint ?? null;
}

function readTraceEvents(reviewCase: ReviewCase): RetrievalTraceEvent[] {
  if (!Array.isArray(reviewCase.trace_events)) {
    return [];
  }
  return reviewCase.trace_events as RetrievalTraceEvent[];
}

export default function ReviewQueuePage() {
  const [cases, setCases] = useState<ReviewCase[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [busyCaseId, setBusyCaseId] = useState<string | null>(null);
  const [editingCaseId, setEditingCaseId] = useState<string | null>(null);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [editedAnswerDrafts, setEditedAnswerDrafts] = useState<Record<string, string>>({});

  async function loadCases() {
    const nextCases = await listReviewCases();
    startTransition(() => {
      setCases(nextCases);
    });
  }

  useEffect(() => {
    void loadCases().catch((error: unknown) => {
      setErrorMessage(error instanceof Error ? error.message : "人工复核队列加载失败。");
    });
  }, []);

  async function handleDecision(reviewCase: ReviewCase, decision: "approve" | "edit" | "reject") {
    const agentRunId = readAgentRunId(reviewCase);
    if (!agentRunId) {
      setErrorMessage("当前案例未关联 agent run，暂不支持在这里直接处理。");
      return;
    }

    const note = noteDrafts[reviewCase.id] ?? "";
    const editedAnswer = editedAnswerDrafts[reviewCase.id] ?? "";
    if (decision === "edit" && !editedAnswer.trim()) {
      setErrorMessage("编辑结论时必须填写修订后的答案。");
      return;
    }

    setBusyCaseId(reviewCase.id);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      await resumeAgentRun(agentRunId, {
        decision,
        note,
        editedAnswer: decision === "edit" ? editedAnswer : undefined,
      });
      setSuccessMessage(`案例 ${reviewCase.id} 已提交 ${decision}。`);
      setEditingCaseId((current) => (current === reviewCase.id ? null : current));
      await loadCases();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "人工复核处理失败。");
    } finally {
      setBusyCaseId(null);
    }
  }

  return (
    <section className="panel panel--reviews">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">人工复核</p>
          <h2>人工复核队列</h2>
        </div>
        <span className="panel__tag">Review Queue</span>
      </div>
      <p className="panel__description">
        这里集中展示低置信度问答、规则拦截工单和需要人工接管的 Agent 运行结果，便于最后统一做验收和复盘。
      </p>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      {successMessage ? <p className="panel__success">{successMessage}</p> : null}
      <div className="review-grid">
        {cases.length === 0 ? (
          <article className="data-card">
            <div className="data-card__header">
              <h3>待处理案例</h3>
            </div>
            <p className="data-table__empty">当前没有待处理的人工复核案例。</p>
          </article>
        ) : (
          cases.map((reviewCase) => {
            const ruleResult = reviewCase.rule_result as RuleResult | undefined;
            const agentRunId = readAgentRunId(reviewCase);
            const threadId = readThreadId(reviewCase);
            const pendingInterrupt = readPendingInterrupt(reviewCase);
            const latestCheckpoint = readLatestCheckpoint(reviewCase);
            const traceEvents = readTraceEvents(reviewCase);
            const isEditing = editingCaseId === reviewCase.id;
            const isBusy = busyCaseId === reviewCase.id;

            return (
              <article key={reviewCase.id} className="data-card review-card">
                <div className="data-card__header">
                  <div>
                    <h3>{reviewCase.id}</h3>
                    <span>{formatTimestamp(reviewCase.created_at)}</span>
                  </div>
                  <span className={`status-pill status-pill--${reviewCase.status}`}>
                    {STATUS_LABELS[reviewCase.status] ?? reviewCase.status}
                  </span>
                </div>
                <div className="review-meta-grid">
                  <article className="review-meta-card">
                    <span>案例来源</span>
                    <strong>{reviewCase.source}</strong>
                    <p>{readQuestion(reviewCase.payload)}</p>
                  </article>
                  <article className="review-meta-card">
                    <span>置信度</span>
                    <ConfidenceBadge confidence={reviewCase.confidence} />
                    <p>{reviewCase.reason}</p>
                  </article>
                  <article className="review-meta-card">
                    <span>审核上下文</span>
                    <strong>{agentRunId ?? "未关联 agent run"}</strong>
                    <p>Thread {threadId ?? "暂无"} · 租户 {reviewCase.tenant_id}</p>
                  </article>
                  <article className="review-meta-card">
                    <span>Pending Interrupt</span>
                    <strong>{pendingInterrupt?.reason ?? "未提供中断原因"}</strong>
                    <p>
                      {pendingInterrupt?.queue_name ?? "无队列信息"}
                      {pendingInterrupt?.anomaly_code ? ` · ${pendingInterrupt.anomaly_code}` : ""}
                    </p>
                  </article>
                  <article className="review-meta-card">
                    <span>Checkpoint</span>
                    <strong>{latestCheckpoint?.checkpoint_type ?? "未生成 checkpoint"}</strong>
                    <p>
                      {latestCheckpoint
                        ? `${latestCheckpoint.status} · ${formatTimestamp(latestCheckpoint.created_at)}`
                        : "当前案例暂无 checkpoint 摘要"}
                    </p>
                  </article>
                </div>
                {traceEvents.length > 0 ? (
                  <section className="agent-plan-section">
                    <div className="agent-plan-section__header">
                      <h4>Trace 事件</h4>
                      <span>{traceEvents.length} 条</span>
                    </div>
                    <div className="agent-domain-report-grid">
                      {traceEvents.slice(0, 5).map((event, index) => (
                        <article
                          key={`${event.category}-${event.name}-${index}`}
                          className="agent-domain-report-card"
                        >
                          <span>{event.name}</span>
                          <strong>{event.category}</strong>
                          <p>
                            {event.detail} · {event.status}
                          </p>
                        </article>
                      ))}
                    </div>
                  </section>
                ) : null}
                <RuleResultPanel ruleResult={ruleResult} />
                <div className="review-actions">
                  <label htmlFor={`review-note-${reviewCase.id}`}>审核备注</label>
                  <textarea
                    id={`review-note-${reviewCase.id}`}
                    rows={3}
                    value={noteDrafts[reviewCase.id] ?? ""}
                    onChange={(event) =>
                      setNoteDrafts((current) => ({
                        ...current,
                        [reviewCase.id]: event.target.value,
                      }))
                    }
                    placeholder="记录审批依据、补充说明或驳回原因"
                  />
                  <div className="data-card__actions">
                    <button
                      type="button"
                      disabled={isBusy || !agentRunId}
                      onClick={() => void handleDecision(reviewCase, "approve")}
                    >
                      通过
                    </button>
                    <button
                      type="button"
                      disabled={isBusy || !agentRunId}
                      onClick={() => void handleDecision(reviewCase, "reject")}
                    >
                      驳回
                    </button>
                    <button
                      type="button"
                      disabled={!agentRunId}
                      onClick={() => setEditingCaseId((current) => (current === reviewCase.id ? null : reviewCase.id))}
                    >
                      {isEditing ? "收起编辑" : "编辑结论"}
                    </button>
                  </div>
                  {isEditing ? (
                    <div className="review-actions__grid">
                      <label htmlFor={`review-answer-${reviewCase.id}`}>修订后的答案</label>
                      <textarea
                        id={`review-answer-${reviewCase.id}`}
                        rows={5}
                        value={editedAnswerDrafts[reviewCase.id] ?? ""}
                        onChange={(event) =>
                          setEditedAnswerDrafts((current) => ({
                            ...current,
                            [reviewCase.id]: event.target.value,
                          }))
                        }
                        placeholder="填写人工修订后的最终答案"
                      />
                      <div className="data-card__actions">
                        <button
                          type="button"
                          disabled={isBusy || !agentRunId}
                          onClick={() => void handleDecision(reviewCase, "edit")}
                        >
                          提交修订
                        </button>
                      </div>
                    </div>
                  ) : null}
                  {!agentRunId ? (
                    <p className="review-card__hint">该案例未关联 agent run，目前只能在后端或后续专用流程中处理。</p>
                  ) : null}
                </div>
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
