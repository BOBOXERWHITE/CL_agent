"""LLM-driven ReAct planner for :mod:`app.services.agents.policy_graph`.

Replaces the hardcoded "if no observations call ``policy_search`` else
finalize" decision with a real LLM-driven plan. This is the missing
piece that turns the existing ReAct scaffold (plan → act → observe →
plan ...) into actual ReAct as described in Yao et al. 2022 — the LLM
reasons about the task each cycle and chooses a tool from the
registered allow-list (or finalizes when evidence is sufficient).

Three guardrails sit between the LLM and the tool runner:

1. **Off by default** — ``settings.agent_react_llm_enabled`` is False
   in fresh deployments, so the planner returns the legacy hardcoded
   verdict and zero LLM tokens are spent. Every existing policy_graph
   test passes unchanged with the flag off.
2. **Fail-soft** — any HTTP / parse / schema error falls through to
   the hardcoded fallback verdict and sets ``fallback_used=True``.
   The observability layer surfaces "planner fell back N of M
   cycles" so operators know when the LLM is unreliable, instead of
   one bad response crashing the whole question.
3. **Tool-name allow-list** — the planner refuses to forward an
   ``action=call_tool`` with a tool name that is not in the supplied
   ``available_tools`` catalog. LLMs hallucinate tool names; that
   path would crash the tool runner downstream.

The output ``PlanResponse`` is frozen so callers cannot accidentally
mutate the verdict between the plan node and the act node.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.core.config import get_settings
from app.core.observability.agent_tracing import llm_span

_log = logging.getLogger(__name__)

# Clamp written-to-DB fields so a single chatty LLM cycle cannot
# explode AgentRun row sizes. 1024 chars is roughly 250 Chinese chars,
# enough to capture genuine reasoning without storing essays.
_THOUGHT_MAX_CHARS = 1024
_REASON_MAX_CHARS = 512

_REACT_SYSTEM_PROMPT = """\
你是一名严谨的 ReAct 规划者。每一轮你都拿到：
- 用户的原始问题
- 过去几轮你说过的 thoughts
- 过去几轮工具调用的 observations
- 当前可用的工具清单（名称 + 简述）
- 剩余可用步数

你需要输出严格 JSON，描述下一步动作：

{
  "thought": "<不超过 200 字，用中文写明你下一步的推理>",
  "action": "call_tool" | "finalize",
  "tool":    "<如果 action=call_tool，必须是工具清单里的 name；否则省略>",
  "tool_args": { ... }   // 工具的额外参数，可省略
}

