"""Unit tests for the audit recorder.

Run on SQLite — verifies the helper writes the row, sanitises secret-like
keys, and pulls IP/UA from the request. Cross-tenant isolation of the
audit_log table is covered separately by the integration suite (PG only,
since SQLite has no RLS).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.deps import RequestContext
from app.core.audit import _sanitize, record_audit
from app.db.models.audit_log import AuditLog
from app.db.session import bypass_rls_session, init_db
from tests.conftest import DOCX_CONTENT_TYPE


@pytest.fixture(autouse=True)
def _ensure_schema(_test_environment: None) -> None:
    """Standalone tests don't go through create_app, so trigger schema bootstrap."""
    init_db()


def _ctx(tenant_id: str = "tenant-test", user_id: str = "alice") -> RequestContext:
    return RequestContext(
        request_id="req-xyz",
        tenant_id=tenant_id,
        user_id=user_id,
        role="admin",
        roles=("admin",),
    )


class _StubRequest:
    """Tiny duck for record_audit: only needs .headers and .client.host."""

    def __init__(
        self, ip: str | None = "203.0.113.7", ua: str = "pytest/0", xff: str | None = None
    ) -> None:
        self.headers: dict[str, str] = {}
        if ua:
            self.headers["user-agent"] = ua
        if xff:
            self.headers["x-forwarded-for"] = xff

        class _Client:
            host = ip

        self.client = _Client() if ip else None


def test_sanitize_redacts_secret_like_keys() -> None:
    raw = {
        "api_key": "sk-real-secret",
        "Authorization": "Bearer xyz",
        "user_password": "abc",
        "question_chars": 42,
        "tenant_id": "tenant-a",
    }
    safe = _sanitize(raw)
    assert safe["api_key"] == "***"
    assert safe["Authorization"] == "***"
    assert safe["user_password"] == "***"
    assert safe["question_chars"] == 42
    assert safe["tenant_id"] == "tenant-a"


def test_record_audit_writes_row(client, docx_file: bytes) -> None:
    """End-to-end: real /api/chat/ask call should leave one audit row."""
    upload = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "default-tenant", "customer_id": "default-customer"},
        files={"file": ("policy.docx", docx_file, DOCX_CONTENT_TYPE)},
    )
    assert upload.status_code == 202, upload.text

    response = client.post(
        "/api/chat/ask",
        json={
            "question": "Can I book business class?",
            "tenant_id": "default-tenant",
            "customer_id": "default-customer",
        },
    )
    assert response.status_code == 200, response.text

    # Inspect via bypass session because the test scope spans tenants.
    with bypass_rls_session() as session:
        rows = (
            session.execute(select(AuditLog).where(AuditLog.action == "chat.ask")).scalars().all()
        )
    assert len(rows) >= 1
    last = rows[-1]
    assert last.action == "chat.ask"
    assert last.target_type == "ChatSession"
    assert last.target_id
    assert last.request_id
    assert "question_chars" in last.payload_json
    # And the upload should have left its own audit row.
    with bypass_rls_session() as session:
        upload_rows = (
            session.execute(select(AuditLog).where(AuditLog.action == "knowledge.upload"))
            .scalars()
            .all()
        )
    assert len(upload_rows) >= 1
    assert upload_rows[-1].target_type == "KnowledgeDocument"


def test_record_audit_imperative_call_with_stub_request() -> None:
    """Direct unit test of record_audit: ensures fields populate correctly."""
    with bypass_rls_session() as session:
        ctx = _ctx(tenant_id="tenant-z", user_id="bob")
        request = _StubRequest(ip="198.51.100.42", ua="curl/8")
        row = record_audit(
            session,
            request=request,  # type: ignore[arg-type]
            ctx=ctx,
            action="custom.event",
            target_type="Widget",
            target_id="w-1",
            payload={"detail": "ok", "secret_token": "should-be-redacted"},
        )
        session.commit()
        rid = row.id

        fetched = session.get(AuditLog, rid)
        assert fetched is not None
        assert fetched.tenant_id == "tenant-z"
        assert fetched.user_id == "bob"
        assert fetched.action == "custom.event"
        assert fetched.target_type == "Widget"
        assert fetched.target_id == "w-1"
        assert fetched.ip == "198.51.100.42"
        assert fetched.user_agent == "curl/8"
        assert fetched.payload_json["detail"] == "ok"
        assert fetched.payload_json["secret_token"] == "***"


def test_record_audit_prefers_xff_over_client_host() -> None:
    """X-Forwarded-For first hop wins when proxied behind Nginx/ALB."""
    with bypass_rls_session() as session:
        ctx = _ctx()
        request = _StubRequest(ip="10.0.0.1", xff="203.0.113.99, 10.0.0.5")
        row = record_audit(
            session,
            request=request,  # type: ignore[arg-type]
            ctx=ctx,
            action="proxy.test",
        )
        session.commit()
        assert row.ip == "203.0.113.99"


def test_record_audit_handles_missing_client() -> None:
    with bypass_rls_session() as session:
        ctx = _ctx()
        request = _StubRequest(ip=None, ua="")
        row = record_audit(
            session,
            request=request,  # type: ignore[arg-type]
            ctx=ctx,
            action="anon.test",
        )
        session.commit()
        assert row.ip is None
        assert row.user_agent is None
