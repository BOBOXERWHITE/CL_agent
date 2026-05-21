import { FormEvent, startTransition, useEffect, useState } from "react";

import {
  AgentCheckpoint,
  AgentCoverage,
  AgentInterrupt,
  AgentProfileReport,
  AgentRun,
  AgentRunOutput,
  createAgentRun,
  listAgentRuns,
} from "../api/agents";
import { RetrievalTrace } from "../api/chat";
import { RuleResult } from "../api/reviews";
import ConfidenceBadge from "../components/ConfidenceBadge";
import RetrievalTraceDrawer from "../components/RetrievalTraceDrawer";
import RuleResultPanel from "../components/RuleResultPanel";
import RunTimeline from "../components/RunTimeline";

const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  needs_review: "待复核",
  rejected: "已拒绝",
};

const DEMO_TICKET = {
  ticket_id: "ticket-demo-001",
  expense_type: "hotel",
  city: "北京",
  amount: 1200,
  status: "pending_review",
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function readTrace(run: AgentRun): RetrievalTrace | null {
  const trace = run.output.orchestration_trace ?? run.output.retrieval_trace ?? null;
  if (!trace) {
    return null;
  }
  return {
    ...trace,
    agent_name: trace.agent_name ?? run.agent_name,
    route_name: trace.route_name ?? run.route_name,
    thread_id: trace.thread_id ?? run.thread_id,
    thread_status: run.thread_status ?? trace.thread_status,
    queue_name:
      (typeof run.output.queue_name === "string" && run.output.queue_name.trim().length > 0
        ? run.output.queue_name
        : null) ?? trace.queue_name,
    pending_interrupt: run.pending_interrupt ?? trace.pending_interrupt ?? null,
    latest_checkpoint: run.latest_checkpoint ?? trace.latest_checkpoint ?? null,
  };
}

function readReviewCaseId(output: AgentRunOutput): string | null {
  return typeof output.review_case_id === "string" && output.review_case_id.trim().length > 0
    ? output.review_case_id
    : null;
}

function readRuleResult(output: AgentRunOutput): RuleResult | undefined {
  return output.rule_result as RuleResult | undefined;
}

function formatCoverage(coverage?: AgentCoverage): string {
  const ratio = coverage?.coverage_ratio;
  if (typeof ratio !== "number" || Number.isNaN(ratio)) {
    return "N/A";
  }
  return `${Math.round(ratio * 100)}%`;
}

function readSpecialistPlan(output: AgentRunOutput): string[] {
  return readStringArray(output.specialist_plan);
}

function readProfileReports(output: AgentRunOutput): AgentProfileReport[] {
  if (!Array.isArray(output.profile_reports)) {
    return [];
  }
  return output.profile_reports as AgentProfileReport[];
}

function readPerDomainCoverage(output: AgentRunOutput): Array<[string, AgentCoverage]> {
  const value = output.coverage?.per_domain;
  if (!value || typeof value !== "object") {
    return [];
  }
  return Object.entries(value) as Array<[string, AgentCoverage]>;
}

function readInterrupt(run: AgentRun): AgentInterrupt | null {
  if (run.pending_interrupt && typeof run.pending_interrupt === "object") {
    return run.pending_interrupt;
  }
  return outputInterrupt(run.output);
}

function outputInterrupt(output: AgentRunOutput): AgentInterrupt | null {
  return output.interrupt ?? null;
}

function readLatestCheckpoint(run: AgentRun): AgentCheckpoint | null {
  return run.latest_checkpoint ?? null;
}

export default function AgentRunsPage() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [question, setQuestion] = useState("这张北京酒店报销单为什么还在排队？");
  const [threadId, setThreadId] = useState("");
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
      const createdRun = await createAgentRun({
        question,
        threadId: threadId.trim() || undefined,
        ticket: useDemoTicket ? DEMO_TICKET : undefined,
      });
      setThreadId(createdRun.thread_id);
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
          <p className="panel__eyebrow">Agent Workflow</p>
          <h2>Agent 运行记录</h2>
        </div>
        <span className="panel__tag">Router + Trace + Review</span>
      </div>
      <p className="panel__description">
        这里用于查看 router、specialist、coverage、guardrail 和人工复核状态。保留
        thread_id 后，可以持续在同一线程里追加多轮问题。
      </p>
      <form className="agent-run-form" onSubmit={(event) => void handleSubmit(event)}>
        <label htmlFor="agent-question">问题或工单描述</label>
        <textarea
          id="agent-question"
          rows={4}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：北京酒店 760 元含早，同时国内机票想订 business class，这张报销单是否合规？"
        />
        <div className="upload-form__grid">
          <div className="field-group">
            <label htmlFor="agent-thread-id">Thread ID</label>
            <input
              id="agent-thread-id"
              type="text"
              value={threadId}
              onChange={(event) => setThreadId(event.target.value)}
              placeholder="留空则自动创建新线程"
            />
          </div>
        </div>
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
            const output = run.output;
            const ruleResult = readRuleResult(output);
            const reviewCaseId = readReviewCaseId(output);
            const retrievalTrace = readTrace(run);
            const specialist =
              (typeof output.specialist === "string" && output.specialist.trim().length > 0
                ? output.specialist
                : null) ??
              retrievalTrace?.router?.specialist ??
              run.agent_name;
            const fallbackReason = retrievalTrace?.router?.fallback_reason;
            const coveredDimensions = readStringArray(output.coverage?.covered_dimensions);
            const missingDimensions = readStringArray(output.missing_dimensions);
            const guardrailEvents = Array.isArray(output.guardrail_events) ? output.guardrail_events : [];
            const interrupt = readInterrupt(run);
            const latestCheckpoint = readLatestCheckpoint(run);
            const resolution = output.resolution;
            const specialistPlan = readSpecialistPlan(output);
            const profileReports = readProfileReports(output);
            const perDomainCoverage = readPerDomainCoverage(output);

            return (
              <article key={run.id} className="data-card">
                <div className="data-card__header">
                  <div>
                    <h3>{run.agent_name}</h3>
                    <span>
                      {run.route_name} · {formatTimestamp(run.created_at)}
                    </span>
                  </div>
                  <div className="agent-run-header-meta">
                    <ConfidenceBadge confidence={run.confidence} />
                    <span className={`status-pill status-pill--${run.status}`}>
                      {STATUS_LABELS[run.status] ?? run.status}
                    </span>
                  </div>
                </div>
                <div className="data-card__actions">
                  <button type="button" onClick={() => setThreadId(run.thread_id)}>
                    复用此线程
                  </button>
                </div>

                <div className="agent-output-grid">
                  <article className="agent-output-card">
                    <span>运行结果</span>
                    <strong>{String(output.queue_name ?? "未返回队列")}</strong>
                    <p>{String(output.reason ?? output.answer ?? "暂无结果摘要")}</p>
                  </article>
                  <article className="agent-output-card">
                    <span>线程与审核</span>
                    <strong>{run.thread_id}</strong>
                    <p>
                      {(run.thread_status ?? (run.requires_human_review ? "awaiting_review" : "active")).toString()} · 运行编号 {run.id}
                    </p>
                  </article>
                  <article className="agent-output-card">
                    <span>Checkpoint</span>
                    <strong>{latestCheckpoint?.checkpoint_type ?? "未生成 checkpoint"}</strong>
                    <p>
                      {latestCheckpoint
                        ? `${latestCheckpoint.status} · ${formatTimestamp(latestCheckpoint.created_at)}`
                        : "当前运行尚未写入 checkpoint 摘要"}
                    </p>
                  </article>
                  <article className="agent-output-card">
                    <span>Policy Specialist</span>
                    <strong>{specialist}</strong>
                    <p>
                      路由域 {retrievalTrace?.router?.domain ?? "generic"}
                      {fallbackReason ? ` · ${fallbackReason}` : ""}
                    </p>
                  </article>
                  <article className="agent-output-card">
                    <span>Coverage</span>
                    <strong>{formatCoverage(output.coverage)}</strong>
                    <p>
                      已覆盖 {coveredDimensions.join("、") || "暂无"} · 缺失{" "}
                      {missingDimensions.join("、") || "无"}
                    </p>
                  </article>
                  <article className="agent-output-card">
                    <span>Guardrails</span>
                    <strong>{guardrailEvents.length > 0 ? `${guardrailEvents.length} 条事件` : "无拦截"}</strong>
                    <p>
                      {interrupt && typeof interrupt.reason === "string"
                        ? interrupt.reason
                        : "当前运行未触发中断。"}
                    </p>
                    {interrupt?.queue_name ? <small>{interrupt.queue_name}</small> : null}
                    {interrupt?.anomaly_code ? <small>{interrupt.anomaly_code}</small> : null}
                  </article>
                  <article className="agent-output-card">
                    <span>审核关联</span>
                    <strong>{reviewCaseId ?? "未进入队列"}</strong>
                    <p>
                      {resolution && typeof resolution.decision === "string"
                        ? `已处理：${resolution.decision}`
                        : "规则命中或低置信度会自动进入人工复核队列。"}
                    </p>
                  </article>
                </div>

                {specialistPlan.length > 0 ? (
                  <section className="agent-plan-section">
                    <div className="agent-plan-section__header">
                      <h4>Specialist Plan</h4>
                      <span>{specialistPlan.length} 个 specialist</span>
                    </div>
                    <div className="trace-card__chips">
                      {specialistPlan.map((item) => (
                        <span key={item} className="trace-card__pill">
                          {item}
                        </span>
                      ))}
                    </div>
                  </section>
                ) : null}

                {perDomainCoverage.length > 0 ? (
                  <section className="agent-plan-section">
                    <div className="agent-plan-section__header">
                      <h4>Per-Domain Coverage</h4>
                      <span>{perDomainCoverage.length} 个领域</span>
                    </div>
                    <div className="agent-domain-report-grid">
                      {perDomainCoverage.map(([domain, coverage]) => (
                        <article key={domain} className="agent-domain-report-card">
                          <span>{domain}</span>
                          <strong>{formatCoverage(coverage)}</strong>
                          <p>
                            已覆盖 {(coverage.covered_dimensions ?? []).join("、") || "暂无"} · 必答{" "}
                            {(coverage.required_dimensions ?? []).join("、") || "暂无"}
                          </p>
                        </article>
                      ))}
                    </div>
                  </section>
                ) : null}

                {profileReports.length > 0 ? (
                  <section className="agent-plan-section">
                    <div className="agent-plan-section__header">
                      <h4>Domain Reports</h4>
                      <span>逐域摘要</span>
                    </div>
                    <div className="agent-domain-report-grid">
                      {profileReports.map((report, index) => (
                        <article
                          key={`${report.domain ?? "domain"}-${index}`}
                          className="agent-domain-report-card"
                        >
                          <span>{report.label ?? report.domain ?? `domain-${index + 1}`}</span>
                          <strong>{report.primary_answer ?? "暂无结论"}</strong>
                          <p>
                            Coverage {formatCoverage(report.coverage)} · 缺失{" "}
                            {(report.missing_dimensions ?? []).join("、") || "无"}
                          </p>
                        </article>
                      ))}
                    </div>
                  </section>
                ) : null}

                <RuleResultPanel ruleResult={ruleResult} heading="规则判定" />
                {retrievalTrace ? <RetrievalTraceDrawer trace={retrievalTrace} /> : null}
                <RunTimeline timeline={run.timeline} toolCalls={run.tool_calls} />
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
