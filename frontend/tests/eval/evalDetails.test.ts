import { buildEvalDetailsCsv, filterEvalDetails } from "../../src/utils/evalDetails";

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

test("filters only failed eval details", () => {
  const filtered = filterEvalDetails(DETAILS, "failed");

  expect(filtered).toHaveLength(1);
  expect(filtered[0].question).toBe("business class 可以直接预订吗？");
});

test("filters only low confidence eval details", () => {
  const filtered = filterEvalDetails(DETAILS, "low_confidence");

  expect(filtered).toHaveLength(1);
  expect(filtered[0].low_confidence).toBe(true);
});

test("builds csv with chinese headers and detail content", () => {
  const csv = buildEvalDetailsCsv(DETAILS.slice(1), "仅看失败项");

  expect(csv).toContain('"问题","系统答案","期望引用","答案关键词","置信度","答案正确","引用命中","低置信度","实际引用","筛选条件"');
  expect(csv).toContain("business class 可以直接预订吗？");
  expect(csv).toContain("仅看失败项");
});
