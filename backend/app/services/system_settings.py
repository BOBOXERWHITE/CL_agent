from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.system_setting import SystemSetting
from app.db.session import bypass_rls_session
from app.schemas.system_settings import EditableSystemSettings, RuntimeSystemSettings


@dataclass(frozen=True)
class EffectiveBusinessSettings:
    default_tenant_id: str
    default_customer_id: str
    chat_top_k: int
    chat_confidence_threshold: float
    default_eval_dataset: str
    agent_router_provider: str
    chat_history_max_turns: int


def _normalize_router_provider(value: object) -> str:
    """Coerce arbitrary persisted values back into the 3 known strategies.

    A typo'd ``.env`` or a hand-edited DB row should not crash chat — fall
    back to ``keyword`` (the always-on tail of the strategy chain) and
    let the operator fix the value from the page.
    """
    candidate = str(value or "").strip().lower()
    if candidate in {"llm", "embedding", "keyword"}:
        return candidate
    return "keyword"


def _editable_defaults_dict() -> dict[str, object]:
    settings = get_settings()
    return EditableSystemSettings(
        default_tenant_id="default-tenant",
        default_customer_id="default-customer",
        chat_top_k=settings.chat_top_k,
        chat_confidence_threshold=settings.chat_confidence_threshold,
        default_eval_dataset="zh-policy-smoke",
        agent_router_provider=_normalize_router_provider(settings.agent_router_provider),
        chat_history_max_turns=max(0, min(20, int(settings.chat_history_max_turns))),
    ).model_dump()


def _runtime_settings() -> RuntimeSystemSettings:
    settings = get_settings()
    return RuntimeSystemSettings(
        llm_provider=settings.llm_provider,
        llm_model_name=settings.llm_model_name,
        embedding_provider=settings.embedding_provider,
        embedding_model_name=settings.embedding_model_name,
        embedding_dimension=settings.embedding_dimension,
        vector_store_provider=settings.vector_store_provider,
        auth_enabled=settings.auth_enabled,
    )


def get_runtime_settings() -> RuntimeSystemSettings:
    return _runtime_settings()


def get_editable_settings(session: Session) -> EditableSystemSettings:
    merged = _editable_defaults_dict()
    rows = session.execute(select(SystemSetting)).scalars().all()
    for row in rows:
        merged[row.key] = row.value_json.get("value")
    return EditableSystemSettings.model_validate(merged)


def update_editable_settings(
    session: Session,
    payload: EditableSystemSettings,
    *,
    updated_by_role: str,
) -> EditableSystemSettings:
    incoming = payload.model_dump()
    for key, value in incoming.items():
        row = session.get(SystemSetting, key)
        if row is None:
            row = SystemSetting(key=key)
        row.value_json = {"value": value}
        row.updated_by_role = updated_by_role
        session.add(row)

    session.commit()
    return get_editable_settings(session)


def get_effective_business_settings() -> EffectiveBusinessSettings:
    with bypass_rls_session() as session:
        editable = get_editable_settings(session)
    payload = editable.model_dump()
    payload["agent_router_provider"] = _normalize_router_provider(
        payload.get("agent_router_provider")
    )
    return EffectiveBusinessSettings(**payload)
