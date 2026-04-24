"""PII redaction regex layer (P7.2).

Kept deliberately simple: regex-based; no LLM assist, no language
detection. The goal is "don't leak obvious PII into logs / audit /
(optionally) chat responses" — not "bulletproof compliance". A real
compliance program layers a vetted commercial tool on top.

Patterns
--------

Each rule has a name (used in the placeholder) and a regex. Order
matters for overlapping patterns — longer / more specific first so
e.g. we don't mask a bank card as part of a phone number.

- ``EMAIL``:     RFC-5322 light
- ``PHONE_CN``:  11-digit mainland China mobile (``1[3-9]xxxxxxxxx``)
- ``PHONE_US``:  ``(NNN) NNN-NNNN`` / ``NNN-NNN-NNNN`` / ``+1 NNN...``
- ``ID_CN``:     18-digit mainland China ID (last digit may be ``X``)
- ``BANK_CARD``: 13-19 consecutive digits with optional spaces/dashes
- ``PASSPORT``:  letter + 7-8 digits (generic; narrower than real spec)

Unknown text stays untouched — redaction is strictly additive.

Knobs
-----

- ``GUARDRAILS_PII_ENABLED=true|false`` (default true). Test harness
  can set false to exercise code without worrying about accidental
  triggers on sample data like ``admin@example.com``.
- Per-call bypass: pass ``force=False`` to ``redact_text`` to opt out
  even when globally enabled (the user-supplied chat response path
  uses this to only redact when the caller asks).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]
    placeholder: str


# IMPORTANT: longer / more specific patterns first.
_RULES: tuple[RedactionRule, ...] = (
    RedactionRule(
        name="EMAIL",
        pattern=re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
        placeholder="[EMAIL]",
    ),
    RedactionRule(
        name="ID_CN",
        # Chinese resident ID card: 17 digits + checksum (0-9 or X).
        pattern=re.compile(
            r"\b[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"
        ),
        placeholder="[ID]",
    ),
    RedactionRule(
        name="PASSPORT",
        # Generic: 1-2 letters + 7-8 digits. Narrow to uppercase to
        # avoid catching regular words like ``E12345678`` inside an
        # all-lowercase sentence.
        pattern=re.compile(r"\b[A-Z]{1,2}\d{7,8}\b"),
        placeholder="[PASSPORT]",
    ),
    RedactionRule(
        name="BANK_CARD",
        # 13-19 digits, allow space / dash separators every 4.
        pattern=re.compile(r"\b(?:\d[ \-]?){13,19}\b"),
        placeholder="[CARD]",
    ),
    RedactionRule(
        name="PHONE_CN",
        pattern=re.compile(r"\b1[3-9]\d{9}\b"),
        placeholder="[PHONE]",
    ),
    RedactionRule(
        name="PHONE_US",
        # +1 (212) 555-1212 / 212-555-1212 / 212 555 1212
        pattern=re.compile(r"(?:\+?1[ \-]?)?\(?\d{3}\)?[ \-]?\d{3}[ \-]?\d{4}\b"),
        placeholder="[PHONE]",
    ),
)


def _enabled() -> bool:
    """Read the global feature flag at call time (not import time) so
    tests using ``monkeypatch.setenv`` flip it cleanly.
    """
    raw = os.getenv("GUARDRAILS_PII_ENABLED", "true").strip().lower()
    return raw not in ("false", "0", "no", "")


def redact_text(text: str, *, force: bool | None = None) -> str:
    """Return ``text`` with all matched PII replaced by placeholders.

    ``force`` (default None = follow env flag):
    - ``True`` — always redact regardless of env
    - ``False`` — never redact regardless of env
    - ``None`` — honour ``GUARDRAILS_PII_ENABLED``
    """
    if not text:
        return text
    if force is False:
        return text
    if force is None and not _enabled():
        return text
    out = text
    for rule in _RULES:
        out = rule.pattern.sub(rule.placeholder, out)
    return out


def has_pii(text: str) -> bool:
    """Detection-only variant; returns True if any rule matches."""
    if not text:
        return False
    return any(rule.pattern.search(text) for rule in _RULES)


def redact_payload(payload: dict | None) -> dict | None:
    """Apply :func:`redact_text` to every string value in a dict.

    Used by log / audit sinks that carry loosely-typed payloads. We do
    NOT recurse into nested dicts / lists by default (too aggressive;
    callers who need it can walk the tree themselves). Non-string
    values stay as-is.
    """
    if payload is None:
        return None
    return {
        key: (redact_text(value) if isinstance(value, str) else value)
        for key, value in payload.items()
    }


__all__ = [
    "RedactionRule",
    "has_pii",
    "redact_payload",
    "redact_text",
]
