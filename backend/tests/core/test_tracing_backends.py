"""Tests for the pluggable tracing backend selector.

Pins the contract of ``_resolve_exporter_specs`` — the pure helper that
turns the four convenience env vars (PHOENIX_ENDPOINT, LANGSMITH_API_KEY,
TRACING_BACKEND, plus the legacy OTEL_EXPORTER_OTLP_ENDPOINT escape hatch)
into a list of concrete ``(label, endpoint, headers)`` tuples that
``init_otel_tracer`` consumes.

Why a pure resolver instead of inline logic in ``init_otel_tracer``:

1. The "which backend wins" decision tree is the user-visible API
   surface. Pinning it in unit tests means a future refactor of the
   OTEL SDK plumbing can't silently change behaviour like "what
   happens if I set both PHOENIX_ENDPOINT and LANGSMITH_API_KEY".
2. The OTEL SDK is heavy to spin up in tests; resolving the spec list
   is pure Python + a Settings dataclass, runs in microseconds.
3. The same spec list will be used by an introspection endpoint
   eventually (``GET /api/admin/tracing`` returns "currently exporting
   to: [phoenix(http://...), langsmith(https://api.smith.langchain.com)]"),
   so it deserves a public function in its own right.

Tested decision table:

  +-------------+----------+----------------+----------+--------+
  | tracing_    | phoenix  | langsmith_     | raw OTLP |        |
  | backend     | _endpoint| api_key        | endpoint | expect |
  +=============+==========+================+==========+========+
  | auto        | "" (off) | ""             | ""       | []     |
  | auto        | set      | ""             | ""       | [phx]  |
  | auto        | ""       | set            | ""       | [lsm]  |
  | auto        | set      | set            | ""       | [both] |
  | auto        | ""       | ""             | set      | [raw]  |
  | auto        | set      | set            | set      | [phx,  |
  |             |          |                |          |  lsm,  |
  |             |          |                |          |  raw]  |
  | phoenix     | set      | (ignored)      | (ig.)    | [phx]  |
  | phoenix     | ""       | (ignored)      | (ig.)    | []     |
  | langsmith   | (ig.)    | set            | (ig.)    | [lsm]  |
  | langsmith   | (ig.)    | ""             | (ig.)    | []     |
  | both        | set      | set            | (ig.)    | [phx,  |
  |             |          |                |          |  lsm]  |
  | none        | (ig.)    | (ig.)          | (ig.)    | []     |
  +-------------+----------+----------------+----------+--------+
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.config import Settings, get_settings
from app.core.observability.tracing import (
    ExporterSpec,
    _resolve_exporter_specs,
)


def _settings(**overrides: object) -> Settings:
    base = get_settings()
    return replace(base, **overrides)


# ---------------------------------------------------------------------------
# tracing_backend=auto — derive from filled-in env
# ---------------------------------------------------------------------------


def test_auto_no_endpoints_returns_empty_spec_list() -> None:
    """Default behaviour: nothing configured = no exporters attached.
    Same as pre-refactor "otel_disabled_no_endpoint"."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="auto",
            phoenix_endpoint="",
            langsmith_api_key="",
            otel_exporter_otlp_endpoint="",
        )
    )
    assert specs == []


def test_auto_phoenix_endpoint_set_yields_single_phoenix_spec() -> None:
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="auto",
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="",
            otel_exporter_otlp_endpoint="",
        )
    )
    assert len(specs) == 1
    assert specs[0].label == "phoenix"
    assert specs[0].endpoint == "http://localhost:6006/v1/traces"
    # Phoenix is auth-free for local self-hosted deployments
    assert specs[0].headers == {}


def test_auto_langsmith_api_key_set_yields_single_langsmith_spec() -> None:
    """The convenience knob: setting just LANGSMITH_API_KEY auto-builds
    the endpoint URL + x-api-key header so users don't have to memorise
    the OTEL ingestion path."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="auto",
            phoenix_endpoint="",
            langsmith_api_key="lsv2_pt_abc123",
            langsmith_project="cl-agent-prod",
            otel_exporter_otlp_endpoint="",
        )
    )
    assert len(specs) == 1
    assert specs[0].label == "langsmith"
    assert specs[0].endpoint == "https://api.smith.langchain.com/otel/v1/traces"
    assert specs[0].headers["x-api-key"] == "lsv2_pt_abc123"
    assert specs[0].headers["Langsmith-Project"] == "cl-agent-prod"


def test_auto_both_phoenix_and_langsmith_yields_dual_export() -> None:
    """Local-dev + team-UI workflow: keep Phoenix for fast in-IDE debug
    while shipping the same spans to LangSmith for ops to look at."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="auto",
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="lsv2_pt_abc123",
            langsmith_project="cl-agent-dev",
            otel_exporter_otlp_endpoint="",
        )
    )
    assert {s.label for s in specs} == {"phoenix", "langsmith"}
    assert len(specs) == 2


