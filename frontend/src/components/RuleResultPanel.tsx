import { RuleResult } from "../api/reviews";

interface RuleResultPanelProps {
  ruleResult?: RuleResult | null;
  heading?: string;
}

const DECISION_LABELS: Record<string, string> = {
  approved: "允许继续流转",
  blocked: "规则拦截",
};

export default function RuleResultPanel({
  ruleResult,
  heading = "规则结论",
}: RuleResultPanelProps) {
  if (!ruleResult || !ruleResult.decision) {
    return (
      <section className="rule-panel">
        <div className="rule-panel__header">
          <h4>{heading}</h4>
        </div>
        <p className="rule-panel__empty">当前案例未命中阻断规则，主要依赖低置信度或人工复核标记进入队列。</p>
      </section>
    );
  }

  return (
    <section className="rule-panel">
      <div className="rule-panel__header">
        <h4>{heading}</h4>
        <span className={`status-pill status-pill--${ruleResult.decision}`}>
          {DECISION_LABELS[ruleResult.decision] ?? ruleResult.decision}
        </span>
      </div>
      <div className="rule-panel__summary">
        <div>
          <span>判定原因</span>
          <strong>{ruleResult.reason}</strong>
        </div>
        <div>
          <span>建议动作</span>
          <strong>{ruleResult.suggested_action}</strong>
        </div>
      </div>
      {ruleResult.rule_hits.length > 0 ? (
        <ul className="rule-panel__list">
          {ruleResult.rule_hits.map((ruleHit) => (
            <li key={`${ruleHit.rule_code}-${ruleHit.actual_amount}`}>
              <div className="rule-panel__list-header">
                <strong>{ruleHit.rule_code}</strong>
                <span>{ruleHit.decision}</span>
              </div>
              <p>{ruleHit.reason}</p>
              <small>
                阈值 {Math.round(ruleHit.threshold_amount)} / 实际 {Math.round(ruleHit.actual_amount)}
              </small>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
