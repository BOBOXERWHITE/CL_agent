import { startTransition, useEffect, useState } from "react";

import {
  type EvalRun,
  type EvalRunMetrics,
  type RegressionDelta,
  type RegressionDiff,
  listEvalRuns,
  triggerEvalRun,
} from "../api/evals";
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

// Percent-style metrics rendered as "85%". Order matters — first row is
// the legacy quality metrics, second row brings in the P0/P1 RAGAS-aligned
// additions so the new info doesn't bury the originals.
interface PercentMetricSpec {
  key: keyof EvalRunMetrics;
  label: string;
  fallbackKeys?: ReadonlyArray<keyof EvalRunMetrics>;
}

const PERCENT_METRICS: ReadonlyArray<PercentMetricSpec> = [
  { key: "answer_correctness", label: "答案正确率", fallbackKeys: ["answer_recall"] },
  { key: "citation_hit_rate", label: "引用命中率" },
  { key: "retrieval_mrr", label: "Retrieval MRR" },
  { key: "answer_pass_rate", label: "Answer Pass Rate" },
  { key: "low_confidence_rate", label: "低置信度占比" },
  // --- P0/P1 additions ---
  { key: "judge_answer_correctness", label: "LLM 判定正确率" },
  { key: "faithfulness", label: "Faithfulness" },
  { key: "context_precision", label: "Context Precision" },
  { key: "context_recall", label: "Context Recall" },
];

const DETAIL_FILTER_LABELS: Record<EvalDetailFilter, string> = {
  all: "全部",
  failed: "仅看失败项",
  low_confidence: "仅看低置信度",
};

const SUMMARY_METRICS = [
  { key: "failedCount", label: "失败题数" },
  { key: "answerIncorrectCount", label: "答案未命中" },
  { key: "citationMissCount", label: "引用未命中" },
  { key: "lowConfidenceCount", label: "低置信度" },
  { key: "emptyCitationCount", label: "无引用返回" },
] as const;

const REGRESSION_GATE_LABELS: Record<string, string> = {
  pass: "无退化",
  warn: "存在轻微退化",
  fail: "存在显著退化",
};

function formatPercent(value = 0): string {
  return `${Math.round(value * 100)}%`;
}

function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatFloat(value: number, fractionDigits = 4): string {
  return value.toFixed(fractionDigits);
}

// Cost is reported in USD; show 4-decimal precision when small, 2 when ≥1.
function formatCostUsd(value = 0): string {
  if (value >= 1) {
    return `$${value.toFixed(2)}`;
  }
  return `$${value.toFixed(4)}`;
}

