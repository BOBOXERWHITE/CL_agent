import { startTransition, useEffect, useState } from "react";

import { EvalRun, listEvalRuns, triggerEvalRun } from "../api/evals";
import {
  buildEvalDetailsCsv,
  downloadTextFile,
  filterEvalDetails,
  type EvalDetailFilter,
} from "../utils/evalDetails";
import { summarizeEvalDetails } from "../utils/evalSummary";


const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
};

const METRIC_LABELS = [
  {
    key: "answer_correctness",
    label: "答案正确率",
  },
  {
    key: "citation_hit_rate",
    label: "引用命中率",
  },
  {
    key: "low_confidence_rate",
    label: "低置信度占比",
  },
] as const;

const DETAIL_FILTER_LABELS: Record<EvalDetailFilter, string> = {
  all: "全部",
  failed: "仅看失败项",
  low_confidence: "仅看低置信度",
};

const SUMMARY_METRICS = [
  {
    key: "failedCount",
    label: "失败题数",
  },
  {
    key: "answerIncorrectCount",
    label: "答案未命中",
  },
  {
    key: "citationMissCount",
    label: "引用未命中",
  },
  {
    key: "lowConfidenceCount",
    label: "低置信度",
  },
  {
    key: "emptyCitationCount",
    label: "无引用返回",
  },
] as const;

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function statusText(value: boolean, trueLabel: string, falseLabel: string): string {
  return value ? trueLabel : falseLabel;
}

