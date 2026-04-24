from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import AuthContext, require_roles
from app.db.session import get_session
from app.schemas.monitoring import MonitoringOverviewResponse
from app.services.monitoring import build_monitoring_overview

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/overview", response_model=MonitoringOverviewResponse)
def get_monitoring_overview(
    _: AuthContext = Depends(require_roles("admin", "operator")),
    session: Session = Depends(get_session),
) -> MonitoringOverviewResponse:
    return build_monitoring_overview(session)