function formatSignedDelta(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(4)}`;
}

function statusText(value: boolean, trueLabel: string, falseLabel: string): string {
  return value ? trueLabel : falseLabel;
}

interface EvalPageProps {
  defaultDatasetName?: string;
}

export default function EvalPage({ defaultDatasetName = "zh-policy-smoke" }: EvalPageProps) {
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
      await triggerEvalRun({ datasetName: defaultDatasetName });
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
    downloadTextFile(`${run.dataset_name}-${run.id}.csv`, csv, "text/csv;charset=utf-8");
  }

  return (
    <section className="panel panel--eval">
      <div className="panel__header">
        <div>
          <p className="panel__eyebrow">离线评测</p>
          <h2>评测运行</h2>
        </div>
        <span className="panel__tag">{defaultDatasetName}</span>
      </div>
      <p className="panel__description">
        这里用于观察回归评测的答案质量、检索排序质量和质量门禁结果。当前批次重点外显
        mixed-domain 评测门禁指标，便于回归对比。
      </p>
      <div className="eval-actions">
        <button type="button" onClick={() => void handleRunEval()} disabled={isSubmitting}>
          {isSubmitting ? "运行中..." : "运行评测"}
        </button>
        <p>当前默认评测集为 {defaultDatasetName}，可通过系统设置切换默认回归集。</p>
      </div>
      {errorMessage ? <p className="panel__error">{errorMessage}</p> : null}
      <div className="eval-grid">
        {runs.length === 0 ? (
          <div className="data-card">
            <div className="data-card__header">
              <h3>最近运行</h3>
            </div>
            <p className="data-table__empty">还没有评测记录，先跑一次回归。</p>
          </div>
        ) : (
          runs.map((run) => {
            const detailFilter = detailFilters[run.id] ?? "all";
            const filteredDetails = filterEvalDetails(run.details, detailFilter);
            const detailSummary = summarizeEvalDetails(run.details);
            const providerSnapshot = run.metrics.provider_snapshot;
            const qualityGate = run.metrics.quality_gate ?? "unknown";
            const qualityGateReasons = run.metrics.quality_gate_reasons ?? [];
            const regression = run.metrics.regression ?? null;
            const judgeCostUsd = run.metrics.judge_cost_usd_total ?? 0;
            const judgePromptTokens = run.metrics.judge_prompt_tokens_total ?? 0;
            const judgeCompletionTokens = run.metrics.judge_completion_tokens_total ?? 0;
            const judgeFallbackRate = run.metrics.judge_fallback_rate ?? 1;
            const hasJudgeCost =
              judgePromptTokens > 0 || judgeCompletionTokens > 0 || judgeCostUsd > 0;

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

                <div className="eval-metric-grid eval-metric-grid--wide">
                  {PERCENT_METRICS.map((metric) => {
                    const primary = run.metrics[metric.key];
                    const fallback = metric.fallbackKeys?.find(
                      (key) => run.metrics[key] !== undefined,
                    );
                    const numericValue =
                      typeof primary === "number"
                        ? primary
                        : fallback
                          ? Number(run.metrics[fallback] ?? 0)
                          : 0;

                    return (
                      <div key={metric.key} className="eval-metric-card">
                        <span>{metric.label}</span>
                        <strong>{formatPercent(numericValue)}</strong>
                      </div>
                    );
                  })}
                </div>

                <section className="eval-summary-card eval-summary-card--quality-gate">
                  <div className="eval-summary-card__header">
                    <div>
                      <h4>Quality Gate</h4>
                      <p>用统一门禁结果观察本次回归是否允许继续推进。</p>
                    </div>
                  </div>
                  <div className="eval-quality-gate-grid">
                    <article className="eval-summary-item">
                      <span>Gate Result</span>
                      <strong>{qualityGate}</strong>
                    </article>
                    <article className="eval-summary-item eval-summary-item--wide">
                      <span>Reasons</span>
                      <strong>
                        {qualityGateReasons.length > 0
                          ? qualityGateReasons.join("；")
                          : "No gate warnings"}
                      </strong>
                    </article>
                  </div>
                </section>

                {regression && regression.has_previous ? (
                  <RegressionDiffCard regression={regression} />
                ) : null}

                {hasJudgeCost ? (
                  <section className="eval-summary-card eval-summary-card--judge-cost">
                    <div className="eval-summary-card__header">
                      <div>
                        <h4>LLM 裁判成本</h4>
                        <p>
                          统计本次评测裁判调用的 token 使用与折算成本，便于
                          "是否值得开判官" 的成本/质量权衡。
                        </p>
                      </div>
                    </div>
                    <div className="eval-summary-grid">
                      <article className="eval-summary-item">
                        <span>Prompt Tokens</span>
                        <strong>{judgePromptTokens.toLocaleString()}</strong>
                      </article>
                      <article className="eval-summary-item">
                        <span>Completion Tokens</span>
                        <strong>{judgeCompletionTokens.toLocaleString()}</strong>
                      </article>
                      <article className="eval-summary-item">
                        <span>裁判成本</span>
                        <strong>{formatCostUsd(judgeCostUsd)}</strong>
                      </article>
                      <article className="eval-summary-item">
                        <span>关键词兜底比例</span>
                        <strong>{formatPercent(judgeFallbackRate)}</strong>
                      </article>
                    </div>
                  </section>
                ) : null}

                {providerSnapshot ? (
                  <section className="eval-summary-card">
                    <div className="eval-summary-card__header">
                      <div>
                        <h4>本次评测配置</h4>
                        <p>展示当前 LLM / embedding / vector store 组合，便于做回归对比。</p>
                      </div>
                    </div>
                    <div className="detail-grid">
                      <div className="detail-item">
                        <span>LLM Provider</span>
                        <strong>{providerSnapshot.llm_provider}</strong>
                      </div>
                      <div className="detail-item">
                        <span>LLM Model</span>
                        <strong>{providerSnapshot.llm_model_name}</strong>
                      </div>
                      <div className="detail-item">
                        <span>Embedding Provider</span>
                        <strong>{providerSnapshot.embedding_provider}</strong>
                      </div>
                      <div className="detail-item">
                        <span>Embedding Model</span>
                        <strong>{providerSnapshot.embedding_model_name}</strong>
                      </div>
                      <div className="detail-item">
                        <span>向量存储</span>
                        <strong>{providerSnapshot.vector_store_provider}</strong>
                      </div>
                    </div>
                  </section>
                ) : null}

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
                          <p>先看整次评测的失败模式，再看下面的单题明细。</p>
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
                        <span>
                          当前显示 {filteredDetails.length} / {run.details.length} 题
                        </span>
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
                      filteredDetails.map((detail, index) => {
                        const judgeReasoning = detail.judge_reasoning?.trim();
                        const hasJudgeMeta =
                          detail.judge_answer_correct !== undefined ||
                          detail.judge_faithfulness !== undefined ||
                          Boolean(judgeReasoning);
                        const hasContextMetrics =
                          detail.context_precision !== undefined ||
                          detail.context_recall !== undefined;
                        const detailJudgeCost = detail.judge_cost_usd ?? 0;
                        const detailJudgeTokens =
                          (detail.judge_prompt_tokens ?? 0) +
                          (detail.judge_completion_tokens ?? 0);
                        const hasJudgeCostDetail = detailJudgeCost > 0 || detailJudgeTokens > 0;

                        return (
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
                              <span>
                                {statusText(detail.answer_correct, "答案正确", "答案未命中")}
                              </span>
                              <span>
                                {statusText(detail.citation_hit, "引用命中", "引用未命中")}
                              </span>
                              <span>
                                {statusText(detail.low_confidence, "低置信度", "置信度正常")}
                              </span>
                            </div>

                            {hasJudgeMeta ? (
                              <div className="eval-detail-card__judge">
                                <span className="eval-detail-card__label">LLM 裁判判定</span>
                                <div className="eval-detail-card__judge-row">
                                  {detail.judge_answer_correct !== undefined ? (
                                    <span>
                                      语义{" "}
                                      {statusText(detail.judge_answer_correct, "正确", "未命中")}
                                    </span>
                                  ) : null}
                                  {detail.judge_faithfulness !== undefined ? (
                                    <span>
                                      Faithfulness {formatFloat(detail.judge_faithfulness, 2)}
                                    </span>
                                  ) : null}
                                  {detail.judge_fallback_used ? (
                                    <span className="status-pill status-pill--warn">
                                      关键词兜底
                                    </span>
                                  ) : null}
                                </div>
                                {judgeReasoning ? (
                                  <p className="eval-detail-card__judge-reasoning">
                                    {judgeReasoning}
                                  </p>
                                ) : null}
                              </div>
                            ) : null}

                            {hasContextMetrics || hasJudgeCostDetail ? (
                              <div className="eval-detail-card__metrics">
                                {detail.context_precision !== undefined ? (
                                  <span>
                                    Context Precision {formatFloat(detail.context_precision, 2)}
                                  </span>
                                ) : null}
                                {detail.context_recall !== undefined ? (
                                  <span>
                                    Context Recall {formatFloat(detail.context_recall, 2)}
                                  </span>
                                ) : null}
                                {hasJudgeCostDetail ? (
                                  <span>
                                    裁判成本 {formatCostUsd(detailJudgeCost)} ·{" "}
                                    {detailJudgeTokens.toLocaleString()} tokens
                                  </span>
                                ) : null}
                              </div>
                            ) : null}

                            <div className="eval-detail-card__citations">
                              <span className="eval-detail-card__label">实际引用</span>
                              {detail.citations.length === 0 ? (
                                <p>当前没有返回引用片段。</p>
                              ) : (
                                detail.citations.map((citation, citationIndex) => (
                                  <p key={`${run.id}-${index}-citation-${citationIndex}`}>
                                    {citation}
                                  </p>
                                ))
                              )}
                            </div>
                          </article>
                        );
                      })
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

interface RegressionDiffCardProps {
  regression: RegressionDiff;
}

function RegressionDiffCard({ regression }: RegressionDiffCardProps) {
  const gateLabel = REGRESSION_GATE_LABELS[regression.regression_gate] ?? regression.regression_gate;

  return (
    <section className="eval-summary-card eval-summary-card--regression">
      <div className="eval-summary-card__header">
        <div>
          <h4>回归门禁</h4>
          <p>
            和上一次同数据集运行对比，高于阈值的退化项会被标红。CI
            可以直接把 regression_gate 接成 PR 检查。
          </p>
        </div>
      </div>
      <div className="eval-quality-gate-grid">
        <article className="eval-summary-item">
          <span>Regression Gate</span>
          <strong className={`status-pill status-pill--${regression.regression_gate}`}>
            {gateLabel}
          </strong>
        </article>
        <article className="eval-summary-item eval-summary-item--wide">
          <span>上一次 Run</span>
          <strong>{regression.previous_run_id ?? "—"}</strong>
        </article>
      </div>
      {regression.regression_reasons.length > 0 ? (
        <ul className="eval-regression-reasons">
          {regression.regression_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
      <div className="eval-regression-table" role="table">
        <div className="eval-regression-table__head" role="row">
          <span role="columnheader">指标</span>
          <span role="columnheader">上次</span>
          <span role="columnheader">本次</span>
          <span role="columnheader">变化</span>
          <span role="columnheader">状态</span>
        </div>
        {regression.deltas.map((delta) => (
          <RegressionRow key={delta.name} delta={delta} />
        ))}
      </div>
    </section>
  );
}

interface RegressionRowProps {
  delta: RegressionDelta;
}

function RegressionRow({ delta }: RegressionRowProps) {
  const rowClassName = delta.regressed
    ? "eval-regression-table__row eval-regression-table__row--regressed"
    : "eval-regression-table__row";
  const isCost = delta.name === "judge_cost_usd_total";

  return (
    <div className={rowClassName} role="row">
      <span role="cell">{delta.name}</span>
      <span role="cell">{isCost ? formatCostUsd(delta.previous) : formatFloat(delta.previous)}</span>
      <span role="cell">{isCost ? formatCostUsd(delta.current) : formatFloat(delta.current)}</span>
      <span role="cell">
        {isCost ? formatCostUsd(delta.delta) : formatSignedDelta(delta.delta)}
      </span>
      <span role="cell">{delta.regressed ? "退化" : "持平 / 改进"}</span>
    </div>
  );
}
