"""The shared board: post a role (checked by the rules), browse, save to your
tracker, report. Reads of the board use a session with no identity, so RLS
itself limits them to approved, visible posts."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import (
    Auth,
    AuthDep,
    FetcherDep,
    OptionalUserDb,
    SystemDb,
    UserDb,
    VerifiedDep,
    client_ip,
    enforce,
    get_limiter,
    optional_auth,
)
from app.models import VISIBLE_STATUSES, Application, BoardRole, Report, User
from app.routers.applications import ApplicationDetail, add_application, detail
from app.services.checking import run_checks
from app.services.digest import today_eat
from app.services.ratelimit import Limit
from app.services.verify import Ad, parse_link

router = APIRouter(prefix="/api/board", tags=["board"])

PAGE_SIZE = 50
POSTS_PER_DAY = 5
NEW_ACCOUNT_DAYS = 7
APPROVED_POSTS_TO_SKIP_REVIEW = 2
AD_TEXT_MAX = 10_000
DELETED_HANDLE = "deleted-user"
BOARD_READ_PER_IP = Limit("board-read-ip", 120, 60)
REPORTS_PER_USER = Limit("board-report", 20, 86400)
Reason = Literal["fee", "fake", "expired", "duplicate", "other"]
Viewer = Annotated[Auth | None, Depends(optional_auth)]


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _blank_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else _strip(value)


class BoardPostIn(BaseModel):
    """A role to share. ad_text and agency_name feed the checks; neither is stored."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    job_url: str = Field(min_length=1, max_length=2048)
    location: str | None = Field(default=None, max_length=100)
    remote: bool = False
    deadline: date | None = None
    ad_text: str = Field(default="", max_length=AD_TEXT_MAX)
    agency_name: str | None = Field(default=None, max_length=200)

    _strip_text = field_validator("title", "company_name", "job_url", mode="before")(_strip)
    _optional = field_validator("location", "agency_name", mode="before")(_blank_to_none)

    @field_validator("title", "company_name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("Can't be blank.")
        return v

    @field_validator("job_url")
    @classmethod
    def _link(cls, v: str) -> str:
        if parse_link(v) is None:
            raise ValueError("Add the link to the job ad, starting with https://")
        return v.split("#", 1)[0]

    @field_validator("deadline")
    @classmethod
    def _future(cls, v: date | None) -> date | None:
        if v is not None and not today_eat() <= v <= today_eat() + timedelta(days=365):
            raise ValueError("Pick a deadline from today to a year ahead.")
        return v


class CheckOut(BaseModel):
    id: str
    label: str
    result: str
    detail: str


class BoardRoleOut(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str
    job_url: str
    location: str | None
    remote: bool
    deadline: date | None
    status: str
    checks: list[CheckOut]
    posted_by: str
    created_at: datetime
    checked_at: datetime
    mine: bool
    # Only ever true on your own posts: waiting for a moderator.
    pending_review: bool


class BoardPage(BaseModel):
    items: list[BoardRoleOut]
    total: int
    next_offset: int | None


class PostResult(BaseModel):
    role: BoardRoleOut
    message: str
    lookups_paused: bool


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    note: str | None = Field(default=None, max_length=300)

    _note = field_validator("note", mode="before")(_blank_to_none)


def role_out(role: BoardRole, handle: str | None, viewer: uuid.UUID | None) -> BoardRoleOut:
    mine = viewer is not None and role.posted_by == viewer
    return BoardRoleOut(
        id=role.id,
        title=role.title,
        company_name=role.company_name,
        job_url=role.job_url,
        location=role.location,
        remote=role.remote,
        deadline=role.deadline,
        status=role.status,
        checks=[CheckOut.model_validate(c) for c in role.checks],
        posted_by=handle or DELETED_HANDLE,
        created_at=role.created_at,
        checked_at=role.checked_at,
        mine=mine,
        pending_review=mine and role.approved_at is None and role.status in VISIBLE_STATUSES,
    )


def _with_handles(query: Select[Any]) -> Select[Any]:
    return query.outerjoin(User, User.id == BoardRole.posted_by).add_columns(User.handle)


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("")
def list_board(
    request: Request,
    db: SystemDb,
    viewer: Viewer,
    remote: bool | None = None,
    location: Annotated[str | None, Query(max_length=100)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    due_within_days: Annotated[int | None, Query(ge=0, le=365)] = None,
    verified_only: bool = False,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=PAGE_SIZE)] = PAGE_SIZE,
) -> BoardPage:
    """Public: no sign-in. The session has no identity, so RLS shows only
    approved, visible posts whatever the filters say."""
    enforce(request, BOARD_READ_PER_IP, client_ip(request))
    today = today_eat()
    query: Select[Any] = select(BoardRole).where(
        BoardRole.approved_at.is_not(None),
        BoardRole.status.in_(("verified",) if verified_only else VISIBLE_STATUSES),
        or_(BoardRole.deadline.is_(None), BoardRole.deadline >= today),
    )
    if remote is not None:
        query = query.where(BoardRole.remote.is_(remote))
    if location and location.strip():
        query = query.where(BoardRole.location.ilike(_like(location.strip()), escape="\\"))
    if q and q.strip():
        term = _like(q.strip())
        query = query.where(
            or_(
                BoardRole.title.ilike(term, escape="\\"),
                BoardRole.company_name.ilike(term, escape="\\"),
            )
        )
    if due_within_days is not None:
        query = query.where(BoardRole.deadline <= today + timedelta(days=due_within_days))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        _with_handles(query)
        .order_by(BoardRole.created_at.desc(), BoardRole.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [role_out(r, h, viewer.user_id if viewer else None) for r, h in rows]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return BoardPage(items=items, total=total, next_offset=next_offset)


@router.get("/mine")
def my_posts(
    auth: AuthDep,
    db: UserDb,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> BoardPage:
    query: Select[Any] = select(BoardRole).where(BoardRole.posted_by == auth.user_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        _with_handles(query)
        .order_by(BoardRole.created_at.desc(), BoardRole.id)
        .offset(offset)
        .limit(PAGE_SIZE)
    ).all()
    items = [role_out(r, h, auth.user_id) for r, h in rows]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return BoardPage(items=items, total=total, next_offset=next_offset)


def _visible_or_own(db: Session, role_id: uuid.UUID) -> tuple[BoardRole, str | None]:
    """RLS decides: public posts, plus your own (and everything, for admins)."""
    row = db.execute(_with_handles(select(BoardRole).where(BoardRole.id == role_id))).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That role isn't on the board.")
    return row[0], row[1]


@router.get("/{role_id}")
def get_role(
    role_id: uuid.UUID, request: Request, db: OptionalUserDb, viewer: Viewer
) -> BoardRoleOut:
    enforce(request, BOARD_READ_PER_IP, client_ip(request))
    role, handle = _visible_or_own(db, role_id)
    return role_out(role, handle, viewer.user_id if viewer else None)


@router.post("", status_code=status.HTTP_201_CREATED)
def post_role(
    body: BoardPostIn,
    request: Request,
    auth: VerifiedDep,
    db: UserDb,
    system_db: SystemDb,
    fetcher: FetcherDep,
) -> PostResult:
    now = datetime.now(UTC)
    recent = db.scalar(
        select(func.count())
        .select_from(BoardRole)
        .where(BoardRole.posted_by == auth.user_id, BoardRole.created_at > now - timedelta(days=1))
    )
    if (recent or 0) >= POSTS_PER_DAY:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You can share up to {POSTS_PER_DAY} roles a day. Thank you for sharing!",
        )
    _refuse_duplicate(db, body.job_url)

    ad = Ad(body.job_url, body.ad_text, body.company_name, body.agency_name)
    run = run_checks(db, fetcher, get_limiter(request), f"user:{auth.user_id}", ad, today_eat())
    signed_up = system_db.scalar(select(User.created_at).where(User.id == auth.user_id))
    system_db.rollback()
    approved_before = db.scalar(
        select(func.count())
        .select_from(BoardRole)
        .where(BoardRole.posted_by == auth.user_id, BoardRole.approved_at.is_not(None))
    )
    needs_review = (
        signed_up is None
        or signed_up > now - timedelta(days=NEW_ACCOUNT_DAYS)
        or (approved_before or 0) < APPROVED_POSTS_TO_SKIP_REVIEW
    )
    link = parse_link(body.job_url)
    if link is None:  # the model already refused these; kept for the type checker
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Check the link.")
    role = BoardRole(
        posted_by=auth.user_id,
        title=body.title,
        company_name=body.company_name,
        job_url=body.job_url,
        company_domain=link.domain,
        location=body.location,
        remote=body.remote,
        deadline=body.deadline,
        status=run.verdict,
        checks=[c.as_dict() for c in run.checks],
        approved_at=None if needs_review or run.verdict == "flagged" else now,
        checked_at=now,
    )
    db.add(role)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _already_posted() from None
    db.refresh(role)

    if run.verdict == "flagged":
        message = (
            "Not posted: the checks flagged this ad as a likely scam. "
            "See why below. Please don't pay anything to apply."
        )
    elif needs_review:
        message = "Thank you! A moderator will look at it before it appears on the board."
    else:
        message = "Thank you! It's on the board now."
    users_handle = system_db.scalar(select(User.handle).where(User.id == auth.user_id))
    system_db.rollback()
    return PostResult(
        role=role_out(role, users_handle, auth.user_id),
        message=message,
        lookups_paused=run.lookups_paused,
    )


def _already_posted() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail="That link is already on the board.")


def _refuse_duplicate(db: Session, job_url: str) -> None:
    # RLS may hide someone else's pending copy; the unique index catches that one.
    existing = db.scalar(
        select(BoardRole.id).where(BoardRole.job_url == job_url, BoardRole.archived_at.is_(None))
    )
    if existing is not None:
        raise _already_posted()


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(role_id: uuid.UUID, auth: AuthDep, db: UserDb) -> Response:
    deleted = db.execute(
        delete(BoardRole)
        .where(BoardRole.id == role_id, BoardRole.posted_by == auth.user_id)
        .returning(BoardRole.id)
    ).one_or_none()
    if deleted is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That isn't one of your posts.")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{role_id}/save")
def save_to_tracker(
    role_id: uuid.UUID, response: Response, auth: AuthDep, db: UserDb
) -> ApplicationDetail:
    """Add a board role to your tracker; saving it again returns the same application."""
    role, _ = _visible_or_own(db, role_id)
    existing = db.scalar(
        select(Application.id).where(
            Application.user_id == auth.user_id, Application.board_role_id == role.id
        )
    )
    if existing is not None:
        return detail(db, auth.user_id, existing)
    app = add_application(
        db,
        auth.user_id,
        {
            "role_title": role.title,
            "company_name": role.company_name,
            "job_url": role.job_url,
            "deadline": role.deadline,
            "board_role_id": role.id,
        },
        source="board",
    )
    db.commit()
    response.status_code = status.HTTP_201_CREATED
    return detail(db, auth.user_id, app.id)


@router.post("/{role_id}/report", status_code=status.HTTP_201_CREATED)
def report_role(
    role_id: uuid.UUID, body: ReportIn, request: Request, auth: VerifiedDep, db: UserDb
) -> dict[str, str]:
    enforce(request, REPORTS_PER_USER, str(auth.user_id))
    role, _ = _visible_or_own(db, role_id)
    if role.posted_by == auth.user_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="You can't report your own post. You can delete it instead.",
        )
    db.add(Report(board_role_id=role.id, reported_by=auth.user_id, **body.model_dump()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="You've already reported this role. Thank you."
        ) from None
    return {
        "detail": "Thank you. Three reports take a role off the board until a moderator checks it."
    }
