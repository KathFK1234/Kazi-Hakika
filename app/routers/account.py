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
from app.models import Application, BoardRole, Checkin, Entry, Report, User, UserSession
from app.services.digest import today_eat, upcoming
from app.services.ratelimit import Limit
from app.services.sessions import clear_session_cookie

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
    # Board posts otherwise stay up, shown as posted by "deleted-user".
    remove_posts: bool = False


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
    posts = user_db.scalars(
        select(BoardRole).where(BoardRole.posted_by == auth.user_id).order_by(BoardRole.created_at)
    ).all()
    reports = user_db.execute(
        select(Report.board_role_id, Report.reason, Report.note, Report.created_at)
        .where(Report.reported_by == auth.user_id)
        .order_by(Report.created_at)
    ).all()
    checkins = user_db.scalars(
        select(Checkin).where(Checkin.user_id == auth.user_id).order_by(Checkin.on_date)
    ).all()
    entries = user_db.scalars(
        select(Entry).where(Entry.user_id == auth.user_id).order_by(Entry.happened_on)
    ).all()
    sign_ins = system_db.execute(
        select(UserSession.created_at, UserSession.expires_at)
        .where(UserSession.user_id == auth.user_id)
        .order_by(UserSession.created_at)
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
            "checkin_interval_weeks": user.checkin_interval_weeks,
            "next_checkin_on": _iso(user.next_checkin_on),
            "weekly_target": user.weekly_target,
        },
        # When each current sign-in started and ends (no tokens).
        "sign_ins": [
            {"created_at": row.created_at.isoformat(), "expires_at": row.expires_at.isoformat()}
            for row in sign_ins
        ],
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
                "tags": list(a.tags),
                "created_at": a.created_at.isoformat(),
                "updated_at": a.updated_at.isoformat(),
                "stage_history": [
                    {"from": e.from_stage, "to": e.to_stage, "at": e.at.isoformat()}
                    for e in a.events
                ],
            }
            for a in apps
        ],
        "board_posts": [
            {
                "id": str(p.id),
                "title": p.title,
                "company_name": p.company_name,
                "job_url": p.job_url,
                "location": p.location,
                "remote": p.remote,
                "deadline": _iso(p.deadline),
                "status": p.status,
                "checks": p.checks,
                "created_at": p.created_at.isoformat(),
            }
            for p in posts
        ],
        "checkins": [
            {
                "on_date": c.on_date.isoformat(),
                "ideal_role": c.ideal_role,
                "excited": c.excited,
                "energised": c.energised,
                "drained": c.drained,
                "changed": c.changed,
                "confidence": {
                    "planning": c.confidence_planning,
                    "control": c.confidence_control,
                    "curiosity": c.confidence_curiosity,
                    "action": c.confidence_action,
                },
                "roles_shown": c.roles_shown,
            }
            for c in checkins
        ],
        "entries": [
            {
                "kind": e.kind,
                "text": e.text,
                "happened_on": e.happened_on.isoformat(),
                "application_id": str(e.application_id) if e.application_id else None,
                "done_at": _iso(e.done_at),
            }
            for e in entries
        ],
        "reports": [
            {
                "board_role_id": str(r.board_role_id),
                "reason": r.reason,
                "note": r.note,
                "created_at": r.created_at.isoformat(),
            }
            for r in reports
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
    user_db: UserDb,
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
    if body.remove_posts:
        user_db.execute(delete(BoardRole).where(BoardRole.posted_by == auth.user_id))
        user_db.commit()
    # Foreign keys cascade to applications, stage events, reports, sessions
    # and tokens; board posts left up lose their poster (SET NULL).
    db.execute(delete(User).where(User.id == auth.user_id))
    db.commit()
    log.info("account deleted")
    clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/digest-preview")
def digest_preview(auth: AuthDep, db: SystemDb, user_db: UserDb) -> dict[str, Any]:
    """What tomorrow morning's reminder would list if it ran now."""
    user = db.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    today = today_eat()
    items = upcoming(user_db, auth.user_id, today)
    reasons = []
    if not user.reminder_opt_in:
        reasons.append("Reminders are turned off in Settings.")
    if user.email_verified_at is None:
        reasons.append("Confirm your email address to get reminders.")
    if not items:
        reasons.append("Nothing is due in the next 3 days.")
    return {
        "will_send": not reasons,
        "reasons": reasons,
        "items": [
            {
                "role_title": i.role_title,
                "company_name": i.company_name,
                "stage": i.stage,
                "deadline": i.deadline.isoformat(),
            }
            for i in items
        ],
    }
