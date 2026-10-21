"""Audit log (admin only): filterable history of user actions and pipeline actions."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_admin
from app.database.models import User
from app.database.schemas import AuditLogPage, Severity, Stream, page_meta
from app.services import queries

router = APIRouter(prefix="/api/audit-logs", tags=["Audit log"])


@router.get("", response_model=AuditLogPage, summary="Audit entries, newest first (admin)")
def list_audit_logs(
    db: Session = Depends(get_db), _: User = Depends(require_admin),
    action: str | None = Query(None, max_length=61, pattern=r"^[a-z_.]+\*?$",
                               description="Exact action, or a prefix ending in * (e.g. model.*)"),
    user_id: int | None = Query(None, ge=1), system: bool | None = Query(None, description="true = pipeline actions only"),
    resource: str | None = Query(None, max_length=40, pattern=r"^[a-z_]+$"), severity: Severity | None = None,
    stream: Stream | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
) -> dict:
    items, total = queries.list_audit_logs(db, page=page, page_size=page_size, action=action, user_id=user_id,
                                           resource=resource, severity=severity, stream=stream,
                                           date_from=date_from, date_to=date_to, system=system)
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/facets", summary="Values available for the audit filters (admin)")
def audit_facets(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    return queries.audit_facets(db)
