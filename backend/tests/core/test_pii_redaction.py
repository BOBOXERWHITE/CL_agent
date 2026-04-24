"""P7.2: PII regex redaction unit tests."""

from __future__ import annotations

import pytest

from app.core.guardrails.redaction import (
    has_pii,
    redact_payload,
    redact_text,
)


@pytest.fixture(autouse=True)
def _enable_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUARDRAILS_PII_ENABLED", "true")


# ---------------------------------------------------------------------------
# Pattern coverage
# ---------------------------------------------------------------------------


def test_redacts_email() -> None:
    assert redact_text("please contact user.name+tag@sub.example.com") == ("please contact [EMAIL]")


def test_redacts_cn_mobile_number() -> None:
    assert redact_text("call me at 13812345678") == "call me at [PHONE]"


def test_redacts_us_phone_formats() -> None:
    for raw in (
        "(212) 555-1212",
        "212-555-1212",
        "+1 212 555 1212",
    ):
        out = redact_text(raw)
        assert "[PHONE]" in out, f"{raw!r} → {out!r}"


def test_redacts_cn_id() -> None:
    # Validly formatted (18-char) mainland ID — last char X to exercise
    # the trailing-checksum branch.
    out = redact_text("身份证号 11010519491231002X 请核对")
    assert "[ID]" in out
    assert "11010519491231002X" not in out


def test_redacts_bank_card() -> None:
    out = redact_text("card 4111 1111 1111 1111 used for payment")
    assert "[CARD]" in out


def test_redacts_passport() -> None:
    out = redact_text("passport E12345678 expires 2030")
    assert "[PASSPORT]" in out


def test_multiple_pii_in_one_string() -> None:
    raw = "email admin@example.com or call 13812345678"
    out = redact_text(raw)
    assert "[EMAIL]" in out
    assert "[PHONE]" in out
    assert "admin@example.com" not in out
    assert "13812345678" not in out


def test_no_pii_text_returned_unchanged() -> None:
    raw = "什么是差旅报销政策？"
    assert redact_text(raw) == raw


def test_empty_and_none_safe() -> None:
    assert redact_text("") == ""


def test_has_pii_detection_only() -> None:
    assert has_pii("邮箱 foo@bar.com") is True
    assert has_pii("hello world") is False
    assert has_pii("") is False


# ---------------------------------------------------------------------------
# Flag / override behaviour
# ---------------------------------------------------------------------------


def test_disabled_when_env_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUARDRAILS_PII_ENABLED", "false")
    # admin@example.com passes through because flag is off.
    assert redact_text("admin@example.com") == "admin@example.com"


def test_force_true_overrides_disabled_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUARDRAILS_PII_ENABLED", "false")
    assert redact_text("admin@example.com", force=True) == "[EMAIL]"


def test_force_false_overrides_enabled_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUARDRAILS_PII_ENABLED", "true")
    assert redact_text("admin@example.com", force=False) == "admin@example.com"


# ---------------------------------------------------------------------------
# redact_payload
# ---------------------------------------------------------------------------


def test_redact_payload_processes_string_values() -> None:
    payload = {
        "question": "联系邮箱 user@example.com",
        "tenant_id": "t1",  # no PII, unchanged
        "count": 5,  # non-string, unchanged
    }
    out = redact_payload(payload)
    assert "[EMAIL]" in out["question"]
    assert out["tenant_id"] == "t1"
    assert out["count"] == 5


def test_redact_payload_none_returns_none() -> None:
    assert redact_payload(None) is None


# ---------------------------------------------------------------------------
# audit.py integration
# ---------------------------------------------------------------------------


def test_audit_sanitize_redacts_pii_in_string_values() -> None:
    """P7.2: the audit sanitize pass should now redact PII in value
    strings, not just mask known-sensitive keys."""
    from app.core.audit import _sanitize

    out = _sanitize(
        {
            "password": "super-secret",  # key-based mask → ***
            "question": "call 13812345678",  # value-based redaction → [PHONE]
            "neutral": "policy info",
        }
    )
    assert out["password"] == "***"
    assert "[PHONE]" in out["question"]
    assert out["neutral"] == "policy info"
