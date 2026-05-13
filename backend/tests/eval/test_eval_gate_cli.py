"""Tests for the eval_gate CLI (P4 / CI integration).

This CLI is the wire between an EvalRun's ``metrics_json`` and a CI
job's exit code. Given a JSON file containing one EvalRun's metrics,
the CLI:

  - reads ``quality_gate`` (absolute thresholds) and the nested
    ``regression.regression_gate`` (cross-run drift) values
  - prints a one-screen markdown summary to stdout
  - exits 0 when both gates are "pass" / missing / unknown
  - exits 2 when either gate is "warn" (configurable via `--strict`)
  - exits 1 when either gate is "fail"

The contract is deliberately tiny so the same script can run anywhere
that has Python and a metrics JSON: GitHub Actions, GitLab CI, a
locally-piped curl response, etc. No HTTP client, no DB.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval_gate_cli.py"


def _run_cli(payload: dict, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI with the payload piped to stdin."""
    return subprocess.run(
        [sys.executable, str(CLI_PATH), "--stdin", *args],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_cli_with_file(
    payload: dict, tmp_path: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(CLI_PATH), str(metrics_path), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_zero_when_both_gates_pass() -> None:
    result = _run_cli(
        {
            "quality_gate": "pass",
            "regression": {
                "has_previous": True,
                "regression_gate": "pass",
            },
        }
    )
    assert result.returncode == 0
    assert "PASS" in result.stdout


def test_cli_exit_one_when_quality_gate_fails() -> None:
    result = _run_cli(
        {
            "quality_gate": "fail",
            "quality_gate_reasons": ["答案正确率低于 80%"],
            "regression": {"has_previous": False, "regression_gate": "pass"},
        }
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "答案正确率低于 80%" in result.stdout


def test_cli_exit_one_when_regression_gate_fails() -> None:
    result = _run_cli(
        {
            "quality_gate": "pass",
            "regression": {
                "has_previous": True,
                "previous_run_id": "abc",
                "regression_gate": "fail",
                "regression_reasons": [
                    "judge_answer_correctness: 0.85 → 0.62 (Δ -0.23)",
                ],
            },
        }
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "judge_answer_correctness" in result.stdout


def test_cli_exit_two_when_only_warn_default_is_pass(tmp_path: Path) -> None:
    """Without --strict, a 'warn' on either gate exits 0 (advisory)."""
    result = _run_cli_with_file(
        {
            "quality_gate": "warn",
            "quality_gate_reasons": ["低置信度占比高于 20%"],
            "regression": {"has_previous": True, "regression_gate": "pass"},
        },
        tmp_path,
    )
    assert result.returncode == 0
    assert "WARN" in result.stdout


def test_cli_strict_flag_converts_warn_to_failure(tmp_path: Path) -> None:
    """--strict turns warn into exit code 2 so PRs can be merged-with-care."""
    result = _run_cli_with_file(
        {
            "quality_gate": "warn",
            "regression": {"has_previous": True, "regression_gate": "pass"},
        },
        tmp_path,
        "--strict",
    )
    assert result.returncode == 2
    assert "WARN" in result.stdout


def test_cli_treats_missing_regression_block_as_pass() -> None:
    """Legacy persisted runs predating P3 won't carry a regression block.
    The CLI must not crash on them."""
    result = _run_cli({"quality_gate": "pass"})
    assert result.returncode == 0
    assert "PASS" in result.stdout


def test_cli_treats_first_run_no_previous_as_pass() -> None:
    """has_previous=False on the very first run for a dataset is normal —
    nothing to compare against, so it can't be a regression."""
    result = _run_cli(
        {
            "quality_gate": "pass",
            "regression": {
                "has_previous": False,
                "regression_gate": "pass",
            },
        }
    )
    assert result.returncode == 0


def test_cli_reads_payload_from_file_arg(tmp_path: Path) -> None:
    """The CLI accepts a positional file path so CI configs can save the
    metrics JSON as an artifact and reference it later."""
    result = _run_cli_with_file({"quality_gate": "pass"}, tmp_path)
    assert result.returncode == 0


def test_cli_handles_invalid_json_with_clear_error(tmp_path: Path) -> None:
    metrics_path = tmp_path / "broken.json"
    metrics_path.write_text("{this isn't json", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(CLI_PATH), str(metrics_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert result.returncode != 1  # not gate-fail; should be a usage error
    assert "JSON" in (result.stderr or result.stdout)


def test_cli_prints_token_and_cost_summary_when_present() -> None:
    """P2 cost info should appear in the summary even when both gates pass —
    ops people want to see what they spent."""
    result = _run_cli(
        {
            "quality_gate": "pass",
            "judge_cost_usd_total": 0.0042,
            "judge_prompt_tokens_total": 3200,
            "judge_completion_tokens_total": 800,
            "regression": {"has_previous": False, "regression_gate": "pass"},
        }
    )
    assert result.returncode == 0
    assert "$0.0042" in result.stdout
    assert "3200" in result.stdout or "3,200" in result.stdout


def test_cli_outputs_github_step_summary_format_when_env_var_set(tmp_path: Path) -> None:
    """When ``GITHUB_STEP_SUMMARY`` env var points to a file, the CLI
    appends the same markdown summary to it (Actions native UX)."""
    summary_path = tmp_path / "github_step_summary.md"
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "quality_gate": "pass",
                "regression": {"has_previous": False, "regression_gate": "pass"},
            }
        ),
        encoding="utf-8",
    )

    env = {
        **{k: v for k, v in subprocess.os.environ.items() if k != "GITHUB_STEP_SUMMARY"},
        "GITHUB_STEP_SUMMARY": str(summary_path),
    }
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), str(metrics_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0
    assert summary_path.exists()
    content = summary_path.read_text(encoding="utf-8")
    assert "PASS" in content


@pytest.mark.parametrize("gate_value", ["pass", "warn", "fail"])
def test_cli_summary_always_includes_both_gate_labels(gate_value: str) -> None:
    """No matter the outcome, the summary must surface both gate values
    so the reader doesn't have to re-read the JSON to know which gate
    triggered the exit code."""
    result = _run_cli(
        {
            "quality_gate": gate_value,
            "regression": {"has_previous": True, "regression_gate": "pass"},
        }
    )
    assert "Quality Gate" in result.stdout
    assert "Regression Gate" in result.stdout
