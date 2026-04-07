import type { EvalDetail } from "./evalDetails";

export interface EvalFailureSummary {
  totalCount: number;
  failedCount: number;
  answerIncorrectCount: number;
  citationMissCount: number;
  lowConfidenceCount: number;
  emptyCitationCount: number;
}

export function summarizeEvalDetails(details: EvalDetail[]): EvalFailureSummary {
  return details.reduce<EvalFailureSummary>(
    (summary, detail) => {
      const failed = !detail.answer_correct || !detail.citation_hit;

      return {
        totalCount: summary.totalCount + 1,
        failedCount: summary.failedCount + (failed ? 1 : 0),
        answerIncorrectCount: summary.answerIncorrectCount + (detail.answer_correct ? 0 : 1),
        citationMissCount: summary.citationMissCount + (detail.citation_hit ? 0 : 1),
        lowConfidenceCount: summary.lowConfidenceCount + (detail.low_confidence ? 1 : 0),
        emptyCitationCount: summary.emptyCitationCount + (detail.citations.length === 0 ? 1 : 0),
      };
    },
    {
      totalCount: 0,
      failedCount: 0,
      answerIncorrectCount: 0,
      citationMissCount: 0,
      lowConfidenceCount: 0,
      emptyCitationCount: 0,
    },
  );
}
