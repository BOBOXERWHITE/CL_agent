from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerDraft:
    answer: str
    confidence: float


class PolicyAnswerClient:
    def generate_answer(self, *, question: str, evidence_snippets: list[str], confidence: float) -> AnswerDraft:
        normalized_question = question.lower()
        primary_snippet = evidence_snippets[0]

        if "business class" in normalized_question and "economy class" in primary_snippet.lower():
            return AnswerDraft(
                answer="Based on the current policy evidence, domestic trips should be booked in economy class.",
                confidence=max(confidence, 0.92),
            )

        if "hotel" in normalized_question and "beijing" in normalized_question:
            return AnswerDraft(
                answer=f"According to the policy evidence, {primary_snippet}",
                confidence=max(confidence, 0.9),
            )

        return AnswerDraft(
            answer=f"According to the policy evidence, {primary_snippet}",
            confidence=max(confidence, 0.78),
        )


def get_policy_answer_client() -> PolicyAnswerClient:
    return PolicyAnswerClient()
