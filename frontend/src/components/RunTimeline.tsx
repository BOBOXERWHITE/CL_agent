import { AgentTimelineStep, AgentToolCall } from "../api/agents";


interface RunTimelineProps {
  timeline: AgentTimelineStep[];
  toolCalls: AgentToolCall[];
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export default function RunTimeline({ timeline, toolCalls }: RunTimelineProps) {
  return (
    <div className="timeline-layout">
      <section>
        <h4>状态时间线</h4>
        <div className="timeline-list">
          {timeline.map((step) => (
            <article key={`${step.node_name}-${step.timestamp}`} className="timeline-item">
              <header>
                <strong>{step.node_name}</strong>
                <span className={`status-pill status-pill--${step.status}`}>{step.status}</span>
              </header>
              <p>{step.detail}</p>
              <time dateTime={step.timestamp}>{formatTimestamp(step.timestamp)}</time>
            </article>
          ))}
        </div>
      </section>
      <section>
        <h4>工具调用</h4>
        <div className="tool-call-grid">
          {toolCalls.length === 0 ? (
            <article className="tool-call-card">
              <strong>当前运行未调用工具</strong>
              <p>这条执行流主要依赖检索或规则判断。</p>
            </article>
          ) : (
            toolCalls.map((toolCall) => (
              <article key={`${toolCall.tool_name}-${toolCall.latency_ms}`} className="tool-call-card">
                <header>
                  <strong>{toolCall.tool_name}</strong>
                  <span>{toolCall.latency_ms} ms</span>
                </header>
                <p>状态：{toolCall.status}</p>
                <p>{JSON.stringify(toolCall.output_payload)}</p>
              </article>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
