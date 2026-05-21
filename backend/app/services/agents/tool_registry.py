"""Tool system foundation (P3.5).

Design rationale
================

The pre-Phase-3 ``tools.py`` was a plain module of free functions. That
works for a demo but misses three things real agent systems need:

1. **Typed I/O**. The LLM (in ReAct) needs to know the shape of each
   tool's input; without a schema, you end up prompt-engineering
   "please return JSON in this format" and praying. Pydantic gives us
   one source of truth for (a) LLM prompt docs, (b) runtime validation,
   (c) generated OpenAPI if we ever expose tools over HTTP.

2. **Discoverability**. The Router (P3.2) and the Plan node (P3.3) need
   to enumerate available tools at runtime ("what can I call?") without
   hard-coding names. A Registry provides that by-name lookup plus a
   listing API.

3. **Clean separation** between *what a tool does* (this file's
   ``Tool``) and *how to call it safely* (``tool_runner.py``'s retry /
   timeout / circuit-breaker policy). Each tool stays small and pure;
   cross-cutting failure handling lives exactly once.

The Tool interface is deliberately boring: one ``invoke`` method taking
a Pydantic model, returning a Pydantic model. No async; network-bound
tools bring their own timeout via httpx or similar. The Runner layer
adds retries / circuit breaking on top.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel


class Tool(ABC):
    """Base class every tool implementation extends.

    Subclasses set ``name`` / ``description`` / ``input_model`` /
    ``output_model`` as class attributes, and implement ``invoke``.

    Why ABC instead of Protocol: we want ``isinstance(x, Tool)`` checks
    to work (the Registry uses them to reject bad registrations) and we
    want ``@abstractmethod`` to force subclasses to implement invoke.
    Protocol can't enforce either at class creation time.
    """

    # Subclasses MUST override all four. We use ClassVar so these are
    # shared across instances (one Tool subclass = one "kind of tool").
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]
    risk_level: ClassVar[str] = "low"
    requires_approval: ClassVar[bool] = False
    idempotency_scope: ClassVar[str] = "request"

    @abstractmethod
    def invoke(self, payload: BaseModel) -> BaseModel:
        """Execute the tool. Receives a validated ``input_model`` instance.

        Return an ``output_model`` instance. Raise any exception on
        failure; the Runner wraps it into a ToolCallRecord.
        """

    @classmethod
    def describe(cls) -> dict[str, object]:
        """Machine-readable tool card for the Router / Plan prompt.

        The LLM sees a concise JSON blob; Pydantic's
        ``model_json_schema`` gives us input / output schemas for free.
        """
        return {
            "name": cls.name,
            "description": cls.description,
            "risk_level": cls.risk_level,
            "requires_approval": cls.requires_approval,
            "idempotency_scope": cls.idempotency_scope,
            "input_schema": cls.input_model.model_json_schema(),
            "output_schema": cls.output_model.model_json_schema(),
        }


class ToolNotRegistered(KeyError):
    """Raised when a tool name is looked up that wasn't registered."""


class ToolRegistryConflict(ValueError):
    """Raised when two tools try to register under the same ``name``."""


class ToolRegistry:
    """In-process registry of Tool instances, keyed by ``Tool.name``.

    Registries are cheap to instantiate, so tests can make private ones
    and prod uses ``_DEFAULT_REGISTRY``. The ``get`` / ``list`` /
    ``describe_all`` API is intentionally small -- the Registry does
    lookups only; policy (retry, circuit) lives on the Runner.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool, *, replace: bool = False) -> None:
        """Register ``tool`` under its class ``name``.

        Setting ``replace=True`` swaps an existing registration; useful
        in tests for injecting fakes. Production callers leave it at
        False so a duplicate name is a configuration bug, not a silent
        overwrite.
        """
        if not isinstance(tool, Tool):
            raise TypeError(f"expected Tool instance, got {type(tool).__name__}")
        name = tool.name
        if not name:
            raise ValueError("tool.name must be a non-empty string")
        if name in self._tools and not replace:
            raise ToolRegistryConflict(
                f"tool {name!r} already registered; pass replace=True to override"
            )
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotRegistered(f"tool {name!r} is not registered") from exc

    def has(self, name: str) -> bool:
        return name in self._tools

    def list(self) -> list[Tool]:
        """Return the registered tools in insertion order."""
        return list(self._tools.values())

    def describe_all(self) -> list[dict[str, object]]:
        """One ``Tool.describe`` dict per registered tool."""
        return [type(tool).describe() for tool in self._tools.values()]

    def clear(self) -> None:
        """Drop every registration. Primarily for test isolation."""
        self._tools.clear()


# ---------------------------------------------------------------------------
# Process-wide default registry
# ---------------------------------------------------------------------------
#
# Tools register themselves into this singleton at import time (see the
# bottom of ``tools.py``). Anything that needs to look up tools imports
# this module's ``get_default_registry`` helper rather than reaching
# into this variable directly; that gives us a seam to swap in a test
# fixture or a dev/prod split later.

_DEFAULT_REGISTRY = ToolRegistry()


def get_default_registry() -> ToolRegistry:
    return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Drop every registered tool in the default registry. Test-only."""
    _DEFAULT_REGISTRY.clear()


__all__ = [
    "Tool",
    "ToolNotRegistered",
    "ToolRegistry",
    "ToolRegistryConflict",
    "get_default_registry",
    "reset_default_registry",
]
