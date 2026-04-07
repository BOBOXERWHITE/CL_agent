from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.services.rag.text_processing import extract_cjk_sequences


@dataclass(frozen=True)
class AnswerDraft:
    answer: str
    confidence: float
    model_name: str
    token_usage: dict[str, int]


class DeterministicPolicyAnswerClient:
    model_name = "deterministic-policy-client"

    @staticmethod
    def _is_chinese_query(question: str) -> bool:
        return bool(extract_cjk_sequences(question))

    def generate_answer(
        self,
        *,
        question: str,
        evidence_snippets: list[str],
        confidence: float,
        prompt_template: str,
    ) -> AnswerDraft:
        normalized_question = question.lower()
        primary_snippet = evidence_snippets[0]
        input_tokens = len((question + " " + " ".join(evidence_snippets) + " " + prompt_template).split())
        is_chinese_query = self._is_chinese_query(question)

        if "business class" in normalized_question and "economy class" in primary_snippet.lower():
            answer = (
                "根据当前政策证据，国内出差应优先预订 economy class。"
                if is_chinese_query
                else "Based on the current policy evidence, domestic trips should be booked in economy class."
            )
            return AnswerDraft(
                answer=answer,
                confidence=max(confidence, 0.92),
                model_name=self.model_name,
                token_usage={"input_tokens": input_tokens, "output_tokens": len(answer.split())},
            )

        if "hotel" in normalized_question and "beijing" in normalized_question:
            answer = (
                f"根据政策证据，{primary_snippet}"
                if is_chinese_query
                else f"According to the policy evidence, {primary_snippet}"
            )
            return AnswerDraft(
                answer=answer,
                confidence=max(confidence, 0.9),
                model_name=self.model_name,
                token_usage={"input_tokens": input_tokens, "output_tokens": len(answer.split())},
            )

        answer = (
            f"根据政策证据，{primary_snippet}"
            if is_chinese_query
            else f"According to the policy evidence, {primary_snippet}"
        )
        return AnswerDraft(
            answer=answer,
            confidence=max(confidence, 0.78),
            model_name=self.model_name,
            token_usage={"input_tokens": input_tokens, "output_tokens": len(answer.split())},
        )


class OpenAICompatiblePolicyAnswerClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self._http_client = http_client or httpx.Client(timeout=30.0)

    def generate_answer(
        self,
        *,
        question: str,
        evidence_snippets: list[str],
        confidence: float,
        prompt_template: str,
    ) -> AnswerDraft:
        evidence_block = "\n".join(f"- {snippet}" for snippet in evidence_snippets)
        response = self._http_client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "system",
                        "content": prompt_template,
                    },
                    {
                        "role": "user",
                        "content": (
                            "请基于给定证据回答问题，回答要简洁且不能捏造未出现的信息。\n"
                            f"问题：{question}\n"
                            f"证据：\n{evidence_block}"
                        ),
                    },
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        answer = str(payload["choices"][0]["message"]["content"]).strip()
        usage = payload.get("usage", {})
        return AnswerDraft(
            answer=answer,
            confidence=max(confidence, 0.78),
            model_name=str(payload.get("model", self.model_name)),
            token_usage={
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            },
        )


def get_policy_answer_client() -> DeterministicPolicyAnswerClient | OpenAICompatiblePolicyAnswerClient:
    settings = get_settings()
    if (
        settings.llm_provider == "openai-compatible"
        and settings.llm_api_base_url
        and settings.llm_api_key
    ):
        return OpenAICompatiblePolicyAnswerClient(
            base_url=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
        )
    return DeterministicPolicyAnswerClient()
