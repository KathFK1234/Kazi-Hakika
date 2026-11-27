"""Moderation for admins: the review queue, reports, hide/restore and the NEA list.

Every endpoint needs an admin (ADMIN_EMAILS, confirmed email) and runs in a
session bound to that admin, so the board policies check kh_is_admin() too.
Non-admins get 404, as if the page didn't exist.
"""

import csv
import io
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.deps import AdminDep, UserDb
from app.models import VISIBLE_STATUSES, BoardRole, NeaAgency, Report, User
from app.routers.board import BoardRoleOut, role_out
from app.services.verify import name_key, verdict

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])

QUEUE_LIMIT = 100
NEA_MAX_ROWS = 5000
NEA_CHUNK_MAX = 60_000  # characters per upload; the page splits bigger files


class ReportOut(BaseModel):
    reason: str
    note: str | None
    created_at: datetime


class AdminRoleOut(BoardRoleOut):
    report_count: int
    reports: list[ReportOut]
    approved: bool


class Queue(BaseModel):
    pending: list[AdminRoleOut]
    hidden: list[AdminRoleOut]
    flagged: list[AdminRoleOut]


class NeaUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv: str = Field(min_length=1, max_length=NEA_CHUNK_MAX)
    # The first chunk replaces the list; later chunks of the same file add to it.
    replace: bool = True


class NeaStatus(BaseModel):
    total: int
    synced_at: datetime | None


def _admin_out(db: Session, role: BoardRole, handle: str | None, admin: uuid.UUID) -> AdminRoleOut:
    reports = db.execute(
        select(Report.reason, Report.note, Report.created_at)
        .where(Report.board_role_id == role.id)
        .order_by(Report.created_at)
    ).all()
    base = role_out(role, handle, admin).model_dump()
    return AdminRoleOut(
        **base,
        report_count=role.report_count,
        reports=[ReportOut(reason=r.reason, note=r.note, created_at=r.created_at) for r in reports],
        approved=role.approved_at is not None,
    )


def _roles(db: Session, admin: uuid.UUID, *where: object) -> list[AdminRoleOut]:
    rows = db.execute(
        select(BoardRole, User.handle)
        .outerjoin(User, User.id == BoardRole.posted_by)
        .where(*where)  # type: ignore[arg-type]
        .order_by(BoardRole.created_at)
        .limit(QUEUE_LIMIT)
    ).all()
    return [_admin_out(db, role, handle, admin) for role, handle in rows]


@router.get("/queue")
def queue(auth: AdminDep, db: UserDb) -> Queue:
    return Queue(
        pending=_roles(
            db,
            auth.user_id,
            BoardRole.approved_at.is_(None),
            BoardRole.status.in_(VISIBLE_STATUSES),
        ),
        hidden=_roles(db, auth.user_id, BoardRole.status == "hidden"),
        flagged=_roles(db, auth.user_id, BoardRole.status == "flagged"),
    )


def _role(db: Session, role_id: uuid.UUID) -> BoardRole:
    role = db.get(BoardRole, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Role not found.")
    return role


def _done(db: Session, role: BoardRole, admin: uuid.UUID) -> AdminRoleOut:
    db.commit()
    db.refresh(role)
    handle = db.scalar(select(User.handle).where(User.id == role.posted_by))
    return _admin_out(db, role, handle, admin)


@router.post("/board/{role_id}/approve")
def approve(role_id: uuid.UUID, auth: AdminDep, db: UserDb) -> AdminRoleOut:
    role = _role(db, role_id)
    if role.status not in VISIBLE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Only verified or unverified roles can be approved."
        )
    role.approved_at = role.approved_at or datetime.now(UTC)
    return _done(db, role, auth.user_id)


@router.post("/board/{role_id}/hide")
def hide(role_id: uuid.UUID, auth: AdminDep, db: UserDb) -> AdminRoleOut:
    role = _role(db, role_id)
    if role.status == "archived":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That role is already archived.")
    role.status = "hidden"
    return _done(db, role, auth.user_id)


@router.post("/board/{role_id}/restore")
def restore(role_id: uuid.UUID, auth: AdminDep, db: UserDb) -> AdminRoleOut:
    """Back on the board with the label its checks earned. Its reports are
    cleared (they've been reviewed). A flagged role stays flagged: the rules,
    not a moderator, decide that label."""
    role = _role(db, role_id)
    if role.status != "hidden":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Only hidden roles can be restored.")
    db.execute(delete(Report).where(Report.board_role_id == role.id))
    role.status = verdict(c.get("result", "") for c in role.checks)
    if role.status != "flagged":
        role.approved_at = role.approved_at or datetime.now(UTC)
    return _done(db, role, auth.user_id)


def parse_nea_csv(text: str) -> list[tuple[str, str]]:
    """(name, licence status) rows. Needs a header with a name column
    ("name", "agency" or "agency name"); a status column is optional."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return []
    name_col = next(
        (i for i, h in enumerate(header) if h in ("name", "agency", "agency name")), None
    )
    if name_col is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The first row must name the columns, with one called Name or Agency.",
        )
    status_col = next((i for i, h in enumerate(header) if "status" in h), None)
    rows = []
    for row in reader:
        if len(row) <= name_col or not row[name_col].strip():
            continue
        status_value = (
            row[status_col].strip() if status_col is not None and len(row) > status_col else ""
        )
        rows.append((row[name_col].strip()[:200], (status_value or "licensed")[:40]))
    return rows


@router.post("/nea")
def upload_nea(body: NeaUpload, auth: AdminDep, db: UserDb) -> NeaStatus:
    rows = parse_nea_csv(body.csv)
    now = datetime.now(UTC)
    if body.replace:
        db.execute(delete(NeaAgency))
    existing = db.scalar(select(func.count()).select_from(NeaAgency)) or 0
    if existing + len(rows) > NEA_MAX_ROWS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The list can hold up to {NEA_MAX_ROWS} agencies.",
        )
    seen: set[str] = set()
    for name, licence in rows:
        key = name_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        values = {"name": name, "licence_status": licence, "synced_at": now}
        db.execute(
            insert(NeaAgency)
            .values(name_key=key, **values)
            .on_conflict_do_update(index_elements=["name_key"], set_={**values, "updated_at": now})
        )
    db.commit()
    log.info("NEA list upload: %d rows", len(seen))
    return nea_status(auth, db)


@router.get("/nea")
def nea_status(auth: AdminDep, db: UserDb) -> NeaStatus:
    total, synced_at = db.execute(
        select(func.count(), func.max(NeaAgency.synced_at)).select_from(NeaAgency)
    ).one()
    return NeaStatus(total=total, synced_at=synced_at)
