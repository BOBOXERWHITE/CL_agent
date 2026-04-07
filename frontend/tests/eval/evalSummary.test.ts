import { summarizeEvalDetails } from "../../src/utils/evalSummary";

const DETAILS = [
  {
    question: "北京酒店报销上限是多少？",
    answer: "北京酒店报销上限为每晚 650 元。",
    expected_citation: "北京酒店报销上限",
    expected_answer_keywords: ["北京", "650"],
    confidence: 0.92,
    citation_hit: true,
    answer_correct: true,
    low_confidence: false,
    citations: ["北京酒店报销上限为每晚 650 元。"],
  },
  {
    question: "business class 可以直接预订吗？",
    answer: "可以直接预订。",
    expected_citation: "需要审批",
    expected_answer_keywords: ["审批"],
    confidence: 0.35,
    citation_hit: false,
    answer_correct: false,
    low_confidence: true,
    citations: [],
  },
];

test("summarizes failure reasons from eval details", () => {
  const summary = summarizeEvalDetails(DETAILS);

  expect(summary.totalCount).toBe(2);
  expect(summary.failedCount).toBe(1);
  expect(summary.answerIncorrectCount).toBe(1);
  expect(summary.citationMissCount).toBe(1);
  expect(summary.lowConfidenceCount).toBe(1);
  expect(summary.emptyCitationCount).toBe(1);
});

test("returns zero failure counts when all details pass", () => {
  const summary = summarizeEvalDetails(DETAILS.slice(0, 1));

  expect(summary.totalCount).toBe(1);
  expect(summary.failedCount).toBe(0);
  expect(summary.answerIncorrectCount).toBe(0);
  expect(summary.citationMissCount).toBe(0);
  expect(summary.lowConfidenceCount).toBe(0);
  expect(summary.emptyCitationCount).toBe(0);
});
