"""CLI wire between an EvalRun's metrics JSON and a CI job's exit code.

Usage:
    # From a saved metrics JSON file:
    python -m scripts.eval_gate_cli metrics.json

    # From stdin (curl response, pipe, etc.):
    curl -s api/evals/runs/$ID | jq .metrics | \
      python -m scripts.eval_gate_cli --stdin

    # Strict mode: treat warn as failure (exit 2).
    python -m scripts.eval_gate_cli --strict metrics.json

Exit codes:
    0  — both quality_gate and regression_gate are pass / absent / unknown
    1  — either gate is "fail"
    2  — either gate is "warn" *and* --strict is supplied

The script also writes the same markdown summary to ``$GITHUB_STEP_SUMMARY``
when that env var is set, so GitHub Actions renders it natively as a
job summary card without any extra YAML.

No HTTP, no DB — runs anywhere Python 3.10+ runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Final, NoReturn

# Anything beyond these three is unknown territory; we treat unknown as
# pass to avoid blocking a PR on a typo in a third-party metric source.
_PASS: Final = "pass"
_WARN: Final = "warn"
_FAIL: Final = "fail"

# Exit code for invalid / unreadable input. BSD sysexits.h convention:
# 64 = EX_USAGE. Distinct from 1 (gate fail) and 2 (warn + strict) so
# CI can tell "broken upload" apart from "real regression".
_EX_USAGE: Final = 64


def _exit_usage(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    sys.exit(_EX_USAGE)


def _load_payload(path: str | None, use_stdin: bool) -> dict[str, Any]:
    if use_stdin:
        raw = sys.stdin.read()
    else:
        if path is None:
            _exit_usage("provide a metrics JSON path or --stdin (run with --help)")
        with open(path, encoding="utf-8") as handle:  # type: ignore[arg-type]
            raw = handle.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _exit_usage(f"failed to parse JSON: {exc.msg}")
    if not isinstance(payload, dict):  # type: ignore[possibly-unbound]
        _exit_usage("metrics JSON must be a JSON object")
    return payload  # type: ignore[return-value]


def _extract_gate_values(payload: dict[str, Any]) -> tuple[str, list[str], str, list[str], bool]:
    """Pull both gate values + reasons out of the metrics payload.

    Returns ``(quality_gate, quality_reasons, regression_gate, regression_reasons, has_previous)``.
    Missing keys default to "pass" so legacy persisted runs (predating P0/P3)
    flow through cleanly.
    """
    quality_gate = str(payload.get("quality_gate") or _PASS).lower()
    quality_reasons = [str(reason) for reason in payload.get("quality_gate_reasons") or []]
    regression_block = payload.get("regression") or {}
    if not isinstance(regression_block, dict):
        regression_block = {}
    regression_gate = str(regression_block.get("regression_gate") or _PASS).lower()
    regression_reasons = [
        str(reason) for reason in regression_block.get("regression_reasons") or []
    ]
    has_previous = bool(regression_block.get("has_previous", False))
    return quality_gate, quality_reasons, regression_gate, regression_reasons, has_previous


def _aggregate_headline(quality_gate: str, regression_gate: str) -> str:
    """Combine the two gate values into a single human-readable headline.

    Fail beats warn beats pass — the headline always reflects the worst
    signal regardless of strict mode, so the markdown summary tells the
    truth even when the exit code stays at 0 (advisory warn)."""
    if quality_gate == _FAIL or regression_gate == _FAIL:
        return "FAIL"
    if quality_gate == _WARN or regression_gate == _WARN:
        return "WARN"
    return "PASS"


def _decide_exit_code(headline: str, *, strict: bool) -> int:
    """Map the headline plus strict mode to a CI exit code.

    - FAIL → exit 1 (always)
    - WARN → exit 0 by default, 2 when --strict
    - PASS → exit 0
    """
    if headline == "FAIL":
        return 1
    if headline == "WARN" and strict:
        return 2
    return 0


def _format_cost_summary(payload: dict[str, Any]) -> list[str]:
    """Cost / token block — only emitted when at least one number is set,
    so legacy runs without P2 don't get an empty section."""
    prompt_tokens = int(payload.get("judge_prompt_tokens_total") or 0)
    completion_tokens = int(payload.get("judge_completion_tokens_total") or 0)
    cost_usd = float(payload.get("judge_cost_usd_total") or 0.0)
    if prompt_tokens == 0 and completion_tokens == 0 and cost_usd == 0.0:
        return []
    return [
        "",
        "### LLM Judge Cost",
        "",
        f"- Prompt tokens: **{prompt_tokens:,}**",
        f"- Completion tokens: **{completion_tokens:,}**",
        f"- Total cost: **${cost_usd:.4f}**",
    ]


def _format_summary(
    payload: dict[str, Any],
    quality_gate: str,
    quality_reasons: list[str],
    regression_gate: str,
    regression_reasons: list[str],
    has_previous: bool,
    headline: str,
) -> str:
    """One-screen markdown summary, friendly to ``$GITHUB_STEP_SUMMARY``."""
    lines: list[str] = [
        f"# Eval Gate: {headline}",
        "",
        f"- Quality Gate: **{quality_gate}**",
        f"- Regression Gate: **{regression_gate}** "
        + (
            f"(vs previous run `{payload.get('regression', {}).get('previous_run_id') or '?'}`)"
            if has_previous
            else "(no previous run for comparison)"
        ),
    ]
    if quality_reasons:
        lines += ["", "## Quality Gate Reasons", ""]
        lines += [f"- {reason}" for reason in quality_reasons]
    if regression_reasons:
        lines += ["", "## Regression Gate Reasons", ""]
        lines += [f"- {reason}" for reason in regression_reasons]
    lines += _format_cost_summary(payload)
    lines += [""]
    return "\n".join(lines)


def _maybe_append_to_github_step_summary(summary: str) -> None:
    """If running inside GitHub Actions, also write to the job-summary file
    so the rich markdown shows up under the workflow run page."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(summary)
        if not summary.endswith("\n"):
            handle.write("\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval-gate",
        description=(
            "Check an eval run's quality_gate + regression_gate against pass/"
            "warn/fail and exit non-zero on regression."
        ),
    )
    parser.add_argument(
        "metrics_path",
        nargs="?",
        help="Path to a JSON file containing an EvalRun's metrics block.",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read the JSON payload from stdin instead of a file.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat 'warn' on either gate as a failure (exit 2).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = _load_payload(args.metrics_path, args.stdin)
    quality_gate, quality_reasons, regression_gate, regression_reasons, has_previous = (
        _extract_gate_values(payload)
    )
    headline = _aggregate_headline(quality_gate, regression_gate)
    exit_code = _decide_exit_code(headline, strict=args.strict)
    summary = _format_summary(
        payload,
        quality_gate,
        quality_reasons,
        regression_gate,
        regression_reasons,
        has_previous,
        headline,
    )
    sys.stdout.write(summary)
    _maybe_append_to_github_step_summary(summary)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
