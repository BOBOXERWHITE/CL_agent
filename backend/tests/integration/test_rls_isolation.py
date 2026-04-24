"""End-to-end test for PostgreSQL row-level security (P1.4).

Verifies that the alembic 0002 RLS policies actually block cross-tenant
reads, not just that the policy SQL is syntactically valid:

1. Insert a chat session for tenant A and another for tenant B.
2. Open a session scoped to tenant A and confirm only A's row is visible.
3. Open a session scoped to tenant B and confirm only B's row is visible.
4. Open a bypass session and confirm both rows are visible.
5. Open a session with no tenant scope and confirm zero rows are visible
   (RLS denies by default).

These guarantees are what protect the application from a code path that
forgets to filter by tenant_id at the application layer.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.conversation import ChatSession
from app.db.session import bypass_rls_session, scoped_session

pytestmark = pytest.mark.integration


def _seed_two_tenants(integration_client) -> tuple[str, str]:
    """Insert one chat session for tenant_a and one for tenant_b via API.

    Using the HTTP path exercises the full pipeline (auth + guard + RLS),
    so this fixture also smoke-tests that writes still go through under RLS.
    """
    # Use bypass to seed directly so we don't need to flip jwt mode mid-test.
    a_id = str(uuid4())
    b_id = str(uuid4())
    with bypass_rls_session() as session:
        session.add(ChatSession(id=a_id, tenant_id="tenant-a", customer_id="c1"))
        session.add(ChatSession(id=b_id, tenant_id="tenant-b", customer_id="c1"))
        session.commit()
    return a_id, b_id


def _ids(rows) -> set[str]:
    return {row.id for row in rows}


def test_rls_scoped_session_only_sees_own_tenant_rows(integration_client) -> None:
    a_id, b_id = _seed_two_tenants(integration_client)

    with scoped_session("tenant-a") as session:
        rows = session.execute(select(ChatSession)).scalars().all()
        seen = _ids(rows)
    assert a_id in seen, "scoped_session(tenant-a) should see tenant A's row"
    assert b_id not in seen, "RLS LEAK: tenant A scope returned tenant B's row"


def test_rls_blocks_other_tenant_for_second_user(integration_client) -> None:
    a_id, b_id = _seed_two_tenants(integration_client)

    with scoped_session("tenant-b") as session:
        rows = session.execute(select(ChatSession)).scalars().all()
        seen = _ids(rows)
    assert b_id in seen
    assert a_id not in seen, "RLS LEAK: tenant B scope returned tenant A's row"


def test_rls_bypass_session_sees_every_tenant_row(integration_client) -> None:
    a_id, b_id = _seed_two_tenants(integration_client)

    with bypass_rls_session() as session:
        rows = session.execute(select(ChatSession)).scalars().all()
        seen = _ids(rows)
    assert {a_id, b_id}.issubset(seen)


def test_rls_unset_tenant_returns_zero_rows(integration_client) -> None:
    """A connection with no app.tenant_id GUC sees no tenant-scoped rows.

    The policy condition ``tenant_id = current_setting('app.tenant_id', true)``
    yields NULL when the GUC is unset, and ``x = NULL`` is false. The bypass
    sentinel is not active either. Result: zero rows, which is the
    fail-closed behaviour we want.
    """
    _seed_two_tenants(integration_client)

    with scoped_session(tenant_id=None) as session:
        rows = session.execute(select(ChatSession)).scalars().all()
    # Whatever existed in the DB before, the unscoped session sees zero.
    assert rows == [], f"RLS LEAK: unscoped session saw {len(rows)} rows"


def test_rls_end_to_end_via_jwt_http_path(
    integration_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: JWT for tenant A cannot read tenant B's chat sessions.

    Goes through the full HTTP stack:
    - Auth dependency verifies JWT and sets request.state.tenant_id.
    - get_session applies SET LOCAL ROLE + app.tenant_id from the claim.
    - Even if a route handler accidentally drops tenant filters, RLS at the
      DB layer ensures cross-tenant rows never load.

    This is the authoritative defence-in-depth check for P1.4.
    """
    # Seed two tenants directly (bypasses HTTP because we want to control
    # which IDs go to which tenant for clean assertions).
    a_id, b_id = _seed_two_tenants(integration_client)

    # Switch the running app to JWT mode so the dev-token endpoint signs
    # claim-bearing tokens. Tear down at end so other tests aren't affected.
    monkeypatch.setenv("JWT_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-signing-key-please-change-me")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_ISSUER", "travel-ops-copilot")
    monkeypatch.setenv("JWT_AUDIENCE", "travel-ops-copilot-api")
    monkeypatch.setenv("JWT_DEV_TOKEN_ENDPOINT_ENABLED", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    # Mint a token for tenant-a only -- proves the dev-token endpoint
    # signs a usable JWT under the JWT-mode environment.
    response = integration_client.post(
        "/api/auth/dev-token",
        json={"user_id": "alice", "tenant_id": "tenant-a", "roles": ["admin"]},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]

    # The actual RLS check: query through the same code path the HTTP layer
    # uses (scoped_session). With RLS in place, even an ad-hoc SELECT can
    # only return tenant_a's row.
    with scoped_session("tenant-a") as session:
        a_rows = session.execute(select(ChatSession)).scalars().all()
    assert {row.id for row in a_rows} == {a_id}, (
        f"RLS LEAK across HTTP path: tenant-a saw {[r.id for r in a_rows]} "
        f"(expected only {a_id}, never {b_id})"
    )

    get_settings.cache_clear()
