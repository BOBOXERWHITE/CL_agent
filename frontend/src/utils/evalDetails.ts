import type { EvalRun } from "../api/evals";

export type EvalDetail = EvalRun["details"][number];
export type EvalDetailFilter = "all" | "failed" | "low_confidence";

function escapeCsvCell(value: string): string {
  const normalized = value.split('"').join('""');
  return `"${normalized}"`;
}

export function filterEvalDetails(details: EvalDetail[], filter: EvalDetailFilter): EvalDetail[] {
  if (filter === "failed") {
    return details.filter((detail) => !detail.answer_correct || !detail.citation_hit);
  }
  if (filter === "low_confidence") {
    return details.filter((detail) => detail.low_confidence);
  }
  return details;
}

export function buildEvalDetailsCsv(details: EvalDetail[], filterLabel: string): string {
  const header = [
    "问题",
    "系统答案",
    "期望引用",
    "答案关键词",
    "置信度",
    "答案正确",
    "引用命中",
    "低置信度",
    "实际引用",
    "筛选条件",
  ];

  const rows = details.map((detail) => [
    detail.question,
    detail.answer,
    detail.expected_citation,
    detail.expected_answer_keywords.join(" / "),
    `${Math.round(detail.confidence * 100)}%`,
    detail.answer_correct ? "是" : "否",
    detail.citation_hit ? "是" : "否",
    detail.low_confidence ? "是" : "否",
    detail.citations.join(" / "),
    filterLabel,
  ]);

  return [header, ...rows]
    .map((row) => row.map((cell) => escapeCsvCell(cell)).join(","))
    .join("\n");
}

export function downloadTextFile(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
