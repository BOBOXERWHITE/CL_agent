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

  // Header now carries P0/P1/P2 columns alongside the legacy ones.
  expect(csv).toContain(
    '"问题","系统答案","期望引用","答案关键词","置信度","答案正确","引用命中","低置信度","LLM 判定正确","Faithfulness","Context Precision","Context Recall","裁判成本 (USD)","实际引用","筛选条件"',
  );
  expect(csv).toContain("business class 可以直接预订吗？");
  expect(csv).toContain("仅看失败项");
});

test("csv leaves new judge / context columns empty when the detail lacks them", () => {
  // Legacy detail rows (no judge_* / context_* fields) must round-trip
  // through the CSV without injecting bogus zeros for missing data.
  // Column layout from "答案正确" onward:
  //   答案正确 / 引用命中 / 低置信度 / LLM 判定正确 / Faithfulness /
  //   Context Precision / Context Recall / 裁判成本 (USD) / 实际引用 / 筛选条件
  const csv = buildEvalDetailsCsv(DETAILS.slice(0, 1), "全部");

  expect(csv).toContain(
    '"是","是","否","","","","","","北京酒店报销上限为每晚 650 元。","全部"',
  );
});

test("csv populates new columns when detail rows carry the P0-P2 fields", () => {
  const csv = buildEvalDetailsCsv(
    [
      {
        ...DETAILS[0],
        judge_answer_correct: true,
        judge_faithfulness: 0.91,
        context_precision: 0.83,
        context_recall: 0.95,
        judge_cost_usd: 0.0007,
      },
    ],
    "全部",
  );

  expect(csv).toContain(
    '"是","是","否","是","0.9100","0.8300","0.9500","0.000700"',
  );
});
