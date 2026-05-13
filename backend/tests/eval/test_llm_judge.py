"""Unit tests for the LLM-as-judge evaluation helper.

The judge is the P0 upgrade for end-to-end QA grading: instead of
deciding "answer correct = all expected keywords appear as substrings"
(which is brittle to paraphrase), the judge asks a real LLM to score
correctness + faithfulness against the cited evidence.

Critical invariants under test:

1. **Disabled by default** — when ``settings.eval_judge_enabled`` is
   False, the judge MUST NOT call out to any LLM. It returns a verdict
   built from the keyword fallback so existing dev / CI runs without a
   real gateway keep working.
2. **Graceful degradation** — when the judge is enabled but the LLM
   call fails (network, parse error, empty body), the judge falls back
   to the keyword verdict and marks ``fallback_used=True`` so the
   metric layer can surface "judge skipped N samples" instead of
   silently returning a wrong number.
3. **Output sanitization** — the LLM might emit faithfulness > 1 or
   < 0 (or a string). We clamp to [0, 1] and coerce types so downstream
   aggregation (mean across samples) never blows up.
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.services.eval.llm_judge import (
    JudgeVerdict,
    judge_answer,
)


@pytest.fixture
def judge_settings(monkeypatch) -> Settings:
    """Force the judge ON with a fake openai-compatible gateway."""
    settings = get_settings()
    overridden = replace(
        settings,
        eval_judge_enabled=True,
        eval_judge_model_name="judge-test-model",
        llm_provider="openai-compatible",
        llm_api_base_url="https://judge.example.test/v1",
        llm_api_key="fake-key",
        llm_model_name="judge-test-model",
    )
    monkeypatch.setattr("app.services.eval.llm_judge.get_settings", lambda: overridden)
    return overridden


def _mock_transport(payload: dict[str, object]) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _mock_transport_with_status(status_code: int, body: str = "") -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body.encode("utf-8"))

    return httpx.MockTransport(handler)


def test_judge_disabled_returns_keyword_fallback_without_llm_call(monkeypatch) -> None:
    """When eval_judge_enabled=False, no HTTP call must happen."""
    settings = get_settings()
    overridden = replace(settings, eval_judge_enabled=False)
    monkeypatch.setattr("app.services.eval.llm_judge.get_settings", lambda: overridden)

    def fail_if_called(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("judge must not call LLM when disabled")

    monkeypatch.setattr("httpx.Client", fail_if_called)

    verdict = judge_answer(
        question="北京酒店报销上限是多少？",
        answer="北京酒店报销上限为每晚 650 元。",
        expected_keywords=["北京", "650"],
        expected_citation="北京酒店报销上限",
        citations=["北京酒店报销上限为每晚 650 元。"],
        keyword_fallback_match=True,
    )

    assert isinstance(verdict, JudgeVerdict)
    assert verdict.answer_correct is True
    assert verdict.fallback_used is True
    assert verdict.faithfulness == pytest.approx(1.0)  # keyword hit → assumed grounded
    assert "fallback" in verdict.reasoning.lower()


def test_judge_disabled_keyword_miss_returns_incorrect_fallback(monkeypatch) -> None:
    settings = get_settings()
    overridden = replace(settings, eval_judge_enabled=False)
    monkeypatch.setattr("app.services.eval.llm_judge.get_settings", lambda: overridden)

    verdict = judge_answer(
        question="上海酒店报销上限是多少？",
        answer="不知道。",
        expected_keywords=["上海", "550"],
        expected_citation="上海酒店报销上限",
        citations=[],
        keyword_fallback_match=False,
    )

    assert verdict.answer_correct is False
    assert verdict.fallback_used is True
    # No citations + no keyword match → faithfulness = 0
    assert verdict.faithfulness == pytest.approx(0.0)


def test_judge_enabled_parses_llm_json_verdict(judge_settings: Settings) -> None:
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer_correct": True,
                                "faithfulness": 0.92,
                                "reasoning": "答案与引用的 650 元上限一致。",
                            }
                        )
                    }
                }
            ]
        }
    )

    verdict = judge_answer(
        question="北京酒店报销上限是多少？",
        answer="北京最高可报销陆佰伍拾元/晚",  # paraphrased — keyword fails
        expected_keywords=["北京", "650"],
        expected_citation="北京酒店报销上限",
        citations=["北京酒店报销上限为每晚 650 元。"],
        keyword_fallback_match=False,  # keyword path would say WRONG
        http_client=httpx.Client(transport=transport),
    )

    # The whole point: LLM judge says correct even though keyword failed.
    assert verdict.answer_correct is True
    assert verdict.faithfulness == pytest.approx(0.92)
    assert verdict.fallback_used is False
    assert "650" in verdict.reasoning


def test_judge_enabled_falls_back_on_http_error(judge_settings: Settings) -> None:
    transport = _mock_transport_with_status(500, "internal error")

    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=["A"],
        expected_citation="A",
        citations=["A"],
        keyword_fallback_match=True,
        http_client=httpx.Client(transport=transport),
    )

    assert verdict.fallback_used is True
    assert verdict.answer_correct is True  # fell back to keyword_fallback_match
    assert "fallback" in verdict.reasoning.lower()


def test_judge_enabled_falls_back_on_invalid_json(judge_settings: Settings) -> None:
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": "this is not json {",
                    }
                }
            ]
        }
    )

    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=["nope"],
        expected_citation="X",
        citations=["X"],
        keyword_fallback_match=False,
        http_client=httpx.Client(transport=transport),
    )

    assert verdict.fallback_used is True
    assert verdict.answer_correct is False  # keyword fallback


def test_judge_clamps_faithfulness_into_unit_interval(judge_settings: Settings) -> None:
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer_correct": True,
                                "faithfulness": 1.7,  # over the limit
                                "reasoning": "weirdly confident judge",
                            }
                        )
                    }
                }
            ]
        }
    )

    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=[],
        expected_citation="X",
        citations=["X"],
        keyword_fallback_match=True,
        http_client=httpx.Client(transport=transport),
    )

    assert 0.0 <= verdict.faithfulness <= 1.0
    assert verdict.faithfulness == pytest.approx(1.0)


def test_judge_clamps_negative_faithfulness_to_zero(judge_settings: Settings) -> None:
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer_correct": False,
                                "faithfulness": -0.4,
                                "reasoning": "broken model",
                            }
                        )
                    }
                }
            ]
        }
    )

    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=[],
        expected_citation="X",
        citations=["X"],
        keyword_fallback_match=False,
        http_client=httpx.Client(transport=transport),
    )

    assert verdict.faithfulness == pytest.approx(0.0)


def test_judge_handles_missing_citations_block(judge_settings: Settings) -> None:
    """When the answer cites nothing, faithfulness defaults to 0 even if the
    judge LLM tries to be lenient — there's literally no evidence to ground
    against. The judge prompt should make this explicit."""
    transport = _mock_transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer_correct": True,
                                "faithfulness": 0.8,
                                "reasoning": "looks plausible",
                            }
                        )
                    }
                }
            ]
        }
    )

    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=[],
        expected_citation="X",
        citations=[],  # NO citations
        keyword_fallback_match=False,
        http_client=httpx.Client(transport=transport),
    )

    # faithfulness is forced to 0 by the helper — without citations it's
    # impossible to be grounded, regardless of what the judge model says.
    assert verdict.faithfulness == pytest.approx(0.0)


def test_judge_verdict_is_immutable() -> None:
    verdict = JudgeVerdict(
        answer_correct=True,
        faithfulness=0.5,
        reasoning="r",
        fallback_used=False,
    )
    with pytest.raises((AttributeError, TypeError)):
        verdict.answer_correct = False  # type: ignore[misc]


# ---------- P2: token usage + cost reporting -------------------------


def _mock_transport_with_usage(
    *,
    content: dict[str, object],
    prompt_tokens: int,
    completion_tokens: int,
) -> httpx.MockTransport:
    """LLM gateway responses include an ``usage`` block per the OpenAI
    contract. The judge needs to parse it so the runner can aggregate
    cost per dataset run."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            },
        )

    return httpx.MockTransport(handler)


