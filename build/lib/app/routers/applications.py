"""The private tracker. Every query filters by the signed-in user, and the
session is RLS-bound to that user as well, so a missed filter still leaks nothing."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.deps import AuthDep, UserDb
from app.models import NOTES_MAX, Application, StageEvent
from app.services.digest import today_eat

router = APIRouter(prefix="/api/applications", tags=["applications"])

PAGE_SIZE = 50
MAX_APPLICATIONS_PER_USER = 2000
Stage = Literal["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"]

MIN_DATE, MAX_DATE = date(2000, 1, 1), date(2100, 12, 31)


def _clean_url(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("Use a full link starting with https://")
    return value


def _check_date(value: date | None) -> date | None:
    if value is not None and not MIN_DATE <= value <= MAX_DATE:
        raise ValueError("Date is out of range.")
    return value


def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_title: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    job_url: str | None = Field(default=None, max_length=2048)
    stage: Stage = "saved"
    deadline: date | None = None
    applied_on: date | None = None
    salary_note: str | None = Field(default=None, max_length=200)
    notes: str = Field(default="", max_length=NOTES_MAX)

    _strip_text = field_validator("role_title", "company_name", "salary_note", mode="before")(
        _strip
    )
    _url = field_validator("job_url")(_clean_url)
    _dates = field_validator("deadline", "applied_on")(_check_date)

    @field_validator("role_title", "company_name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("Can't be blank.")
        return v


class ApplicationPatch(BaseModel):
    """Only the fields sent are changed; send null to clear an optional field."""

    model_config = ConfigDict(extra="forbid")

    role_title: str | None = Field(default=None, min_length=1, max_length=200)
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    job_url: str | None = Field(default=None, max_length=2048)
    stage: Stage | None = None
    deadline: date | None = None
    applied_on: date | None = None
    salary_note: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)

    _strip_text = field_validator("role_title", "company_name", "salary_note", mode="before")(
        _strip
    )
    _url = field_validator("job_url")(_clean_url)
    _dates = field_validator("deadline", "applied_on")(_check_date)


class StageEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_stage: str | None
    to_stage: str
    at: datetime


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role_title: str
    company_name: str
    job_url: str | None
    source: str
    stage: str
    deadline: date | None
    applied_on: date | None
    salary_note: str | None
    notes: str
    created_at: datetime
    updated_at: datetime


class ApplicationDetail(ApplicationOut):
    events: list[StageEventOut]


class ApplicationPage(BaseModel):
    items: list[ApplicationOut]
    total: int
    next_offset: int | None


def _today() -> date:
    return today_eat()


def _record_stage(db: UserDb, app: Application, user_id: uuid.UUID, from_stage: str | None) -> None:
    db.add(
        StageEvent(
            application_id=app.id,
            user_id=user_id,
            from_stage=from_stage,
            to_stage=app.stage,
            at=datetime.now(UTC),
        )
    )
    if app.stage == "applied" and app.applied_on is None:
        app.applied_on = _today()


def _owned(db: UserDb, user_id: uuid.UUID, app_id: uuid.UUID) -> Application:
    app = db.scalar(
        select(Application).where(Application.id == app_id, Application.user_id == user_id)
    )
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return app


@router.get("")
def list_applications(
    auth: AuthDep,
    db: UserDb,
    stage: Annotated[list[Stage] | None, Query()] = None,
    due_within_days: Annotated[int | None, Query(ge=0, le=365)] = None,
    include_overdue: bool = False,
    sort: Literal["deadline", "updated"] = "deadline",
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=PAGE_SIZE)] = PAGE_SIZE,
) -> ApplicationPage:
    query: Select[Application] = select(Application).where(Application.user_id == auth.user_id)
    if stage:
        query = query.where(Application.stage.in_(stage))
    if due_within_days is not None:
        today = _today()
        query = query.where(Application.deadline <= today + timedelta(days=due_within_days))
        if not include_overdue:
            query = query.where(Application.deadline >= today)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if sort == "deadline":
        query = query.order_by(
            Application.deadline.asc().nulls_last(), Application.created_at.desc()
        )
    else:
        query = query.order_by(Application.updated_at.desc())
    items = db.scalars(query.order_by(Application.id).offset(offset).limit(limit)).all()
    next_offset = offset + len(items) if offset + len(items) < total else None
    return ApplicationPage(
        items=[ApplicationOut.model_validate(a) for a in items],
        total=total,
        next_offset=next_offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_application(body: ApplicationIn, auth: AuthDep, db: UserDb) -> ApplicationDetail:
    count = db.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == auth.user_id)
    )
    if (count or 0) >= MAX_APPLICATIONS_PER_USER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"You can track up to {MAX_APPLICATIONS_PER_USER} applications. "
            "Delete some old ones to add more.",
        )
    app = Application(user_id=auth.user_id, source="own", **body.model_dump())
    db.add(app)
    db.flush()
    _record_stage(db, app, auth.user_id, None)
    db.commit()
    return _detail(db, auth.user_id, app.id)


@router.get("/{app_id}")
def get_application(app_id: uuid.UUID, auth: AuthDep, db: UserDb) -> ApplicationDetail:
    return _detail(db, auth.user_id, app_id)


@router.patch("/{app_id}")
def update_application(
    app_id: uuid.UUID, body: ApplicationPatch, auth: AuthDep, db: UserDb
) -> ApplicationDetail:
    app = _owned(db, auth.user_id, app_id)
    changes = body.model_dump(exclude_unset=True)
    for required in ("role_title", "company_name", "stage", "notes"):
        if required in changes and changes[required] is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{required} can't be empty."
            )
    old_stage = app.stage
    for field, value in changes.items():
        setattr(app, field, value)
    if app.stage != old_stage:
        _record_stage(db, app, auth.user_id, old_stage)
    db.commit()
    return _detail(db, auth.user_id, app_id)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(app_id: uuid.UUID, auth: AuthDep, db: UserDb) -> Response:
    db.delete(_owned(db, auth.user_id, app_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _detail(db: UserDb, user_id: uuid.UUID, app_id: uuid.UUID) -> ApplicationDetail:
    app = db.scalar(
        select(Application)
        .where(Application.id == app_id, Application.user_id == user_id)
        .options(selectinload(Application.events))
        .execution_options(populate_existing=True)
    )
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return ApplicationDetail.model_validate(app)