export default function EvalPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [expandedRunIds, setExpandedRunIds] = useState<string[]>([]);
  const [detailFilters, setDetailFilters] = useState<Record<string, EvalDetailFilter>>({});

  async function loadRuns() {
    const nextRuns = await listEvalRuns();
    startTransition(() => {
      setRuns(nextRuns);
    });
  }

  useEffect(() => {
    void loadRuns().catch((error: unknown) => {
      setErrorMessage(error instanceof Error ? error.message : "评测记录加载失败。");
    });
  }, []);

  async function handleRunEval() {
    setIsSubmitting(true);
    setErrorMessage("");
    try {
      await triggerEvalRun({ datasetName: "zh-policy-smoke" });
      await loadRuns();
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : "评测运行失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  function toggleRunDetails(runId: string) {
    setExpandedRunIds((current) =>
      current.includes(runId) ? current.filter((item) => item !== runId) : [...current, runId],
    );
  }

  function updateDetailFilter(runId: string, filter: EvalDetailFilter) {
    setDetailFilters((current) => ({
      ...current,
      [runId]: filter,
    }));
  }

  function exportFilteredDetails(run: EvalRun) {
    const filter = detailFilters[run.id] ?? "all";
    const details = filterEvalDetails(run.details, filter);
    const csv = buildEvalDetailsCsv(details, DETAIL_FILTER_LABELS[filter]);
    downloadTextFile(
      `${run.dataset_name}-${run.id}.csv`,
      csv,
      "text/csv;charset=utf-8",
    );
  }

  return (
    <section className="panel panel--eval">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">离线评测</p>
          <h2>评测运行</h2>
        </div>
        <span className="panel__tag">zh-policy-smoke</span>
      </div>
      <p className="panel__description">
        先跑最小中文冒烟集，确认答案正确率、引用命中率和低置信度占比没有回退。
      </p>
      <div className="eval-actions">
        <button type="button" onClick={() => void handleRunEval()} disabled={isSubmitting}>
          运行评测
        </button>
        <p>当前评测集固定为 zh-policy-smoke，后续再扩成更完整的中文回归集。</p>
      </div>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      <div className="eval-grid">
        {runs.length === 0 ? (
          <div className="data-card">
            <div className="data-card__header">
              <h3>最近运行</h3>
            </div>
            <p className="data-table__empty">还没有评测记录，先跑一次中文回归。</p>
          </div>
        ) : (
          runs.map((run) => {
            const detailFilter = detailFilters[run.id] ?? "all";
            const filteredDetails = filterEvalDetails(run.details, detailFilter);
            const detailSummary = summarizeEvalDetails(run.details);

            return (
              <article key={run.id} className="data-card eval-run-card">
                <div className="data-card__header">
                  <div>
                    <h3>{run.dataset_name}</h3>
                    <span>{run.question_count} 个问题</span>
                  </div>
                  <span className={`status-pill status-pill--${run.status}`}>
                    {STATUS_LABELS[run.status] ?? run.status}
                  </span>
                </div>
                <div className="eval-metric-grid">
                  {METRIC_LABELS.map((metric) => {
                    const metricValue =
                      metric.key === "answer_correctness"
                        ? run.metrics.answer_correctness ?? run.metrics.answer_recall ?? 0
                        : run.metrics[metric.key];

                    return (
                      <div key={metric.key} className="eval-metric-card">
                        <span>{metric.label}</span>
                        <strong>{formatPercent(metricValue)}</strong>
                      </div>
                    );
                  })}
                </div>
                <div className="eval-run-card__footer">
                  <p>展开单题结果，逐条检查答案、引用和低置信度原因。</p>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => toggleRunDetails(run.id)}
                  >
                    {expandedRunIds.includes(run.id) ? "收起明细" : "查看明细"}
                  </button>
                </div>
                {expandedRunIds.includes(run.id) ? (
                  <div className="eval-detail-list">
                    <section className="eval-summary-card">
                      <div className="eval-summary-card__header">
                        <div>
                          <h4>失败原因汇总</h4>
                          <p>按整次评测全量统计，先看失败模式，再看下面的单题明细。</p>
                        </div>
                      </div>
                      <div className="eval-summary-grid">
                        {SUMMARY_METRICS.map((metric) => {
                          const value = detailSummary[metric.key];
                          const displayValue =
                            metric.key === "failedCount"
                              ? `${value} / ${detailSummary.totalCount} 题`
                              : `${value} 题`;

                          return (
                            <article key={metric.key} className="eval-summary-item">
                              <span>{metric.label}</span>
                              <strong>{displayValue}</strong>
                            </article>
                          );
                        })}
                      </div>
                    </section>
                    <div className="eval-detail-toolbar">
                      <div className="eval-detail-toolbar__filters">
                        {(Object.keys(DETAIL_FILTER_LABELS) as EvalDetailFilter[]).map((filter) => (
                          <button
                            key={filter}
                            type="button"
                            className={`secondary-button ${detailFilter === filter ? "secondary-button--active" : ""}`}
                            onClick={() => updateDetailFilter(run.id, filter)}
                          >
                            {DETAIL_FILTER_LABELS[filter]}
                          </button>
                        ))}
                      </div>
                      <div className="eval-detail-toolbar__actions">
                        <span>当前显示 {filteredDetails.length} / {run.details.length} 题</span>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => exportFilteredDetails(run)}
                        >
                          导出 CSV
                        </button>
                      </div>
                    </div>
                    {filteredDetails.length === 0 ? (
                      <p className="eval-detail-empty">当前筛选条件下没有评测明细。</p>
                    ) : (
                      filteredDetails.map((detail, index) => (
                        <article key={`${run.id}-${index}`} className="eval-detail-card">
                          <div className="eval-detail-card__header">
                            <strong>问题 {index + 1}</strong>
                            <span>置信度 {formatConfidence(detail.confidence)}</span>
                          </div>
                          <p className="eval-detail-card__question">{detail.question}</p>
                          <div className="eval-detail-card__body">
                            <div>
                              <span className="eval-detail-card__label">系统答案</span>
                              <p>{detail.answer}</p>
                            </div>
                            <div>
                              <span className="eval-detail-card__label">期望引用</span>
                              <p>{detail.expected_citation}</p>
                            </div>
                            <div>
                              <span className="eval-detail-card__label">答案关键词</span>
                              <p>{detail.expected_answer_keywords.join(" / ") || "未配置"}</p>
                            </div>
                          </div>
                          <div className="eval-detail-card__status">
                            <span>{statusText(detail.answer_correct, "答案正确", "答案未命中")}</span>
                            <span>{statusText(detail.citation_hit, "引用命中", "引用未命中")}</span>
                            <span>{statusText(detail.low_confidence, "低置信度", "置信度正常")}</span>
                          </div>
                          <div className="eval-detail-card__citations">
                            <span className="eval-detail-card__label">实际引用</span>
                            {detail.citations.length === 0 ? (
                              <p>当前没有返回引用片段。</p>
                            ) : (
                              detail.citations.map((citation, citationIndex) => (
                                <p key={`${run.id}-${index}-citation-${citationIndex}`}>{citation}</p>
                              ))
                            )}
                          </div>
                        </article>
                      ))
                    )}
                  </div>
                ) : null}
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
