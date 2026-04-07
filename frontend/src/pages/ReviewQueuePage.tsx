import { startTransition, useEffect, useState } from "react";

import { ReviewCase, RuleResult, listReviewCases } from "../api/reviews";
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

export default function ReviewQueuePage() {
  const [cases, setCases] = useState<ReviewCase[]>([]);
  const [errorMessage, setErrorMessage] = useState("");

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
        这里集中展示低置信度问答、规则拦截工单和需要人工接管的 Agent 运行结果，便于你最后统一做验收和复盘。
      </p>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
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
                    <span>建议动作</span>
                    <strong>{reviewCase.suggested_action}</strong>
                    <p>
                      租户 {reviewCase.tenant_id} / 客户 {reviewCase.customer_id}
                    </p>
                  </article>
                </div>
                <RuleResultPanel ruleResult={ruleResult} />
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
