from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import AuthContext, require_roles
from app.db.session import get_session
from app.schemas.system_settings import EditableSystemSettings, SystemSettingsResponse
from app.services.system_settings import (
    get_editable_settings,
    get_runtime_settings,
    update_editable_settings,
)

router = APIRouter(prefix="/api/settings", tags=["system-settings"])


@router.get("/system", response_model=SystemSettingsResponse)
def get_system_settings(
    _: AuthContext = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> SystemSettingsResponse:
    return SystemSettingsResponse(
        editable_settings=get_editable_settings(session),
        runtime_settings=get_runtime_settings(),
    )


@router.put("/system", response_model=SystemSettingsResponse)
def put_system_settings(
    payload: EditableSystemSettings,
    auth_context: AuthContext = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> SystemSettingsResponse:
    editable = update_editable_settings(
        session,
        payload,
        updated_by_role=auth_context.role,
    )
    return SystemSettingsResponse(
        editable_settings=editable,
        runtime_settings=get_runtime_settings(),
    )
