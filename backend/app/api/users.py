"""User administration (admin only)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.common import audit_async
from app.auth.dependencies import get_db, require_admin
from app.database.models import User
from app.database.schemas import UserOut, UserUpdate
from app.errors import NotFoundError, ValidationFailedError
from app.services import queries

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("", response_model=list[UserOut], summary="List users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[User]:
    return queries.list_users(db)


@router.patch("/{user_id}", response_model=UserOut, summary="Change a user's role or disable an account")
async def update_user(user_id: int, body: UserUpdate, request: Request, admin: User = Depends(require_admin)) -> User:
    db = request.app.state.db

    changes: dict = {}

    def apply() -> User:
        with db.transaction() as s:
            target = s.get(User, user_id)
            if target is None:
                raise NotFoundError("User not found.")
            if body.role is not None and body.role != target.role:
                changes["role"] = [target.role, body.role]
            if body.is_active is not None and body.is_active != target.is_active:
                changes["is_active"] = [target.is_active, body.is_active]
            if target.id == admin.id and (body.role not in (None, "admin") or body.is_active is False):
                raise ValidationFailedError("You cannot remove your own admin access or disable your own account.")
            if body.role is not None:
                target.role = body.role
            if body.is_active is not None and body.is_active != target.is_active:
                target.is_active = body.is_active
                target.token_version += 1          # disabling (or re-enabling) ends existing sessions
            s.flush()
            s.refresh(target)
            return target
    target = await asyncio.to_thread(apply)
    if changes:
        await audit_async(request, "user.updated", user=admin, resource="user", resource_id=target.id,
                          severity="warning", details={"changes": changes})
    manager = request.app.state.ws_manager
    if not target.is_active:
        await manager.close_user(target.id, reason="Account disabled")
    else:
        await manager.update_role(target.id, target.role)
    return target
