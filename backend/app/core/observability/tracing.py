"""Lightweight trace context + optional OTEL bridge (P5.1).

Two layers, separated so the app doesn't hard-depend on
``opentelemetry-sdk`` at import time:

1. **Always-on in-memory trace context.** ``current_trace_id()`` +
   ``trace_span()`` work without any third-party library. The trace_id
   is a deterministic 32-char hex derived from the HTTP ``traceparent``
   header, the ``X-Trace-Id`` header, or (fallback) the ``request_id``.
   This is enough to stitch logs together across FastAPI → Celery →
   audit / agent_event tables.

2. **Optional OTEL bridge.** If ``opentelemetry-sdk`` is installed AND
   ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, ``init_otel_tracer()`` wires
   a real ``TracerProvider`` + OTLP exporter + FastAPI / httpx / Celery
   auto-instrumentation. When either condition fails, the layer is a
   no-op: the in-memory trace context keeps working, nothing crashes.

Design choices
--------------

- **No hard OTEL dependency**: new developers can clone + test without
  having to ``pip install opentelemetry-*``. Production containers add
  the extras (``pip install -e .[otel]``) via the optional extra.
- **Deterministic trace_id**: derived from upstream headers when
  present so ``traceparent`` propagation works across services even
  in the no-op path. Falls back to a new UUID hex when neither header
  is set.
- **Single entry point for business spans**: ``trace_span(name, **attrs)``
  opens a span, attaches attrs, yields, closes. Under the OTEL layer it
  becomes a real span with OTLP export; under the no-op layer it's a
  ContextVar push + log line.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

_log = logging.getLogger(__name__)

# 32-hex-char trace id per W3C traceparent spec.
_TRACE_ID_HEX = re.compile(r"^[0-9a-f]{32}$")
_TRACE_ID_CTX: ContextVar[str | None] = ContextVar("trace_id", default=None)
_TENANT_ID_CTX: ContextVar[str | None] = ContextVar("tenant_id_span", default=None)


# ---------------------------------------------------------------------------
# No-op in-memory trace context (always available)
# ---------------------------------------------------------------------------


def new_trace_id() -> str:
    """Return a fresh 32-hex-char trace id."""
    return uuid4().hex


def extract_trace_id_from_headers(headers: dict[str, str] | Any) -> str:
    """Extract the upstream trace_id from HTTP headers.

    Preference:
    1. W3C ``traceparent`` (format ``00-<trace>-<span>-<flags>``)
    2. ``X-Trace-Id`` (legacy / internal)
    3. New random id

    Returns a normalised 32-char hex — never raises.
    """
    get = headers.get if hasattr(headers, "get") else (lambda _k: None)
    # Case-insensitive: try both cases.
    traceparent = get("traceparent") or get("Traceparent") or ""
    if traceparent:
        parts = traceparent.strip().split("-")
        if len(parts) >= 2 and _TRACE_ID_HEX.match(parts[1] or ""):
            return parts[1]
    x_trace = get("x-trace-id") or get("X-Trace-Id") or ""
    if x_trace and _TRACE_ID_HEX.match(x_trace.strip().lower()):
        return x_trace.strip().lower()
    return new_trace_id()


def set_trace_id(trace_id: str) -> None:
    """Install ``trace_id`` as the current context's trace id."""
    _TRACE_ID_CTX.set(trace_id)


def current_trace_id() -> str | None:
    """Return the current context's trace id, or None."""
    return _TRACE_ID_CTX.get()


def set_tenant_id(tenant_id: str) -> None:
    _TENANT_ID_CTX.set(tenant_id)


def current_tenant_id() -> str | None:
    return _TENANT_ID_CTX.get()


def to_traceparent(trace_id: str | None) -> str | None:
    """Render a W3C ``traceparent`` header from a trace id.

    We don't track span ids at the no-op layer, so we synthesise a fresh
    16-char span id per call. OTEL-backed spans overwrite this via the
    real SDK when present.
    """
    if not trace_id or not _TRACE_ID_HEX.match(trace_id):
        return None
    span_id = uuid4().hex[:16]
    return f"00-{trace_id}-{span_id}-01"


@dataclass
class _SpanHandle:
    """Opaque handle returned by ``trace_span``; callers only use the
    ``set_attr`` method. Under the no-op layer this just accumulates
    attrs into the ``_SpanHandle.attrs`` dict (which we log on exit).
    """

    name: str
    attrs: dict[str, Any]
    _real_span: Any | None = None

    def set_attr(self, key: str, value: Any) -> None:
        self.attrs[key] = value
        if self._real_span is not None:
            try:
                self._real_span.set_attribute(key, value)
            except Exception:
                pass


@contextlib.contextmanager
def trace_span(name: str, **attrs: Any) -> Iterator[_SpanHandle]:
    """Open a named span attached to the current trace.

    Usage::

        with trace_span("answer_policy_question", tenant_id=t) as span:
            span.set_attr("citation_count", len(citations))
            ...

    Under the OTEL layer this becomes a real ``start_as_current_span``;
    otherwise it's a log line on exit + the attrs are available for
    assertion in tests.
    """
    handle = _SpanHandle(name=name, attrs=dict(attrs))
    tracer = _get_tracer_if_ready()
    if tracer is not None:
        real_span_cm = tracer.start_as_current_span(name, attributes=dict(attrs))
        with real_span_cm as real_span:
            handle._real_span = real_span
            for k, v in attrs.items():
                try:
                    real_span.set_attribute(k, v)
                except Exception:
                    pass
            try:
                yield handle
            except Exception as exc:
                try:
                    real_span.record_exception(exc)
                    real_span.set_status(_get_error_status())
                except Exception:
                    pass
                raise
    else:
        try:
            yield handle
        finally:
            if _log.isEnabledFor(logging.DEBUG):
                _log.debug(
                    "trace_span_closed",
                    extra={
                        "span_name": name,
                        "trace_id": current_trace_id(),
                        "attrs": handle.attrs,
                    },
                )