def test_judge_records_token_usage_from_response(judge_settings, monkeypatch) -> None:
    # Set a non-zero per-1K price so cost_usd should be > 0.
    overridden = replace(
        judge_settings,
        eval_judge_price_prompt_per_1k_usd=1.0,  # $1 per 1K prompt tokens
        eval_judge_price_completion_per_1k_usd=2.0,  # $2 per 1K completion tokens
    )
    monkeypatch.setattr("app.services.eval.llm_judge.get_settings", lambda: overridden)

    transport = _mock_transport_with_usage(
        content={
            "answer_correct": True,
            "faithfulness": 0.9,
            "reasoning": "ok",
        },
        prompt_tokens=500,
        completion_tokens=100,
    )

    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=[],
        expected_citation="X",
        citations=["X"],
        keyword_fallback_match=True,
        http_client=httpx.Client(transport=transport),
    )

    assert verdict.prompt_tokens == 500
    assert verdict.completion_tokens == 100
    # 500/1000 * $1 + 100/1000 * $2 = $0.5 + $0.2 = $0.7
    assert verdict.cost_usd == pytest.approx(0.7, rel=1e-6)


def test_judge_zero_cost_when_prices_default(judge_settings: Settings) -> None:
    """Default judge_settings has both prices at 0 — cost_usd must be 0
    even when tokens are non-zero, so users who don't configure prices
    aren't shown a misleading $0.00 vs missing distinction."""
    transport = _mock_transport_with_usage(
        content={"answer_correct": True, "faithfulness": 0.5, "reasoning": "ok"},
        prompt_tokens=200,
        completion_tokens=50,
    )

    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=[],
        expected_citation="X",
        citations=["X"],
        keyword_fallback_match=True,
        http_client=httpx.Client(transport=transport),
    )

    assert verdict.prompt_tokens == 200
    assert verdict.completion_tokens == 50
    assert verdict.cost_usd == pytest.approx(0.0)