规则：
- 不要解释、不要附加 markdown 包裹，只输出顶层 JSON 对象。
- 如果已掌握足够证据回答，立即 action=finalize 避免浪费 LLM 配额。
- 工具名必须**完全**来自工具清单；编造的名字会被拒绝并回退。
- 如果不确定，优先 call_tool 拿更多证据，但不要循环超过剩余步数。
"""


@dataclass(frozen=True)
class PlanResponse:
    """The verdict returned by :func:`plan_next_action`.

    ``fallback_used=True`` means the planner could not produce or
    validate an LLM verdict and reverted to the legacy hardcoded plan.
    Aggregators report this rate so operators can decide whether the
    LLM judge is worth the cost on a per-deployment basis.
    """

    action: Literal["call_tool", "finalize"]
    tool: str | None
    tool_args: dict[str, Any] = field(default_factory=dict)
    thought: str = ""
    fallback_used: bool = False


def _hardcoded_fallback(observations: list[dict[str, Any]], reason: str) -> PlanResponse:
    """Matches the pre-Phase-B behaviour of ``policy_graph._plan_node``
    bit-for-bit so toggling the flag off or hitting an LLM error never
    changes user-visible answers.
    """
    if not observations:
        return PlanResponse(
            action="call_tool",
            tool="policy_search",
            tool_args={},
            thought=f"[fallback] {reason}"[:_REASON_MAX_CHARS],
            fallback_used=True,
        )
    return PlanResponse(
        action="finalize",
        tool=None,
        tool_args={},
        thought=f"[fallback] {reason}"[:_REASON_MAX_CHARS],
        fallback_used=True,
    )


def _build_user_prompt(
    *,
    question: str,
    observations: list[dict[str, Any]],
    thoughts: list[str],
    available_tools: list[dict[str, Any]],
    max_steps: int,
    current_step: int,
) -> str:
    tools_block = (
        "\n".join(
            f"- {tool.get('name', '?')}: {tool.get('description', '(no description)')}"
            for tool in available_tools
        )
        if available_tools
        else "(无可用工具)"
    )
    observations_block = (
        "\n".join(
            f"#{idx + 1} tool={obs.get('tool', '?')} output={json.dumps(obs.get('output'), ensure_ascii=False)[:400]}"
            for idx, obs in enumerate(observations)
        )
        if observations
        else "(尚无观察结果)"
    )
    thoughts_block = (
        "\n".join(f"#{idx + 1} {thought[:240]}" for idx, thought in enumerate(thoughts))
        if thoughts
        else "(尚无历史思考)"
    )
    remaining = max(0, max_steps - current_step)
    return (
        f"原始问题：{question}\n"
        f"剩余可用步数：{remaining}（已用 {current_step}）\n"
        f"可用工具：\n{tools_block}\n"
        f"历史 thoughts：\n{thoughts_block}\n"
        f"历史 observations：\n{observations_block}"
    )


def _parse_llm_payload(content: str) -> dict[str, Any] | None:
    """Tolerate ``` fenced JSON wrappers + leading 'json' language tags."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _validate_and_normalize(
    raw: dict[str, Any], available_tool_names: set[str]
) -> PlanResponse | None:
    """Apply schema + tool-allow-list. Returns None on any violation
    so the caller can decide to fall back."""
    action = raw.get("action")
    if action not in {"call_tool", "finalize"}:
        return None
    thought = str(raw.get("thought") or "")[:_THOUGHT_MAX_CHARS]
    if action == "finalize":
        return PlanResponse(
            action="finalize",
            tool=None,
            tool_args={},
            thought=thought,
            fallback_used=False,
        )
    tool = raw.get("tool")
    if not isinstance(tool, str) or tool not in available_tool_names:
        # Hallucinated or omitted tool name → reject so caller falls back.
        return None
    tool_args = raw.get("tool_args") or {}
    if not isinstance(tool_args, dict):
        tool_args = {}
    return PlanResponse(
        action="call_tool",
        tool=tool,
        tool_args=tool_args,
        thought=thought,
        fallback_used=False,
    )


def plan_next_action(
    *,
    question: str,
    observations: list[dict[str, Any]],
    thoughts: list[str],
    available_tools: list[dict[str, Any]],
    max_steps: int,
    current_step: int,
    http_client: httpx.Client | None = None,
) -> PlanResponse:
    """Decide whether to call a tool or finalize.

    When the LLM is disabled / misconfigured / fails / returns garbage
    the function returns a fallback verdict marked
    ``fallback_used=True``. Callers MUST treat the verdict's
    ``action`` as authoritative; the ``fallback_used`` flag is purely
    informational (aggregate as ``planner_fallback_rate`` in metrics).
    """
    available_tool_names = {str(tool.get("name")) for tool in available_tools if tool.get("name")}
    settings = get_settings()
    if not settings.agent_react_llm_enabled:
        return _hardcoded_fallback(observations, "agent_react_llm_enabled is False")
    if settings.llm_provider != "openai-compatible" or not (
        settings.llm_api_base_url and settings.llm_api_key
    ):
        return _hardcoded_fallback(
            observations, "planner requires an openai-compatible LLM gateway"
        )

    client = http_client or httpx.Client(timeout=20.0)
    user_prompt = _build_user_prompt(
        question=question,
        observations=observations,
        thoughts=thoughts,
        available_tools=available_tools,
        max_steps=max_steps,
        current_step=current_step,
    )

    # P8: emit an LLM span so Phoenix / LangSmith / Jaeger can plot the
    # planner's per-cycle latency + token usage + cost separately from
    # the surrounding agent / react_step spans.
    with llm_span(
        purpose="react_plan",
        model_name=settings.llm_model_name,
        provider=settings.llm_provider,
        **{"llm.current_step": current_step},
    ) as span:
        try:
            response = client.post(
                f"{settings.llm_api_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model_name,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": _REACT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
            content = str(payload["choices"][0]["message"]["content"])
            # Token + cost attribution lives on the span so dashboards
            # can aggregate by purpose/agent/tenant without parsing logs.
            usage = payload.get("usage") or {}
            if usage:
                span.set_attr("llm.token_count.prompt", int(usage.get("prompt_tokens", 0)))
                span.set_attr("llm.token_count.completion", int(usage.get("completion_tokens", 0)))
                span.set_attr("llm.token_count.total", int(usage.get("total_tokens", 0)))
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            _log.warning("react_planner LLM call failed: %s", exc, exc_info=False)
            span.set_attr("llm.error", f"{type(exc).__name__}: {exc}")
            return _hardcoded_fallback(observations, f"LLM call failed: {type(exc).__name__}")

    parsed = _parse_llm_payload(content)
    if parsed is None:
        return _hardcoded_fallback(observations, "LLM returned non-JSON payload")

    verdict = _validate_and_normalize(parsed, available_tool_names)
    if verdict is None:
        return _hardcoded_fallback(observations, "LLM verdict failed schema validation")
    return verdict


__all__ = ["PlanResponse", "plan_next_action"]
