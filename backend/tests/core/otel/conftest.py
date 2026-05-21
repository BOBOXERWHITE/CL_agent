"""Shared OTEL fixture for ``tests/core/test_*`` modules.

OTEL's ``trace.set_tracer_provider`` is process-global and one-shot:
the SECOND call (even from a different test module) silently keeps the
ORIGINAL provider. So if each test module owns its own
``InMemorySpanExporter`` + calls ``init_otel_tracer(exporter=...)`` at
module scope, whichever module gets imported first wins — spans from
later-imported modules' tests flow into the first module's exporter and
the assertions see empty buffers.

This conftest sits at the ``tests/core/`` boundary and owns one shared
``InMemorySpanExporter`` for the whole session. Both
``test_otel_export.py`` and ``test_agent_tracing.py`` request the
``otel_exporter`` fixture below; the buffer is cleared between tests
so each test sees only its own spans.
"""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.core.observability import tracing

_OTEL_TEST_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="session", autouse=True)
def _otel_session_setup():
    """Initialise the OTEL SDK with a shared in-memory exporter once per
    pytest session. Subsequent ``init_otel_tracer`` calls (from legacy
    module-scope fixtures) are no-ops because the global provider is
    already set; tests just share this exporter via the fixture below."""
    tracing.init_otel_tracer(exporter=_OTEL_TEST_EXPORTER, force=True)
    yield
    tracing.shutdown_otel_tracer()


@pytest.fixture()
def otel_exporter() -> InMemorySpanExporter:
    """Buffer-cleared in-memory exporter, shared across modules."""
    _OTEL_TEST_EXPORTER.clear()
    return _OTEL_TEST_EXPORTER
