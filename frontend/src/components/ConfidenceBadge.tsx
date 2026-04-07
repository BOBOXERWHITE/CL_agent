interface ConfidenceBadgeProps {
  confidence: number;
}

export default function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const percentage = Math.round(confidence * 100);
  const tone = confidence >= 0.85 ? "high" : confidence >= 0.6 ? "medium" : "low";

  return <p className={`confidence-badge confidence-badge--${tone}`}>置信度 {percentage}%</p>;
}