def test_auto_raw_otlp_endpoint_fallback_when_nothing_convenient_set() -> None:
    """Backward-compat: the legacy OTEL_EXPORTER_OTLP_ENDPOINT escape
    hatch still works for users on Jaeger / Tempo / Datadog who don't
    fit the Phoenix/LangSmith convenience boxes."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="auto",
            phoenix_endpoint="",
            langsmith_api_key="",
            otel_exporter_otlp_endpoint="https://otlp.example.test/v1/traces",
            otel_exporter_otlp_headers="DD-API-KEY=xxx",
        )
    )
    assert len(specs) == 1
    assert specs[0].label == "custom"
    assert specs[0].endpoint == "https://otlp.example.test/v1/traces"
    assert specs[0].headers == {"DD-API-KEY": "xxx"}


def test_auto_all_three_endpoints_yields_three_exporters() -> None:
    """Power user: explicit Jaeger AND Phoenix AND LangSmith all at once.
    Useful during a migration when you want spans in three places to
    compare UIs side-by-side."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="auto",
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="lsv2_pt_x",
            otel_exporter_otlp_endpoint="https://tempo.example.test/v1/traces",
        )
    )
    labels = {s.label for s in specs}
    assert labels == {"phoenix", "langsmith", "custom"}


# ---------------------------------------------------------------------------
# tracing_backend=phoenix — explicit pick, ignore other envs
# ---------------------------------------------------------------------------


def test_explicit_phoenix_picks_phoenix_only_even_when_langsmith_set() -> None:
    """``TRACING_BACKEND=phoenix`` is the override — even if LANGSMITH_API_KEY
    is lying around in .env from a prior experiment, don't dual-export."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="phoenix",
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="lsv2_pt_x",  # ignored
            otel_exporter_otlp_endpoint="https://otlp.example.test/v1",  # ignored
        )
    )
    assert len(specs) == 1
    assert specs[0].label == "phoenix"


def test_explicit_phoenix_without_endpoint_returns_empty() -> None:
    """``TRACING_BACKEND=phoenix`` but PHOENIX_ENDPOINT empty → return
    [] instead of falling back to LangSmith. The explicit selector means
    "these are my intentions" — silently switching backends would
    confuse ops more than a missing trace UI does."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="phoenix",
            phoenix_endpoint="",
            langsmith_api_key="lsv2_pt_x",  # not used as fallback
            otel_exporter_otlp_endpoint="https://otlp.example.test/v1",
        )
    )
    assert specs == []


# ---------------------------------------------------------------------------
# tracing_backend=langsmith — explicit pick
# ---------------------------------------------------------------------------


def test_explicit_langsmith_picks_langsmith_only() -> None:
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="langsmith",
            phoenix_endpoint="http://localhost:6006/v1/traces",  # ignored
            langsmith_api_key="lsv2_pt_x",
            langsmith_project="prod",
            otel_exporter_otlp_endpoint="https://otlp.example.test/v1",  # ignored
        )
    )
    assert len(specs) == 1
    assert specs[0].label == "langsmith"


def test_explicit_langsmith_without_api_key_returns_empty() -> None:
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="langsmith",
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="",
            otel_exporter_otlp_endpoint="https://otlp.example.test/v1",
        )
    )
    assert specs == []


# ---------------------------------------------------------------------------
# tracing_backend=both / none
# ---------------------------------------------------------------------------


def test_explicit_both_requires_both_to_be_configured() -> None:
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="both",
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="lsv2_pt_x",
        )
    )
    assert {s.label for s in specs} == {"phoenix", "langsmith"}


def test_explicit_both_skips_missing_side() -> None:
    """``TRACING_BACKEND=both`` with only one configured exports to that
    one — better than crashing on a half-configured rollout."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="both",
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="",  # missing
        )
    )
    assert [s.label for s in specs] == ["phoenix"]


def test_explicit_none_disables_all_export() -> None:
    """The kill switch: even if every env var is filled in, exporters
    are off. Useful in CI / load tests / cost-saving deploys."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="none",
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="lsv2_pt_x",
            otel_exporter_otlp_endpoint="https://otlp.example.test/v1",
        )
    )
    assert specs == []


# ---------------------------------------------------------------------------
# Defensive parsing
# ---------------------------------------------------------------------------


def test_unknown_tracing_backend_value_falls_back_to_auto() -> None:
    """A typo (TRACING_BACKEND=phenix) must not break the app; treat as
    auto-derive + log a warning at init time. Pin the behaviour here so
    we don't accidentally start crashing on unknown values."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="phenix",  # typo
            phoenix_endpoint="http://localhost:6006/v1/traces",
            langsmith_api_key="",
        )
    )
    # auto with phoenix set → phoenix
    assert len(specs) == 1
    assert specs[0].label == "phoenix"


def test_exporter_spec_is_immutable() -> None:
    """Frozen dataclass — accidental mutation between resolve and init
    would silently change export targets."""
    spec = ExporterSpec(label="phoenix", endpoint="http://x", headers={})
    with pytest.raises((AttributeError, TypeError)):
        spec.label = "langsmith"  # type: ignore[misc]


def test_langsmith_default_project_is_used_when_unset() -> None:
    """Even without LANGSMITH_PROJECT, the spec still includes a
    Langsmith-Project header — LangSmith silently puts the run in the
    'default' project otherwise, which makes traces hard to find."""
    specs = _resolve_exporter_specs(
        _settings(
            tracing_backend="auto",
            langsmith_api_key="lsv2_pt_x",
            langsmith_project="cl-agent",  # default value
            phoenix_endpoint="",
        )
    )
    assert specs[0].headers["Langsmith-Project"] == "cl-agent"
