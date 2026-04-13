import { FormEvent, useEffect, useState } from "react";

import {
  getRuntimeLogDetail,
  listRuntimeLogs,
  type RuntimeLogDetail,
  type RuntimeLogFilters,
  type RuntimeLogItem,
} from "../api/logs";

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const DEFAULT_FILTERS: RuntimeLogFilters = {
  path: "",
  statusCode: "",
  requestId: "",
  tenantId: "",
  sessionId: "",
  dateFrom: "",
  dateTo: "",
  limit: 50,
};

export default function RuntimeLogsPage() {
  const [filters, setFilters] = useState<RuntimeLogFilters>(DEFAULT_FILTERS);
  const [items, setItems] = useState<RuntimeLogItem[]>([]);
  const [selectedLog, setSelectedLog] = useState<RuntimeLogDetail | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);

  async function loadLogs(nextFilters: RuntimeLogFilters = filters) {
    setIsLoading(true);
    setErrorMessage("");
    try {
      const nextItems = await listRuntimeLogs(nextFilters);
      setItems(nextItems);
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "运行日志加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadLogs(DEFAULT_FILTERS);
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await loadLogs(filters);
  }

  async function openDetail(runtimeLogId: string) {
    setIsLoadingDetail(true);
    setErrorMessage("");
    try {
      const detail = await getRuntimeLogDetail(runtimeLogId);
      setSelectedLog(detail);
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "运行日志详情加载失败。");
    } finally {
      setIsLoadingDetail(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">请求审计</p>
          <h2>运行日志</h2>
        </div>
        <span className="panel__tag">admin / operator</span>
      </div>
      <p className="panel__description">
        这里保留请求级运行日志，便于按路径、租户、会话和请求编号排查问题。stdout
        结构化日志继续保留，这个面板只做后台查询。
      </p>

      <form className="log-filter-grid" onSubmit={(event) => void handleSubmit(event)}>
        <div className="field-group">
          <label htmlFor="runtime-log-path">请求路径</label>
          <input
            id="runtime-log-path"
            value={filters.path ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, path: event.target.value }))}
          />
        </div>
        <div className="field-group">
          <label htmlFor="runtime-log-status">状态码</label>
          <input
            id="runtime-log-status"
            value={filters.statusCode ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, statusCode: event.target.value }))}
          />
        </div>
        <div className="field-group">
          <label htmlFor="runtime-log-request-id">请求 ID</label>
          <input
            id="runtime-log-request-id"
            value={filters.requestId ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, requestId: event.target.value }))}
          />
        </div>
        <div className="field-group">
          <label htmlFor="runtime-log-tenant-id">租户 ID</label>
          <input
            id="runtime-log-tenant-id"
            value={filters.tenantId ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, tenantId: event.target.value }))}
          />
        </div>
        <div className="field-group">
          <label htmlFor="runtime-log-session-id">会话 ID</label>
          <input
            id="runtime-log-session-id"
            value={filters.sessionId ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, sessionId: event.target.value }))}
          />
        </div>
        <div className="field-group">
          <label htmlFor="runtime-log-limit">返回条数</label>
          <input
            id="runtime-log-limit"
            type="number"
            min={1}
            max={200}
            value={String(filters.limit ?? 50)}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                limit: Number(event.target.value || 50),
              }))
            }
          />
        </div>
        <div className="field-group">
          <label htmlFor="runtime-log-date-from">开始时间</label>
          <input
            id="runtime-log-date-from"
            type="datetime-local"
            value={filters.dateFrom ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, dateFrom: event.target.value }))}
          />
        </div>
        <div className="field-group">
          <label htmlFor="runtime-log-date-to">结束时间</label>
          <input
            id="runtime-log-date-to"
            type="datetime-local"
            value={filters.dateTo ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, dateTo: event.target.value }))}
          />
        </div>
        <div className="log-filter-grid__actions">
          <button type="submit" disabled={isLoading}>
            {isLoading ? "查询中..." : "查询日志"}
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              setFilters(DEFAULT_FILTERS);
              void loadLogs(DEFAULT_FILTERS);
            }}
            disabled={isLoading}
          >
            重置筛选
          </button>
        </div>
      </form>

      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}

      <div className="log-layout">
        <article className="data-card">
          <div className="data-card__header">
            <div>
              <h3>请求列表</h3>
              <span>{items.length} 条记录</span>
            </div>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>请求</th>
                <th>状态</th>
                <th>延迟</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="data-table__empty">
                    当前没有匹配的运行日志。
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>
                      <strong>{item.path}</strong>
                      <div className="data-table__sub">{item.request_id}</div>
                    </td>
                    <td>
                      <span
                        className={`status-pill ${
                          item.status_code >= 400 ? "status-pill--failed" : "status-pill--completed"
                        }`}
                      >
                        {item.status_code}
                      </span>
                    </td>
                    <td>{item.latency_ms} ms</td>
                    <td>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => void openDetail(item.id)}
                        disabled={isLoadingDetail}
                      >
                        查看详情
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </article>

        <aside className="data-card runtime-log-detail">
          <div className="data-card__header">
            <div>
              <h3>请求详情</h3>
              <span>{selectedLog ? selectedLog.request_id : "未选择记录"}</span>
            </div>
          </div>
          {selectedLog ? (
            <div className="detail-grid">
              <div className="detail-item">
                <span>请求 ID</span>
                <strong>{selectedLog.request_id}</strong>
              </div>
              <div className="detail-item">
                <span>会话 ID</span>
                <strong>{selectedLog.session_id ?? "无"}</strong>
              </div>
              <div className="detail-item">
                <span>模型名</span>
                <strong>{selectedLog.model_name ?? "未记录"}</strong>
              </div>
              <div className="detail-item">
                <span>租户 / 客户</span>
                <strong>
                  {selectedLog.tenant_id ?? "无"} / {selectedLog.customer_id ?? "无"}
                </strong>
              </div>
              <div className="detail-item">
                <span>Token 用量</span>
                <strong>{JSON.stringify(selectedLog.token_usage_json)}</strong>
              </div>
              <div className="detail-item">
                <span>错误信息</span>
                <strong>{selectedLog.error_message ?? "无"}</strong>
              </div>
            </div>
          ) : (
            <p className="data-table__empty">先从左侧选择一条日志查看详情。</p>
          )}
        </aside>
      </div>
    </section>
  );
}
