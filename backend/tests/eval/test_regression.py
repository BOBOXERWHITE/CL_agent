"""Unit tests for the cross-run regression diff (P3).

The ``quality_gate`` in :mod:`app.services.eval.runner` decides pass /
warn / fail against absolute thresholds — "answer_correctness >= 80%".
That's useful for an initial bar but useless as a regression detector:
a run that dropped from 95% to 81% still passes the absolute gate, and
the team that just shipped a worse retriever has no idea.

The regression diff compares the current run with the *previous* run of
the same dataset and flags any metric that dropped (or rose, for
lower-is-better metrics) by more than its threshold. Output feeds a
second-tier ``regression_gate`` (pass / warn / fail) that CI can wire
into PR checks.

Invariants under test:

1. **First run has no diff.** When no previous run exists we return
   ``has_previous=False`` with empty deltas and a neutral ``"pass"``
   gate — better than crashing or hand-waving.
2. **Direction matters.** ``low_confidence_rate`` going UP is a
   regression; ``judge_answer_correctness`` going DOWN is a regression.
3. **Marginal noise is forgiven.** A 0.01 swing on a 0.05-threshold
   metric is not a regression — eval datasets have noise floors and
   we'd burn out the team chasing them.
4. **Cost is informational only.** ``judge_cost_usd_total`` is included
   in the diff but never triggers the regression gate; cost trade-offs
   are an explicit ops conversation, not a quality regression.
5. **Missing previous metric is treated as zero.** Legacy runs from
   before P0/P1/P2 don't have the new metric keys; we want a
   ``previous=0.0`` row rather than a crash so the team can see "this
   was added since last time".
"""

from __future__ import annotations

import pytest

from app.services.eval.regression import (
    MetricDelta,
    RegressionDiff,
    compute_regression_diff,
)


def test_no_previous_returns_empty_diff() -> None:
    diff = compute_regression_diff(
        current={"judge_answer_correctness": 0.8},
        previous=None,
    )

    assert diff.has_previous is False
    assert diff.deltas == []
    assert diff.regression_gate == "pass"
    assert diff.regression_reasons == []
    assert diff.previous_run_id is None


def test_all_metrics_improve_passes() -> None:
    diff = compute_regression_diff(
        current={
            "judge_answer_correctness": 0.85,
            "faithfulness": 0.9,
            "context_precision": 0.7,
            "context_recall": 0.95,
            "retrieval_mrr": 0.8,
            "citation_hit_rate": 0.95,
            "low_confidence_rate": 0.05,
            "judge_cost_usd_total": 0.05,
        },
        previous={
            "judge_answer_correctness": 0.6,
            "faithfulness": 0.7,
            "context_precision": 0.5,
            "context_recall": 0.7,
            "retrieval_mrr": 0.6,
            "citation_hit_rate": 0.8,
            "low_confidence_rate": 0.2,
            "judge_cost_usd_total": 0.04,
        },
        previous_run_id="run-A",
    )

    assert diff.has_previous is True
    assert diff.previous_run_id == "run-A"
    assert diff.regression_gate == "pass"
    assert all(not d.regressed for d in diff.deltas)


def test_judge_correctness_drop_triggers_regression() -> None:
    diff = compute_regression_diff(
        current={"judge_answer_correctness": 0.6},
        previous={"judge_answer_correctness": 0.85},
    )

    correctness = next(d for d in diff.deltas if d.name == "judge_answer_correctness")
    assert correctness.regressed is True
    assert correctness.delta == pytest.approx(-0.25)
    assert correctness.direction == "higher_is_better"
    assert diff.regression_gate == "fail"
    assert any("judge_answer_correctness" in reason for reason in diff.regression_reasons)


def test_low_confidence_rate_rise_is_a_regression() -> None:
    """Inverted-direction metric: low_confidence_rate going UP is bad."""
    diff = compute_regression_diff(
        current={"low_confidence_rate": 0.35},
        previous={"low_confidence_rate": 0.10},
    )

    lcr = next(d for d in diff.deltas if d.name == "low_confidence_rate")
    assert lcr.regressed is True
    assert lcr.direction == "lower_is_better"
    assert lcr.delta == pytest.approx(0.25)


