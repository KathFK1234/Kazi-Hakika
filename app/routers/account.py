"""Settings, export and permanent deletion of everything a user owns."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.deps import AuthDep, SettingsDep, SystemDb, UserDb, enforce
from app.models import Application, User
from app.routers.auth import clear_session_cookie
from app.services.ratelimit import Limit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/account", tags=["account"])

EXPORT_PER_USER = Limit("export", 10, 3600)
DELETE_PER_USER = Limit("delete-account", 5, 3600)


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reminder_opt_in: bool


class DeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_handle: str = Field(max_length=30)


@router.patch("/settings")
def update_settings(body: SettingsIn, auth: AuthDep, db: SystemDb) -> dict[str, bool]:
    user = db.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    user.reminder_opt_in = body.reminder_opt_in
    db.commit()
    return {"reminder_opt_in": user.reminder_opt_in}


def build_export(system_db: SystemDb, user_db: UserDb, auth: AuthDep) -> dict[str, Any]:
    user = system_db.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    apps = user_db.scalars(
        select(Application)
        .where(Application.user_id == auth.user_id)
        .options(selectinload(Application.events))
        .order_by(Application.created_at)
    ).all()
    return {
        "format": "kazi-hakika-export/1",
        "exported_at": datetime.now(UTC).isoformat(),
        "account": {
            "email": user.email,
            "handle": user.handle,
            "created_at": user.created_at.isoformat(),
            "email_verified_at": _iso(user.email_verified_at),
            "reminder_opt_in": user.reminder_opt_in,
        },
        "applications": [
            {
                "id": str(a.id),
                "role_title": a.role_title,
                "company_name": a.company_name,
                "job_url": a.job_url,
                "source": a.source,
                "stage": a.stage,
                "deadline": _iso(a.deadline),
                "applied_on": _iso(a.applied_on),
                "salary_note": a.salary_note,
                "notes": a.notes,
                "created_at": a.created_at.isoformat(),
                "updated_at": a.updated_at.isoformat(),
                "stage_history": [
                    {"from": e.from_stage, "to": e.to_stage, "at": e.at.isoformat()}
                    for e in a.events
                ],
            }
            for a in apps
        ],
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("/export")
def export(request: Request, auth: AuthDep, db: SystemDb, user_db: UserDb) -> Response:
    enforce(request, EXPORT_PER_USER, str(auth.user_id))
    data = build_export(db, user_db, auth)
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="kazi-hakika-export-{day}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: DeleteIn,
    request: Request,
    response: Response,
    auth: AuthDep,
    db: SystemDb,
    settings: SettingsDep,
) -> Response:
    enforce(request, DELETE_PER_USER, str(auth.user_id))
    user = db.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    if body.confirm_handle.strip().lower() != user.handle:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Type your handle exactly to confirm."
        )
    # Foreign keys cascade to applications, stage events, sessions and tokens.
    db.execute(delete(User).where(User.id == auth.user_id))
    db.commit()
    log.info("account deleted")
    clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
