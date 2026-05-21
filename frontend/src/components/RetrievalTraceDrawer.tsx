import { useState } from "react";

import { RetrievalGuardrailEvent, RetrievalTrace, RetrievalTraceEvent } from "../api/chat";

interface RetrievalTraceDrawerProps {
  trace: RetrievalTrace;
}

function formatPercent(value?: number): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "N/A";
  }
  return `${Math.round(value * 100)}%`;
}

function formatGuardrailEvent(event: RetrievalGuardrailEvent, index: number): string {
  const decision = typeof event.decision === "string" ? event.decision : `event-${index + 1}`;
  const reason =
    typeof event.reason === "string" && event.reason.trim().length > 0
      ? event.reason
      : "No reason provided";
  const missingDimensions =
    Array.isArray(event.missing_dimensions) && event.missing_dimensions.length > 0
      ? `Missing: ${event.missing_dimensions.join(", ")}`
      : "";
  return [decision, reason, missingDimensions].filter(Boolean).join(" / ");
}

function formatTimestamp(value?: string): string {
  if (!value) {
    return "N/A";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatTraceEvent(event: RetrievalTraceEvent): string {
  return [event.category, event.name, event.status].filter(Boolean).join(" / ");
}

export default function RetrievalTraceDrawer({ trace }: RetrievalTraceDrawerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const selectedChunks = trace.selected_chunks ?? [];
  const rewriteRules = trace.rewrite_rules ?? [];
  const guardrailEvents = trace.guardrail_events ?? [];
  const coverage = trace.coverage;
  const specialistPlan = trace.specialist_plan ?? [];
  const plannedDomains = trace.router?.planned_domains ?? [];
  const perDomainCoverage = coverage?.per_domain
    ? Object.entries(coverage.per_domain)
    : [];
  const pendingInterrupt = trace.pending_interrupt;
  const latestCheckpoint = trace.latest_checkpoint;
  const timelineNodes = trace.timeline_nodes ?? [];
  const toolCalls = trace.tool_calls ?? [];
  const traceEvents = trace.trace_events ?? [];
  const cragRounds = trace.crag_rounds ?? [];

  return (
    <section className="trace-card">
      <button
        type="button"
        className="trace-card__toggle"
        onClick={() => setIsOpen((current) => !current)}
      >
        {isOpen ? "收起 Trace" : "查看 Trace"}
      </button>
      {isOpen ? (
        <div className="trace-card__body">
          <div className="trace-card__summary">
            {trace.mode ? (
              <div>
                <span>检索模式</span>
                <strong>{trace.mode}</strong>
              </div>
            ) : null}
            {trace.prompt_name ? (
              <div>
                <span>Prompt</span>
                <strong>
                  {trace.prompt_name}
                  {typeof trace.prompt_version === "number" ? ` v${trace.prompt_version}` : ""}
                </strong>
              </div>
            ) : null}
            {trace.model_name ? (
              <div>
                <span>模型</span>
                <strong>{trace.model_name}</strong>
              </div>
            ) : null}
            {trace.token_usage ? (
              <div>
                <span>Tokens</span>
                <strong>
                  输入 {trace.token_usage.input_tokens} / 输出 {trace.token_usage.output_tokens}
                </strong>
              </div>
            ) : null}
            {typeof trace.candidate_count === "number" && trace.candidate_count > 0 ? (
              <div>
                <span>候选块数</span>
                <strong>{trace.candidate_count}</strong>
              </div>
            ) : null}
            {trace.thread_id ? (
              <div>
                <span>Thread</span>
                <strong>{trace.thread_id}</strong>
              </div>
            ) : null}
            {trace.agent_name || trace.route_name ? (
              <div>
                <span>Execution</span>
                <strong>
                  {(trace.agent_name ?? "unknown").toString()}
                  {" / "}
                  {(trace.route_name ?? "unknown").toString()}
                </strong>
                {trace.thread_status ? <small>{trace.thread_status}</small> : null}
              </div>
            ) : null}
            {trace.queue_name ? (
              <div>
                <span>Queue</span>
                <strong>{trace.queue_name}</strong>
              </div>
            ) : null}
            {trace.router ? (
              <div>
                <span>Router</span>
                <strong>
                  {(trace.router.domain ?? "generic").toString()}
                  {" / "}
                  {(trace.router.specialist ?? "generic_policy_agent").toString()}
                </strong>
                {typeof trace.router.confidence === "number" ? (
                  <small>置信度 {formatPercent(trace.router.confidence)}</small>
                ) : null}
                {trace.router.fallback_reason ? <small>{trace.router.fallback_reason}</small> : null}
              </div>
            ) : null}
            {coverage ? (
              <div>
                <span>Coverage</span>
                <strong>{formatPercent(coverage.coverage_ratio)}</strong>
                <small>
                  已覆盖 {(coverage.covered_dimensions ?? []).join(", ") || "N/A"} / 必答维度{" "}
                  {(coverage.required_dimensions ?? []).join(", ") || "N/A"}
                </small>
              </div>
            ) : null}
            {latestCheckpoint ? (
              <div>
                <span>Checkpoint</span>
                <strong>{latestCheckpoint.checkpoint_type}</strong>
                <small>
                  {latestCheckpoint.status} / {formatTimestamp(latestCheckpoint.created_at)}
                </small>
              </div>
            ) : null}
          </div>

          {pendingInterrupt ? (
            <div className="trace-card__list">
              <h4>Pending Interrupt</h4>
              <ul>
                <li>
                  <strong>{pendingInterrupt.kind ?? "interrupt"}</strong>
                  <span>{pendingInterrupt.reason ?? "No reason provided"}</span>
                  <em>
                    {[pendingInterrupt.queue_name, pendingInterrupt.anomaly_code]
                      .filter(Boolean)
                      .join(" / ") || "N/A"}
                  </em>
                </li>
              </ul>
            </div>
          ) : null}

          {trace.original_query || trace.expanded_query ? (
            <div className="trace-card__list">
              <h4>Query</h4>
              <ul>
                {trace.original_query ? (
                  <li>
                    <strong>原始问题</strong>
                    <span>{trace.original_query}</span>
                  </li>
                ) : null}
                {trace.expanded_query ? (
                  <li>
                    <strong>改写问题</strong>
                    <span>{trace.expanded_query}</span>
                  </li>
                ) : null}
              </ul>
            </div>
          ) : null}

          {plannedDomains.length > 0 ? (
            <div className="trace-card__list">
              <h4>Planned Domains</h4>
              <div className="trace-card__chips">
                {plannedDomains.map((domain) => (
                  <span key={domain} className="trace-card__pill">
                    {domain}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {specialistPlan.length > 0 ? (
            <div className="trace-card__list">
              <h4>Specialist Plan</h4>
              <div className="trace-card__chips">
                {specialistPlan.map((specialist) => (
                  <span key={specialist} className="trace-card__pill">
                    {specialist}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {perDomainCoverage.length > 0 ? (
            <div className="trace-card__list">
              <h4>Per-Domain Coverage</h4>
              <ul>
                {perDomainCoverage.map(([domain, value]) => (
                  <li key={domain}>
                    <strong>{domain}</strong>
                    <span>Coverage {formatPercent(value.coverage_ratio)}</span>
                    <em>
                      已覆盖 {(value.covered_dimensions ?? []).join(", ") || "N/A"} / 必答{" "}
                      {(value.required_dimensions ?? []).join(", ") || "N/A"}
                    </em>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {rewriteRules.length > 0 ? (
            <div className="trace-card__list">
              <h4>Rewrite Rules</h4>
              <div className="trace-card__chips">
                {rewriteRules.map((rule) => (
                  <span key={rule} className="trace-card__pill">
                    {rule}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {guardrailEvents.length > 0 ? (
            <div className="trace-card__list">
              <h4>Guardrails</h4>
              <ul className="trace-card__event-list">
                {guardrailEvents.map((event, index) => (
                  <li key={`${index}-${formatGuardrailEvent(event, index)}`} className="trace-card__event-item">
                    {formatGuardrailEvent(event, index)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {timelineNodes.length > 0 ? (
            <div className="trace-card__list">
              <h4>Timeline Nodes</h4>
              <ul>
                {timelineNodes.map((node, index) => (
                  <li key={`${node.node_name}-${index}`}>
                    <strong>{node.node_name}</strong>
                    <span>{node.status}</span>
                    {node.detail ? <em>{node.detail}</em> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {toolCalls.length > 0 ? (
            <div className="trace-card__list">
              <h4>Tool Calls</h4>
              <ul>
                {toolCalls.map((toolCall, index) => (
                  <li key={`${toolCall.tool_name}-${index}`}>
                    <strong>{toolCall.tool_name}</strong>
                    <span>{toolCall.status}</span>
                    {typeof toolCall.latency_ms === "number" ? <em>{toolCall.latency_ms} ms</em> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {traceEvents.length > 0 ? (
            <div className="trace-card__list">
              <h4>Trace Events</h4>
              <ul>
                {traceEvents.map((event, index) => (
                  <li key={`${event.category}-${event.name}-${index}`}>
                    <strong>{event.name}</strong>
                    <span>{formatTraceEvent(event)}</span>
                    <em>{event.detail}</em>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {cragRounds.length > 0 ? (
            <div className="trace-card__list">
              <h4>CRAG Rounds</h4>
              <ul>
                {cragRounds.map((round) => {
                  const covered = round.covered_aspects ?? [];
                  const missing = round.missing_aspects ?? [];
                  const suggested = round.suggested_queries ?? [];
                  const sufficiencyPct = `${Math.round(round.sufficiency_score * 100)}%`;
                  const action = round.triggered_re_retrieval
                    ? `补检索 +${round.new_chunks_added ?? 0} chunk`
                    : "已达充分阈值";
                  return (
                    <li key={`crag-round-${round.round_index}`}>
                      <strong>
                        #{round.round_index} · sufficiency {sufficiencyPct} · {action}
                      </strong>
                      {missing.length > 0 ? (
                        <span>缺失：{missing.join("；")}</span>
                      ) : (
                        <span>缺失：无</span>
                      )}
                      {suggested.length > 0 ? (
                        <span>建议查询：{suggested.join("；")}</span>
                      ) : null}
                      {covered.length > 0 ? (
                        <em>已覆盖：{covered.join("；")}</em>
                      ) : null}
                      {round.reasoning ? <em>理由：{round.reasoning}</em> : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

          {selectedChunks.length > 0 ? (
            <div className="trace-card__list">
              <h4>Selected Chunks</h4>
              <ul>
                {selectedChunks.map((chunk) => (
                  <li key={chunk.chunk_id}>
                    <strong>{chunk.document_title}</strong>
                    <span>{chunk.chunk_id}</span>
                    <em>命中分数 {Math.round(chunk.score * 100)}%</em>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
