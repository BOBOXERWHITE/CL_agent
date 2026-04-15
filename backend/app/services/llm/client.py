from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import httpx

from app.core.config import get_settings
from app.services.rag.text_processing import extract_cjk_sequences


@dataclass(frozen=True)
class AnswerDraft:
    answer: str
    confidence: float
    model_name: str
    token_usage: dict[str, int]


@dataclass(frozen=True)
class LlmReadiness:
    provider: str
    model_name: str
    configured: bool
    available: bool
    status: str
    message: str
    endpoint: str | None = None


@dataclass(frozen=True)
class LlmSmokeTestResult:
    provider: str
    model_name: str
    configured: bool
    available: bool
    status: str
    message: str
    sample_question: str
    sample_evidence: str
    answer_preview: str
    latency_ms: float
    token_usage: dict[str, int]
    endpoint: str | None = None


DEFAULT_SMOKE_TEST_QUESTION = "北京酒店报销上限是多少？"
DEFAULT_SMOKE_TEST_EVIDENCE = "北京酒店报销上限为每晚 650 元。"
DEFAULT_SMOKE_TEST_PROMPT = "请严格基于证据回答，不要编造未出现的信息。"


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
            confidence=confidence,
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


def _resolve_llm_gateway_settings(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> tuple[str, str, str, str]:
    settings = get_settings()
    return (
        (provider or settings.llm_provider).strip().lower(),
        (base_url or settings.llm_api_base_url).strip(),
        (api_key or settings.llm_api_key).strip(),
        (model_name or settings.llm_model_name).strip(),
    )


def _supports_models_endpoint(status_code: int) -> bool:
    return status_code not in {404, 405, 501}


def _probe_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model_name: str,
    http_client: httpx.Client,
) -> None:
    response = http_client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_name,
            "max_tokens": 1,
            "messages": [
                {
                    "role": "user",
                    "content": "ping",
                }
            ],
        },
    )
    response.raise_for_status()


def check_llm_readiness(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    http_client: httpx.Client | None = None,
) -> LlmReadiness:
    resolved_provider, resolved_base_url, resolved_api_key, resolved_model_name = (
        _resolve_llm_gateway_settings(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
        )
    )

    if resolved_provider != "openai-compatible":
        return LlmReadiness(
            provider="deterministic",
            model_name=DeterministicPolicyAnswerClient.model_name,
            configured=True,
            available=True,
            status="ready",
            message="当前使用本地 deterministic LLM，无需额外网关连通性检查。",
        )

    if not resolved_base_url or not resolved_api_key:
        return LlmReadiness(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=False,
            available=False,
            status="missing_config",
            message="缺少 LLM_API_BASE_URL 或 LLM_API_KEY。",
            endpoint=resolved_base_url or None,
        )

    client = http_client or httpx.Client(timeout=5.0)
    try:
        response = client.get(
            f"{resolved_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {resolved_api_key}"},
        )
        response.raise_for_status()
        payload = response.json()
        model_ids = [
            str(item.get("id"))
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
    except httpx.HTTPStatusError as exc:
        if _supports_models_endpoint(exc.response.status_code):
            return LlmReadiness(
                provider="openai-compatible",
                model_name=resolved_model_name,
                configured=True,
                available=False,
                status="unreachable",
                message=f"LLM 网关不可达：{exc}",
                endpoint=resolved_base_url,
            )

        try:
            _probe_chat_completion(
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                model_name=resolved_model_name,
                http_client=client,
            )
        except Exception as probe_exc:
            return LlmReadiness(
                provider="openai-compatible",
                model_name=resolved_model_name,
                configured=True,
                available=False,
                status="unreachable",
                message=f"LLM 网关不可达：/models 不可用，且最小推理探活失败：{probe_exc}",
                endpoint=resolved_base_url,
            )

        return LlmReadiness(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=True,
            available=True,
            status="ready",
            message=f"LLM 网关连通正常；/models 不可用，已通过真实推理探活验证 {resolved_model_name}。",
            endpoint=resolved_base_url,
        )
    except Exception as exc:
        return LlmReadiness(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=True,
            available=False,
            status="unreachable",
            message=f"LLM 网关不可达：{exc}",
            endpoint=resolved_base_url,
        )

    model_hint = (
        f"；当前模型 {resolved_model_name} 已在网关列表中。"
        if resolved_model_name in model_ids
        else f"；当前模型 {resolved_model_name} 未在网关列表中显式返回。"
    )
    return LlmReadiness(
        provider="openai-compatible",
        model_name=resolved_model_name,
        configured=True,
        available=True,
        status="ready",
        message=f"LLM 网关连通正常{model_hint}",
        endpoint=resolved_base_url,
    )


def run_llm_smoke_test(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    http_client: httpx.Client | None = None,
    sample_question: str = DEFAULT_SMOKE_TEST_QUESTION,
    sample_evidence: str = DEFAULT_SMOKE_TEST_EVIDENCE,
    prompt_template: str = DEFAULT_SMOKE_TEST_PROMPT,
) -> LlmSmokeTestResult:
    resolved_provider, resolved_base_url, resolved_api_key, resolved_model_name = (
        _resolve_llm_gateway_settings(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
        )
    )
    if resolved_provider == "openai-compatible" and (not resolved_base_url or not resolved_api_key):
        return LlmSmokeTestResult(
            provider="openai-compatible",
            model_name=resolved_model_name,
            configured=False,
            available=False,
            status="missing_config",
            message="缺少 LLM_API_BASE_URL 或 LLM_API_KEY。",
            sample_question=sample_question,
            sample_evidence=sample_evidence,
            answer_preview="",
            latency_ms=0.0,
            token_usage={"input_tokens": 0, "output_tokens": 0},
            endpoint=resolved_base_url or None,
        )

    if resolved_provider == "openai-compatible":
        client = OpenAICompatiblePolicyAnswerClient(
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            model_name=resolved_model_name,
            http_client=http_client,
        )
        result_provider = "openai-compatible"
        endpoint = resolved_base_url
    else:
        client = DeterministicPolicyAnswerClient()
        result_provider = "deterministic"
        endpoint = None

    started_at = perf_counter()
    try:
        answer_draft = client.generate_answer(
            question=sample_question,
            evidence_snippets=[sample_evidence],
            confidence=0.88,
            prompt_template=prompt_template,
        )
    except Exception as exc:
        return LlmSmokeTestResult(
            provider=result_provider,
            model_name=resolved_model_name,
            configured=True,
            available=False,
            status="failed",
            message=f"LLM 烟雾测试失败：{exc}",
            sample_question=sample_question,
            sample_evidence=sample_evidence,
            answer_preview="",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            token_usage={"input_tokens": 0, "output_tokens": 0},
            endpoint=endpoint,
        )

    return LlmSmokeTestResult(
        provider=result_provider,
        model_name=answer_draft.model_name,
        configured=True,
        available=True,
        status="ready",
        message="LLM 烟雾测试通过。",
        sample_question=sample_question,
        sample_evidence=sample_evidence,
        answer_preview=answer_draft.answer,
        latency_ms=round((perf_counter() - started_at) * 1000, 2),
        token_usage=answer_draft.token_usage,
        endpoint=endpoint,
    )
