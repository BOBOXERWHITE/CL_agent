import { startTransition, useEffect, useState } from "react";

import { getMonitoringOverview, type MonitoringOverview } from "../api/monitoring";

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function MonitoringPage() {
  const [overview, setOverview] = useState<MonitoringOverview | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function loadOverview() {
    setIsRefreshing(true);
    setErrorMessage("");
    try {
      const nextOverview = await getMonitoringOverview();
      startTransition(() => {
        setOverview(nextOverview);
      });
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "监控概览加载失败。");
    } finally {
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    void loadOverview();
  }, []);

  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">系统总览</p>
          <h2>监控面板</h2>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => void loadOverview()}
          disabled={isRefreshing}
        >
          {isRefreshing ? "刷新中..." : "刷新数据"}
        </button>
      </div>
      <p className="panel__description">
        面向运营和值班排查的业务概览。这里展示知识库、问答、评测、Agent 和请求运行的聚合视图，
        不直接解析 Prometheus 原始指标。
      </p>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      {overview ? (
        <>
          <div className="overview-grid">
            <article className="overview-card">
              <span>知识库概览</span>
              <strong>{overview.knowledge_summary.document_total}</strong>
              <p>
                已完成 {overview.knowledge_summary.completed_total}，失败 {overview.knowledge_summary.failed_total}
              </p>
            </article>
            <article className="overview-card">
              <span>待重建文档</span>
              <strong>{overview.knowledge_summary.pending_reindex_total}</strong>
              <p>向量配置已变化，需要重新生成向量的文档数量。</p>
            </article>
            <article className="overview-card">
              <span>问答会话</span>
              <strong>{overview.chat_summary.session_total}</strong>
              <p>累计消息 {overview.chat_summary.message_total} 条。</p>
            </article>
            <article className="overview-card">
              <span>人工复核</span>
              <strong>{overview.review_summary.open_total}</strong>
              <p>当前待处理审核案例数量。</p>
            </article>
            <article className="overview-card">
              <span>近 24 小时 Agent</span>
              <strong>{overview.agent_summary.last_24h_total}</strong>
              <p>最近 24 小时内新建的 Agent 运行数量。</p>
            </article>
            <article className="overview-card">
              <span>近 24 小时评测</span>
              <strong>{overview.eval_summary.last_24h_total}</strong>
              <p>最近 24 小时内新建的评测运行数量。</p>
            </article>
            <article className="overview-card">
              <span>近 1 小时请求</span>
              <strong>{overview.request_summary.last_hour_total}</strong>
              <p>
                错误 {overview.request_summary.last_hour_error_total}，P95 延迟{" "}
                {overview.request_summary.last_hour_p95_latency_ms} ms
              </p>
            </article>
          </div>

          <div className="activity-grid">
            <article className="data-card">
              <div className="data-card__header">
                <div>
                  <h3>最近失败请求</h3>
                  <span>{overview.recent_activity.recent_failed_requests.length} 条</span>
                </div>
              </div>
              {overview.recent_activity.recent_failed_requests.length === 0 ? (
                <p className="data-table__empty">最近没有失败请求。</p>
              ) : (
                <ul className="activity-list">
                  {overview.recent_activity.recent_failed_requests.map((item) => (
                    <li key={item.id} className="activity-list__item">
                      <div>
                        <strong>{item.path}</strong>
                        <p>{item.error_message ?? "无错误摘要"}</p>
                      </div>
                      <span>
                        {item.status_code} / {formatDateTime(item.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </article>

            <article className="data-card">
              <div className="data-card__header">
                <div>
                  <h3>最近评测</h3>
                  <span>{overview.eval_summary.last_24h_total} 次 / 24 小时</span>
                </div>
              </div>
              {overview.recent_activity.recent_eval_runs.length === 0 ? (
                <p className="data-table__empty">最近没有评测运行。</p>
              ) : (
                <ul className="activity-list">
                  {overview.recent_activity.recent_eval_runs.map((item) => (
                    <li key={item.id} className="activity-list__item">
                      <div>
                        <strong>{item.dataset_name}</strong>
                        <p>{item.status}</p>
                      </div>
                      <span>{formatDateTime(item.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </article>

            <article className="data-card">
              <div className="data-card__header">
                <div>
                  <h3>最近 Agent 运行</h3>
                  <span>{overview.agent_summary.last_24h_total} 次 / 24 小时</span>
                </div>
              </div>
              {overview.recent_activity.recent_agent_runs.length === 0 ? (
                <p className="data-table__empty">最近没有 Agent 运行。</p>
              ) : (
                <ul className="activity-list">
                  {overview.recent_activity.recent_agent_runs.map((item) => (
                    <li key={item.id} className="activity-list__item">
                      <div>
                        <strong>{item.agent_name}</strong>
                        <p>{item.status}</p>
                      </div>
                      <span>{formatDateTime(item.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          </div>
        </>
      ) : (
        <div className="data-card">
          <p className="data-table__empty">正在加载监控概览...</p>
        </div>
      )}
    </section>
  );
}