def test_judge_token_fields_are_zero_when_disabled(monkeypatch) -> None:
    """Fallback verdicts must report zero tokens — the LLM was never
    called, so attributing any cost to this sample would be wrong."""
    settings = get_settings()
    overridden = replace(settings, eval_judge_enabled=False)
    monkeypatch.setattr("app.services.eval.llm_judge.get_settings", lambda: overridden)

    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=["A"],
        expected_citation="X",
        citations=["X"],
        keyword_fallback_match=True,
    )

    assert verdict.fallback_used is True
    assert verdict.prompt_tokens == 0
    assert verdict.completion_tokens == 0
    assert verdict.cost_usd == pytest.approx(0.0)


def test_judge_handles_missing_usage_block_gracefully(judge_settings: Settings) -> None:
    """Some OpenAI-compatible gateways (older self-hosted vLLM, etc.)
    omit the ``usage`` block entirely. Judge should still parse the
    verdict and report tokens=0 rather than raising."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_correct": True,
                                    "faithfulness": 0.8,
                                    "reasoning": "no usage block in this gateway",
                                }
                            )
                        }
                    }
                ],
                # NO "usage" key
            },
        )

    transport = httpx.MockTransport(handler)
    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=[],
        expected_citation="X",
        citations=["X"],
        keyword_fallback_match=True,
        http_client=httpx.Client(transport=transport),
    )

    assert verdict.fallback_used is False  # parse succeeded
    assert verdict.answer_correct is True
    assert verdict.prompt_tokens == 0
    assert verdict.completion_tokens == 0
    assert verdict.cost_usd == pytest.approx(0.0)


def test_judge_ignores_negative_or_garbage_token_counts(judge_settings: Settings) -> None:
    """If the upstream returns nonsense token counts (negative, string,
    null), the judge must coerce them to 0 rather than propagate the
    garbage downstream into cost aggregation."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer_correct": True,
                                    "faithfulness": 0.5,
                                    "reasoning": "ok",
                                }
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": -42,
                    "completion_tokens": "wat",
                    "total_tokens": None,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    verdict = judge_answer(
        question="Q",
        answer="A",
        expected_keywords=[],
        expected_citation="X",
        citations=["X"],
        keyword_fallback_match=True,
        http_client=httpx.Client(transport=transport),
    )

    assert verdict.prompt_tokens == 0
    assert verdict.completion_tokens == 0
    assert verdict.cost_usd == pytest.approx(0.0)