# ---------------------------------------------------------------------------
# Optional OTEL bridge
# ---------------------------------------------------------------------------


_OTEL_READY = False
_OTEL_TRACER: Any | None = None


def _get_tracer_if_ready() -> Any | None:
    """Return the real OTEL tracer when ``init_otel_tracer`` succeeded;
    otherwise None. Reading the module-level flag is cheap — hot paths
    can call this without any perf worry.
    """
    if _OTEL_READY:
        return _OTEL_TRACER
    return None


def _get_error_status() -> Any:
    from opentelemetry.trace import Status, StatusCode

    return Status(StatusCode.ERROR)


def init_otel_tracer(
    *,
    exporter: Any | None = None,
    force: bool = False,
) -> bool:
    """Best-effort OTEL wiring. Returns True when a real tracer is active.

    Call from the FastAPI lifespan. Silently returns False when:
    - ``OTEL_EXPORTER_OTLP_ENDPOINT`` is empty AND no exporter was injected
    - ``opentelemetry-*`` packages aren't installed

    The existing no-op tracing layer continues to work in both cases —
    so we never crash the app on an observability misconfig.

    ``exporter`` (tests / IT): inject a custom ``SpanExporter`` (e.g.
    ``InMemorySpanExporter``) instead of the default OTLP HTTP
    exporter. When provided, the ``OTEL_EXPORTER_OTLP_ENDPOINT`` env
    check is bypassed — the test explicitly opted in.

    ``force`` (tests): re-initialise even if a tracer is already
    registered. Production never sets this.
    """
    global _OTEL_READY, _OTEL_TRACER

    from app.core.config import get_settings

    if _OTEL_READY and not force:
        # Already initialised; don't clobber the existing tracer.
        return True

    settings = get_settings()
    if exporter is None and not settings.otel_exporter_otlp_endpoint:
        _log.info("otel_disabled_no_endpoint")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
        )

        if exporter is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            headers = _parse_otlp_headers(settings.otel_exporter_otlp_headers)
            exporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                headers=headers or None,
            )
            processor = BatchSpanProcessor(exporter)
        else:
            # Injected exporter (tests / IT): use SimpleSpanProcessor so
            # spans are flushed synchronously — tests can assert on the
            # in-memory buffer without a manual flush.
            processor = SimpleSpanProcessor(exporter)
    except ImportError as exc:
        _log.warning(
            "otel_libs_missing",
            extra={
                "hint": (
                    "OTEL_EXPORTER_OTLP_ENDPOINT set but opentelemetry libs "
                    "are not installed. Install the ``.[otel]`` extra "
                    "(``pip install -e .[otel]``) or unset the env var."
                ),
                "error": str(exc),
            },
        )
        return False

    resource = Resource.create(
        {"service.name": settings.otel_service_name, "deployment.environment": settings.app_env}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    _OTEL_TRACER = trace.get_tracer("app.core.observability")
    _OTEL_READY = True
    _log.info(
        "otel_enabled",
        extra={
            "endpoint": settings.otel_exporter_otlp_endpoint,
            "service": settings.otel_service_name,
        },
    )
    return True


def shutdown_otel_tracer() -> None:
    """Flush & shutdown the OTEL provider on app shutdown."""
    global _OTEL_READY, _OTEL_TRACER
    _OTEL_READY = False
    _OTEL_TRACER = None
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if shutdown is not None:
            shutdown()
    except Exception as exc:
        _log.warning("otel_shutdown_failed", extra={"error": str(exc)})


def _parse_otlp_headers(raw: str) -> dict[str, str]:
    """Parse OTLP header env format ``k1=v1,k2=v2`` → dict.

    Tolerates whitespace; silently drops malformed pairs (we don't want
    a missing comma to crash startup — the missing header will just mean
    the collector auth fails, and the operator sees the OTLP exporter
    log that instead).
    """
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        key = k.strip()
        value = v.strip()
        if key:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Convenience for Celery task header propagation
# ---------------------------------------------------------------------------


_CELERY_HEADER_KEY = "x_trace_id"


def celery_task_headers(trace_id: str | None = None) -> dict[str, str]:
    """Build the Celery ``headers`` dict that carries trace state to the
    worker. Pass this to ``task.apply_async(headers=...)``.
    """
    tid = trace_id or current_trace_id()
    if not tid:
        return {}
    return {_CELERY_HEADER_KEY: tid}


def restore_trace_from_celery_headers(headers: dict[str, Any] | None) -> str | None:
    """Restore trace_id on the worker side. Returns the installed id."""
    if not headers:
        return None
    tid = headers.get(_CELERY_HEADER_KEY)
    if isinstance(tid, str) and _TRACE_ID_HEX.match(tid):
        set_trace_id(tid)
        return tid
    return None


__all__ = [
    "celery_task_headers",
    "current_tenant_id",
    "current_trace_id",
    "extract_trace_id_from_headers",
    "init_otel_tracer",
    "new_trace_id",
    "restore_trace_from_celery_headers",
    "set_tenant_id",
    "set_trace_id",
    "shutdown_otel_tracer",
    "to_traceparent",
    "trace_span",
]