def test_marginal_change_below_threshold_is_not_regression() -> None:
    # default threshold is 0.05 for headline metrics; a 0.01 wobble
    # is signal-of-noise territory.
    diff = compute_regression_diff(
        current={"judge_answer_correctness": 0.79},
        previous={"judge_answer_correctness": 0.80},
    )

    correctness = next(d for d in diff.deltas if d.name == "judge_answer_correctness")
    assert correctness.regressed is False
    assert diff.regression_gate == "pass"


def test_single_marginal_regression_warns_not_fails() -> None:
    """A single 0.06 drop (just over threshold) on a single metric is
    warn-worthy but not a CI-block. Two or more regressed metrics OR a
    single >0.15 cliff escalates to fail."""
    diff = compute_regression_diff(
        current={"judge_answer_correctness": 0.74},
        previous={"judge_answer_correctness": 0.80},
    )

    assert diff.regression_gate == "warn"


def test_two_regressions_fail() -> None:
    diff = compute_regression_diff(
        current={
            "judge_answer_correctness": 0.70,
            "context_precision": 0.55,
        },
        previous={
            "judge_answer_correctness": 0.80,
            "context_precision": 0.75,
        },
    )

    assert diff.regression_gate == "fail"
    assert len(diff.regression_reasons) >= 2


def test_cost_is_informational_only() -> None:
    """A 10x cost spike does NOT trip the regression gate — cost is an
    ops conversation, not a quality regression. Still surfaced in deltas."""
    diff = compute_regression_diff(
        current={"judge_cost_usd_total": 1.50},
        previous={"judge_cost_usd_total": 0.10},
    )

    assert diff.regression_gate == "pass"
    cost = next(d for d in diff.deltas if d.name == "judge_cost_usd_total")
    assert cost.delta == pytest.approx(1.40)
    # cost metric MUST NOT be marked as regressed even though it ballooned
    assert cost.regressed is False


def test_missing_previous_metric_treated_as_zero() -> None:
    """A legacy previous-run row without judge_answer_correctness still
    yields a delta entry with previous=0 so the UI can render it."""
    diff = compute_regression_diff(
        current={"judge_answer_correctness": 0.75},
        previous={"answer_correctness": 0.70},  # judge metric was not tracked yet
    )

    correctness = next(d for d in diff.deltas if d.name == "judge_answer_correctness")
    assert correctness.previous == pytest.approx(0.0)
    assert correctness.current == pytest.approx(0.75)
    # Going from 0 → 0.75 is an "improvement", not a regression
    assert correctness.regressed is False


def test_metric_delta_is_immutable() -> None:
    delta = MetricDelta(
        name="x",
        current=0.5,
        previous=0.4,
        delta=0.1,
        direction="higher_is_better",
        regressed=False,
        threshold=0.05,
    )
    with pytest.raises((AttributeError, TypeError)):
        delta.regressed = True  # type: ignore[misc]


def test_regression_diff_is_immutable() -> None:
    diff = RegressionDiff(
        has_previous=False,
        previous_run_id=None,
        deltas=[],
        regression_gate="pass",
        regression_reasons=[],
    )
    with pytest.raises((AttributeError, TypeError)):
        diff.has_previous = True  # type: ignore[misc]


def test_diff_includes_all_tracked_metric_keys() -> None:
    """Even when current/previous only carry a subset, the diff should
    enumerate every tracked metric so the UI can lay out a stable
    table without missing-row holes."""
    diff = compute_regression_diff(
        current={"judge_answer_correctness": 0.8},
        previous={"judge_answer_correctness": 0.7},
    )

    delta_names = {d.name for d in diff.deltas}
    # Headline quality metrics plus the (informational) cost metric.
    expected = {
        "judge_answer_correctness",
        "answer_correctness",
        "faithfulness",
        "context_precision",
        "context_recall",
        "retrieval_mrr",
        "citation_hit_rate",
        "low_confidence_rate",
        "judge_cost_usd_total",
    }
    assert expected.issubset(delta_names)
