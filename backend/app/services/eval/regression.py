"""Cross-run regression diff (P3).

Absolute ``quality_gate`` in :mod:`app.services.eval.runner` answers
"is the system above the bar today?". This module answers the
companion question: **"did we regress compared to the last run?"**

Concretely: given the current run's ``metrics_json`` and the previous
run's ``metrics_json`` for the same dataset, produce a per-metric
delta plus a second-tier ``regression_gate`` (pass / warn / fail) that
CI can wire into a PR check.

Design choices worth knowing:

- **Per-metric direction.** Most quality metrics are higher-is-better
  (``judge_answer_correctness``, ``faithfulness``, ``context_precision``,
  …) but a few are inverted (``low_confidence_rate``). The spec table
  encodes this so the rest of the math is symmetric.
- **Threshold per metric.** Defaults to 0.05 absolute, which is the
  empirical noise floor on a 50-question dataset. Customize per metric
  in the spec if you have a sharper measurement (e.g. recall on a
  100-question set).
- **Cost is informational, not gating.** ``judge_cost_usd_total``
  appears in the diff so ops can see the trend, but a cost spike
  never trips ``regression_gate``. Cost vs. quality is an explicit
  business call — the eval shouldn't unilaterally decide.
- **Missing previous values default to 0.** Legacy runs predating
  P0/P1/P2 won't have new metric keys. We surface them as
  ``previous=0.0`` instead of crashing, so the UI can still show
  "this metric is new — current 0.75, no history yet" rather than a
  blank row.

Output shape (``RegressionDiff``) is frozen so consumers can rely on
identity for caching / diff'ing in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# (direction, absolute_threshold)
# direction is one of: "higher_is_better", "lower_is_better", "informational"
_METRIC_SPECS: dict[str, tuple[str, float]] = {
    # Headline quality metrics — included in the regression gate.
    "judge_answer_correctness": ("higher_is_better", 0.05),
    "answer_correctness": ("higher_is_better", 0.05),
    "faithfulness": ("higher_is_better", 0.05),
    "context_precision": ("higher_is_better", 0.05),
    "context_recall": ("higher_is_better", 0.05),
    "retrieval_mrr": ("higher_is_better", 0.05),
    "citation_hit_rate": ("higher_is_better", 0.05),
    "low_confidence_rate": ("lower_is_better", 0.05),
    # Cost — surfaced in deltas but never gates the build.
    "judge_cost_usd_total": ("informational", 0.0),
}

# A single >15-percentage-point cliff on one metric escalates straight
# to fail even when only one metric regressed. Multi-metric regressions
# (>=2) escalate to fail at the lower threshold. Single small (1-15pp)
# regression on one metric → warn.
_FAIL_HARD_DELTA = 0.15


@dataclass(frozen=True)
class MetricDelta:
    """Per-metric comparison entry.

    ``delta = current - previous`` (signed). The interpretation of the
    sign depends on ``direction`` — use the ``regressed`` boolean for
    the answer the UI / CI actually want.
    """

    name: str
    current: float
    previous: float
    delta: float
    direction: str
    regressed: bool
    threshold: float


@dataclass(frozen=True)
class RegressionDiff:
    """Cross-run comparison summary.

    ``has_previous`` is False on the first run for a dataset; consumers
    should suppress the regression UI in that case. ``deltas`` is always
    populated when ``has_previous`` is True, with one entry per tracked
    metric so the UI can render a stable table.
    """

    has_previous: bool
    previous_run_id: str | None
    deltas: list[MetricDelta] = field(default_factory=list)
    regression_gate: str = "pass"
    regression_reasons: list[str] = field(default_factory=list)


def _coerce_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _is_regression(*, delta: float, direction: str, threshold: float) -> bool:
    if direction == "higher_is_better":
        return delta < -threshold
    if direction == "lower_is_better":
        return delta > threshold
    return False  # informational metrics never count as a regression


def _build_metric_delta(
    name: str, current: dict[str, object], previous: dict[str, object]
) -> MetricDelta:
    direction, threshold = _METRIC_SPECS[name]
    cur = _coerce_float(current.get(name))
    prev = _coerce_float(previous.get(name))
    delta = cur - prev
    return MetricDelta(
        name=name,
        current=cur,
        previous=prev,
        delta=delta,
        direction=direction,
        regressed=_is_regression(delta=delta, direction=direction, threshold=threshold),
        threshold=threshold,
    )


def _build_gate(deltas: list[MetricDelta]) -> tuple[str, list[str]]:
    """Pass / warn / fail rules:
    - no regressions     → pass
    - single regression, |delta| <= _FAIL_HARD_DELTA → warn
    - any regression with |delta| > _FAIL_HARD_DELTA → fail
    - two or more regressions → fail
    """
    regressed = [d for d in deltas if d.regressed]
    if not regressed:
        return "pass", []

    reasons = [
        f"{d.name}: {d.previous:.4f} → {d.current:.4f} (Δ {d.delta:+.4f})" for d in regressed
    ]

    if len(regressed) >= 2:
        return "fail", reasons
    only = regressed[0]
    if abs(only.delta) > _FAIL_HARD_DELTA:
        return "fail", reasons
    return "warn", reasons


def compute_regression_diff(
    *,
    current: dict[str, object],
    previous: dict[str, object] | None,
    previous_run_id: str | None = None,
) -> RegressionDiff:
    """Compare the current eval metrics with the previous run's metrics.

    Passing ``previous=None`` returns an empty pass-state diff — useful
    on the very first run for a dataset where the regression UI should
    be suppressed.
    """
    if previous is None:
        return RegressionDiff(
            has_previous=False,
            previous_run_id=None,
            deltas=[],
            regression_gate="pass",
            regression_reasons=[],
        )

    deltas = [_build_metric_delta(name, current, previous) for name in _METRIC_SPECS]
    gate, reasons = _build_gate(deltas)
    return RegressionDiff(
        has_previous=True,
        previous_run_id=previous_run_id,
        deltas=deltas,
        regression_gate=gate,
        regression_reasons=reasons,
    )


__all__ = ["MetricDelta", "RegressionDiff", "compute_regression_diff"]
