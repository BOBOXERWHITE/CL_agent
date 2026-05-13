"""LLM-as-judge for end-to-end QA evaluation.

The keyword-AND grading in :func:`app.services.eval.runner._matches_expected_answer`
is brittle: any paraphrase of the expected answer breaks it. RAGAS / DeepEval /
TruLens all sidestep this with an LLM judge — give the model the question, the
proposed answer, the gold expectation and the cited evidence, then ask for a
JSON verdict. We do the same here, with three guardrails:

1. **Off by default.** ``settings.eval_judge_enabled`` gates the LLM call.
   When False the judge returns a verdict synthesized from the existing
   keyword-fallback boolean — preserving today's behaviour bit-for-bit so
   nothing regresses for callers without a real LLM gateway.
2. **Fail-soft.** Network failures, non-2xx responses, garbled JSON and
   missing fields all funnel into the keyword fallback verdict with
   ``fallback_used=True``. The eval runner can then surface "judged: 8/10,
   fallback: 2/10" instead of crashing the whole run.
3. **Sanitized output.** Faithfulness is clamped to ``[0, 1]`` and forced
   to 0 when no citations were supplied (ungrounded by definition).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

_log = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
你是一名严谨的评测裁判。给定一道问题、被评测系统给出的回答、参考的关键信息、\
以及被引用的证据片段，请判断：
1. answer_correct：回答是否在语义上正确回答了问题（容忍同义改写、单位换算、\
   数值用大写写法等表面差异；如果回答缺漏关键信息或答非所问，则为 false）。
2. faithfulness：回答中的事实陈述能在多大比例上从所给证据中直接得出，取值 0~1。\
   如果回答额外引入证据中没有的事实，应降低该分数；如果完全凭空生成，则为 0。

只输出严格的 JSON 对象，不要附加任何解释或代码块标记，字段：
{"answer_correct": <true|false>, "faithfulness": <0.0~1.0>, "reasoning": "<不超过 80 字>"}
"""


@dataclass(frozen=True)
class JudgeVerdict:
    """Result of grading one answer.

    ``fallback_used=True`` means the LLM judge was disabled or failed and
    the verdict was synthesized from the keyword fallback. Aggregators
    should report the count separately so eval consumers know how much
    of the metric came from the LLM vs. a string match.

    P2 token / cost reporting:
      - ``prompt_tokens`` / ``completion_tokens``: from the OpenAI
        ``usage`` block on the chat completion response. Zero when the
        judge was disabled or when the upstream omitted the block (some
        self-hosted gateways do).
      - ``cost_usd``: computed from the price-per-1K config knobs. Zero
        when prices are unconfigured — better than showing a misleading
        $0.00 alongside non-zero tokens, ops people can spot the
        unconfigured state at a glance.
    """

    answer_correct: bool
    faithfulness: float
    reasoning: str
    fallback_used: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


def _keyword_fallback_verdict(
    *, keyword_fallback_match: bool, has_citations: bool, reason: str
) -> JudgeVerdict:
    # Faithfulness in fallback mode is a coarse proxy:
    #   - keyword match + had citations → 1.0 (model probably grounded)
    #   - keyword match + no citations  → 0.0 (no evidence to ground against)
    #   - keyword miss                  → 0.0 (likely wrong / ungrounded)
    faithfulness = 1.0 if keyword_fallback_match and has_citations else 0.0
    return JudgeVerdict(
        answer_correct=keyword_fallback_match,
        faithfulness=faithfulness,
        reasoning=f"keyword fallback used: {reason}",
        fallback_used=True,
    )


def _build_user_prompt(
    *,
    question: str,
    answer: str,
    expected_keywords: list[str],
    expected_citation: str,
    citations: list[str],
) -> str:
    keywords_block = "、".join(expected_keywords) if expected_keywords else "(无)"
    citation_block = (
        "\n".join(f"[{idx + 1}] {text}" for idx, text in enumerate(citations))
        if citations
        else "(无引用证据)"
    )
    return (
        f"问题：{question}\n"
        f"系统回答：{answer}\n"
        f"参考关键词（语义层面应覆盖到的核心点）：{keywords_block}\n"
        f"期望命中的证据片段：{expected_citation}\n"
        f"系统实际引用的证据：\n{citation_block}"
    )


def _clamp_unit(value: object) -> float:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _safe_nonnegative_int(value: object) -> int:
    """Coerce a possibly-garbage upstream token count into a sane int.

    OpenAI-compatible gateways sometimes return ``null``, a string, or a
    negative number for ``usage.prompt_tokens`` (seen in older self-hosted
    vLLM and in cached responses). We coerce to 0 rather than propagate
    bad data into the cost aggregation downstream — easier to spot a
    stuck-at-zero metric than chase phantom negative costs.
    """
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(n, 0)


