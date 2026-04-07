import { FormEvent, startTransition, useEffect, useState } from "react";

import { AgentRun, createAgentRun, listAgentRuns } from "../api/agents";
import { RuleResult } from "../api/reviews";
import ConfidenceBadge from "../components/ConfidenceBadge";
import RuleResultPanel from "../components/RuleResultPanel";
import RunTimeline from "../components/RunTimeline";

const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  needs_review: "待复核",
};

const DEMO_TICKET = {
  ticket_id: "ticket-demo-001",
  expense_type: "hotel",
  city: "北京",
  amount: 1200,
  status: "pending_review",
};

export default function AgentRunsPage() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [question, setQuestion] = useState("这张北京酒店报销单为什么还在排队？");
  const [useDemoTicket, setUseDemoTicket] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function loadRuns() {
    const nextRuns = await listAgentRuns();
    startTransition(() => {
      setRuns(nextRuns);
    });
  }

  useEffect(() => {
    void loadRuns().catch((error: unknown) => {
      setErrorMessage(error instanceof Error ? error.message : "Agent 运行记录加载失败。");
    });
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) {
      setErrorMessage("请先输入一条问题或工单说明。");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");
    try {
      await createAgentRun({
        question,
        ticket: useDemoTicket ? DEMO_TICKET : undefined,
      });
      await loadRuns();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "Agent 运行失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="panel panel--agent-runs">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">Agent 工作流</p>
          <h2>Agent 运行记录</h2>
        </div>
        <span className="panel__tag">Router + Timeline</span>
      </div>
      <p className="panel__description">
        这一步用于查看 Query Router、工具调用、规则结论和人工复核检查点。默认附带一条示例工单，便于直接验证分流链路。
      </p>
      <form className="agent-run-form" onSubmit={(event) => void handleSubmit(event)}>
        <label htmlFor="agent-question">问题或工单描述</label>
        <textarea
          id="agent-question"
          rows={4}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：这张北京酒店报销单为什么还在排队？"
        />
        <label className="agent-run-form__toggle">
          <input
            type="checkbox"
            checked={useDemoTicket}
            onChange={(event) => setUseDemoTicket(event.target.checked)}
          />
          <span>附带示例工单 payload</span>
        </label>
        <button type="submit" disabled={isSubmitting}>
          运行 Agent
        </button>
      </form>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      <div className="agent-run-grid">
        {runs.length === 0 ? (
          <article className="data-card">
            <div className="data-card__header">
              <h3>最近运行</h3>
            </div>
            <p className="data-table__empty">还没有 Agent 运行记录，先执行一条工单分流。</p>
          </article>
        ) : (
          runs.map((run) => {
            const ruleResult = run.output.rule_result as RuleResult | undefined;
            const reviewCaseId = run.output.review_case_id;
            return (
              <article key={run.id} className="data-card">
                <div className="data-card__header">
                  <div>
                    <h3>{run.agent_name}</h3>
                    <span>{run.route_name}</span>
                  </div>
                  <div className="agent-run-header-meta">
                    <ConfidenceBadge confidence={run.confidence} />
                    <span className={`status-pill status-pill--${run.status}`}>
                      {STATUS_LABELS[run.status] ?? run.status}
                    </span>
                  </div>
                </div>
                <div className="agent-output-grid">
                  <article className="agent-output-card">
                    <span>分流结果</span>
                    <strong>{String(run.output.queue_name ?? "未返回队列")}</strong>
                    <p>{String(run.output.reason ?? run.output.answer ?? "暂无结果摘要")}</p>
                  </article>
                  <article className="agent-output-card">
                    <span>人工复核</span>
                    <strong>{run.requires_human_review ? "需要" : "不需要"}</strong>
                    <p>运行编号：{run.id}</p>
                  </article>
                  <article className="agent-output-card">
                    <span>审核关联</span>
                    <strong>{typeof reviewCaseId === "string" ? reviewCaseId : "未进入队列"}</strong>
                    <p>规则命中和低置信度会自动进入人工复核队列。</p>
                  </article>
                </div>
                <RuleResultPanel ruleResult={ruleResult} heading="规则判定" />
                <RunTimeline timeline={run.timeline} toolCalls={run.tool_calls} />
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