def _compute_cost_usd(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    prompt_price_per_1k: float,
    completion_price_per_1k: float,
) -> float:
    """Standard 1K-token pricing math. Returns 0.0 when either side is 0
    so an unconfigured price never produces a phantom cost."""
    if prompt_price_per_1k <= 0.0 and completion_price_per_1k <= 0.0:
        return 0.0
    prompt_cost = (prompt_tokens / 1000.0) * prompt_price_per_1k
    completion_cost = (completion_tokens / 1000.0) * completion_price_per_1k
    return round(prompt_cost + completion_cost, 6)


def _parse_judge_payload(content: str) -> tuple[bool, float, str] | None:
    """Parse the LLM's JSON verdict.

    Tolerates a leading ``"json"`` language tag or surrounding code-fence
    backticks because real models love to wrap JSON anyway. Returns None
    when the payload is unsalvageable; the caller treats None as a fallback
    trigger.
    """
    text = content.strip()
    if text.startswith("```"):
        # strip ```json ... ``` or ``` ... ```
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if "answer_correct" not in payload:
        return None
    return (
        bool(payload.get("answer_correct")),
        _clamp_unit(payload.get("faithfulness", 0.0)),
        str(payload.get("reasoning", "")).strip(),
    )


def judge_answer(
    *,
    question: str,
    answer: str,
    expected_keywords: list[str],
    expected_citation: str,
    citations: list[str],
    keyword_fallback_match: bool,
    http_client: httpx.Client | None = None,
) -> JudgeVerdict:
    """Grade one (question, answer) pair with an LLM judge.

    ``citations`` carries the *full text* of the chunks the system cited;
    the judge needs the actual evidence to score faithfulness. Pass an
    empty list when the system returned no citations — faithfulness is
    then forced to 0 regardless of judge output.

    ``keyword_fallback_match`` is the existing AND-keyword verdict from
    :func:`app.services.eval.runner._matches_expected_answer`; we use it
    as the safety net any time the LLM judge can't return a usable answer.
    """
    settings = get_settings()
    has_citations = bool(citations)

    if not settings.eval_judge_enabled:
        return _keyword_fallback_verdict(
            keyword_fallback_match=keyword_fallback_match,
            has_citations=has_citations,
            reason="eval_judge_enabled is False",
        )

    if settings.llm_provider != "openai-compatible" or not (
        settings.llm_api_base_url and settings.llm_api_key
    ):
        return _keyword_fallback_verdict(
            keyword_fallback_match=keyword_fallback_match,
            has_citations=has_citations,
            reason="judge requires an openai-compatible LLM gateway",
        )

    model_name = settings.eval_judge_model_name or settings.llm_model_name
    client = http_client or httpx.Client(timeout=settings.eval_judge_timeout_seconds)

    user_prompt = _build_user_prompt(
        question=question,
        answer=answer,
        expected_keywords=expected_keywords,
        expected_citation=expected_citation,
        citations=citations,
    )

    try:
        response = client.post(
            f"{settings.llm_api_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "temperature": 0.0,
                "messages": [
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = str(payload["choices"][0]["message"]["content"])
    except (
        httpx.HTTPError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as exc:
        _log.warning("LLM judge HTTP/parse error: %s", exc, exc_info=False)
        return _keyword_fallback_verdict(
            keyword_fallback_match=keyword_fallback_match,
            has_citations=has_citations,
            reason=f"LLM judge call failed: {type(exc).__name__}",
        )

    parsed = _parse_judge_payload(content)
    if parsed is None:
        return _keyword_fallback_verdict(
            keyword_fallback_match=keyword_fallback_match,
            has_citations=has_citations,
            reason="LLM judge returned non-JSON payload",
        )

    answer_correct, faithfulness, reasoning = parsed
    if not has_citations:
        # Ungrounded by definition — override the model's possibly-lenient score.
        faithfulness = 0.0

    # P2: parse OpenAI ``usage`` block. Gracefully degrades to zeros
    # when the gateway omitted the block (some self-hosted vLLM) or
    # filled it with garbage (negative, null, string).
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(usage, dict):
        prompt_tokens = _safe_nonnegative_int(usage.get("prompt_tokens"))
        completion_tokens = _safe_nonnegative_int(usage.get("completion_tokens"))
    else:
        prompt_tokens = 0
        completion_tokens = 0
    cost_usd = _compute_cost_usd(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_price_per_1k=settings.eval_judge_price_prompt_per_1k_usd,
        completion_price_per_1k=settings.eval_judge_price_completion_per_1k_usd,
    )

    return JudgeVerdict(
        answer_correct=answer_correct,
        faithfulness=faithfulness,
        reasoning=reasoning or "(judge returned empty reasoning)",
        fallback_used=False,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )


__all__ = ["JudgeVerdict", "judge_answer"]
