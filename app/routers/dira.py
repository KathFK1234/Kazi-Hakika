"""Dira: opt-in career check-ins, entries and patterns (Phase 3b).

The most private data in the app: every query runs RLS-bound to the user
(forced RLS on checkins and entries) and filters by them too; nothing here
logs reflection text. Off unless DIRA_ENABLED is set (404 otherwise).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.deps import AuthDep, SystemDb, UserDb
from app.models import Application, Checkin, Entry, StageEvent, User
from app.services import patterns
from app.services.digest import today_eat


def require_dira(request: Request) -> None:
    if not request.app.state.settings.dira_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found.")


router = APIRouter(prefix="/api/dira", tags=["dira"], dependencies=[Depends(require_dira)])

MAX_CHECKINS = 60
MAX_ENTRIES = 2000
ROLES_SHOWN_MAX = 20
ENTRY_PAGE = 100
Interval = Literal[4, 6, 8]
Kind = Literal["win", "learning", "goal"]
Rating = Annotated[int, Field(ge=1, le=5)]


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# --- settings ------------------------------------------------------------


class DiraSettings(BaseModel):
    checkin_interval_weeks: Interval | None
    next_checkin_on: date | None
    weekly_target: int | None


class DiraSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkin_interval_weeks: Interval | None
    weekly_target: Annotated[int, Field(ge=1, le=20)] | None = None


def _settings(user: User) -> DiraSettings:
    return DiraSettings(
        checkin_interval_weeks=user.checkin_interval_weeks,
        next_checkin_on=user.next_checkin_on,
        weekly_target=user.weekly_target,
    )


def _user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    return user


@router.patch("/settings")
def update_settings(body: DiraSettingsIn, auth: AuthDep, db: SystemDb) -> DiraSettings:
    user = _user(db, auth.user_id)
    if body.checkin_interval_weeks is None:
        user.checkin_interval_weeks = None
        user.next_checkin_on = None
    else:
        if user.checkin_interval_weeks is None:
            # Turning check-ins on: the first one is due straight away.
            user.next_checkin_on = today_eat()
        user.checkin_interval_weeks = body.checkin_interval_weeks
    user.weekly_target = body.weekly_target
    db.commit()
    return _settings(user)


# --- check-ins -----------------------------------------------------------


class CheckinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ideal_role: str = Field(min_length=1, max_length=300)
    excited: str | None = Field(default=None, max_length=2000)
    energised: str | None = Field(default=None, max_length=1000)
    drained: str | None = Field(default=None, max_length=1000)
    changed: str | None = Field(default=None, max_length=2000)
    confidence_planning: Rating | None = None
    confidence_control: Rating | None = None
    confidence_curiosity: Rating | None = None
    confidence_action: Rating | None = None

    _texts = field_validator("excited", "energised", "drained", "changed", mode="before")(
        _blank_to_none
    )

    @field_validator("ideal_role", mode="before")
    @classmethod
    def _ideal(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("Write a sentence about the role you're aiming for.")
        return v.strip() if isinstance(v, str) else v


class CheckinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    on_date: date
    ideal_role: str
    excited: str | None
    energised: str | None
    drained: str | None
    changed: str | None
    confidence_planning: int | None
    confidence_control: int | None
    confidence_curiosity: int | None
    confidence_action: int | None


class RoleReminder(BaseModel):
    id: uuid.UUID
    role_title: str


class CheckinPrompt(BaseModel):
    last_checkin_on: date | None
    checked_in_today: bool
    roles_since: list[RoleReminder]


class WeekProgress(BaseModel):
    target: int | None
    applied_this_week: int


class Overview(BaseModel):
    settings: DiraSettings
    due: bool
    week: WeekProgress
    checkins: list[CheckinOut]


def _checkins(db: Session, user_id: uuid.UUID) -> list[Checkin]:
    return list(
        db.scalars(
            select(Checkin)
            .where(Checkin.user_id == user_id)
            .order_by(Checkin.on_date.desc())
            .limit(MAX_CHECKINS)
        )
    )


def _roles_since(db: Session, user_id: uuid.UUID, since: date | None) -> list[Application]:
    """Roles added or moved since the last check-in (all of them, the first time)."""
    query = select(Application).where(Application.user_id == user_id)
    if since is not None:
        start = datetime.combine(since, datetime.min.time(), UTC) - timedelta(hours=3)
        moved = select(StageEvent.application_id).where(
            StageEvent.user_id == user_id, StageEvent.at >= start
        )
        query = query.where(or_(Application.created_at >= start, Application.id.in_(moved)))
    return list(db.scalars(query.order_by(Application.updated_at.desc()).limit(ROLES_SHOWN_MAX)))


def _week_start(today: date) -> datetime:
    monday = today - timedelta(days=today.weekday())
    # Weeks run Monday to Sunday in Kenya (UTC+3).
    return datetime.combine(monday, datetime.min.time(), UTC) - timedelta(hours=3)


@router.get("")
def overview(auth: AuthDep, db: UserDb, system_db: SystemDb) -> Overview:
    user = _user(system_db, auth.user_id)
    system_db.rollback()
    today = today_eat()
    applied = db.scalar(
        select(func.count(func.distinct(StageEvent.application_id))).where(
            StageEvent.user_id == auth.user_id,
            StageEvent.to_stage == "applied",
            StageEvent.at >= _week_start(today),
        )
    )
    return Overview(
        settings=_settings(user),
        due=user.next_checkin_on is not None and user.next_checkin_on <= today,
        week=WeekProgress(target=user.weekly_target, applied_this_week=applied or 0),
        checkins=[CheckinOut.model_validate(c) for c in _checkins(db, auth.user_id)],
    )


@router.get("/checkin")
def checkin_prompt(auth: AuthDep, db: UserDb) -> CheckinPrompt:
    last = db.scalar(select(func.max(Checkin.on_date)).where(Checkin.user_id == auth.user_id))
    roles = _roles_since(db, auth.user_id, last)
    return CheckinPrompt(
        last_checkin_on=last,
        checked_in_today=last == today_eat(),
        roles_since=[RoleReminder(id=a.id, role_title=a.role_title) for a in roles],
    )


@router.post("/checkins", status_code=status.HTTP_201_CREATED)
def save_checkin(body: CheckinIn, auth: AuthDep, db: UserDb, system_db: SystemDb) -> CheckinOut:
    count = db.scalar(select(func.count()).where(Checkin.user_id == auth.user_id)) or 0
    if count >= MAX_CHECKINS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"You have {MAX_CHECKINS} check-ins, the most we keep. "
            "Delete an old one to add a new one.",
        )
    today = today_eat()
    last = db.scalar(select(func.max(Checkin.on_date)).where(Checkin.user_id == auth.user_id))
    shown = [str(a.id) for a in _roles_since(db, auth.user_id, last)]
    checkin = Checkin(user_id=auth.user_id, on_date=today, roles_shown=shown, **body.model_dump())
    db.add(checkin)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="You've already checked in today. You can delete it and start again.",
        ) from None

    user = _user(system_db, auth.user_id)
    if user.checkin_interval_weeks is not None:
        user.next_checkin_on = today + timedelta(weeks=user.checkin_interval_weeks)
        system_db.commit()
    return CheckinOut.model_validate(checkin)


@router.delete("/checkins/{checkin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_checkin(checkin_id: uuid.UUID, auth: AuthDep, db: UserDb) -> Response:
    gone = db.execute(
        delete(Checkin)
        .where(Checkin.id == checkin_id, Checkin.user_id == auth.user_id)
        .returning(Checkin.id)
    ).one_or_none()
    if gone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Check-in not found.")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- patterns ------------------------------------------------------------


class GroupOut(BaseModel):
    name: str
    total: int
    reached_screening: int


class StopOut(BaseModel):
    stage: str
    count: int
    ended: int


class FitOut(BaseModel):
    recent: int
    matching: int
    tags: list[str]


class PatternsOut(BaseModel):
    min_group: int
    applications: int
    by_tag: list[GroupOut]
    by_source: list[GroupOut]
    stops: StopOut | None
    direction: FitOut | None
    ideal_role: str | None


def _facts(app: Application) -> patterns.AppFacts:
    stages = {e.to_stage for e in app.events} | {app.stage}
    ended_from = None
    for event in app.events:
        if event.to_stage in patterns.ENDED and event.from_stage is not None:
            ended_from = event.from_stage
    if app.stage in patterns.ENDED and ended_from is None:
        ended_from = "saved"  # added straight as rejected/withdrawn
    return patterns.AppFacts(
        tags=tuple(app.tags),
        source=app.source,
        created_on=(app.created_at + timedelta(hours=3)).date(),
        stages=frozenset(stages),
        ended_from=ended_from if app.stage in patterns.ENDED else None,
    )


@router.get("/patterns")
def get_patterns(auth: AuthDep, db: UserDb) -> PatternsOut:
    apps = db.scalars(
        select(Application)
        .where(Application.user_id == auth.user_id)
        .options(selectinload(Application.events))
    ).all()
    facts = [_facts(a) for a in apps]
    latest = db.scalar(
        select(Checkin.ideal_role)
        .where(Checkin.user_id == auth.user_id)
        .order_by(Checkin.on_date.desc())
        .limit(1)
    )
    stop = patterns.where_they_stop(facts)
    fit = patterns.direction_fit(facts, latest, today_eat())
    return PatternsOut(
        min_group=patterns.MIN_GROUP,
        applications=len(facts),
        by_tag=[GroupOut(**g.__dict__) for g in patterns.by_tag(facts)],
        by_source=[GroupOut(**g.__dict__) for g in patterns.by_source(facts)],
        stops=StopOut(**stop.__dict__) if stop else None,
        direction=FitOut(**fit.__dict__) if fit else None,
        ideal_role=latest,
    )


# --- entries -------------------------------------------------------------


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    text: str = Field(min_length=1, max_length=1000)
    happened_on: date | None = None
    application_id: uuid.UUID | None = None

    @field_validator("text", mode="before")
    @classmethod
    def _text(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("Write a few words.")
        return v.strip() if isinstance(v, str) else v


class EntryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1, max_length=1000)
    happened_on: date | None = None
    done: bool | None = None


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    text: str
    happened_on: date
    application_id: uuid.UUID | None
    done_at: datetime | None


def _check_day(day: date) -> date:
    today = today_eat()
    if not today - timedelta(days=3650) <= day <= today + timedelta(days=3650):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Pick a sensible date.")
    return day


@router.get("/entries")
def list_entries(
    auth: AuthDep,
    db: UserDb,
    kind: Kind | None = None,
    application_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0, le=MAX_ENTRIES)] = 0,
) -> list[EntryOut]:
    query = select(Entry).where(Entry.user_id == auth.user_id)
    if kind:
        query = query.where(Entry.kind == kind)
    if application_id:
        query = query.where(Entry.application_id == application_id)
    rows = db.scalars(
        query.order_by(Entry.happened_on.desc(), Entry.created_at.desc())
        .offset(offset)
        .limit(ENTRY_PAGE)
    )
    return [EntryOut.model_validate(e) for e in rows]


@router.post("/entries", status_code=status.HTTP_201_CREATED)
def add_entry(body: EntryIn, auth: AuthDep, db: UserDb) -> EntryOut:
    count = db.scalar(select(func.count()).where(Entry.user_id == auth.user_id)) or 0
    if count >= MAX_ENTRIES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"You have {MAX_ENTRIES} entries, the most we keep. Delete some to add more.",
        )
    if body.application_id is not None:
        owned = db.scalar(
            select(Application.id).where(
                Application.id == body.application_id, Application.user_id == auth.user_id
            )
        )
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Application not found.")
    entry = Entry(
        user_id=auth.user_id,
        kind=body.kind,
        text=body.text,
        happened_on=_check_day(body.happened_on or today_eat()),
        application_id=body.application_id,
    )
    db.add(entry)
    db.commit()
    return EntryOut.model_validate(entry)


def _entry(db: Session, user_id: uuid.UUID, entry_id: uuid.UUID) -> Entry:
    entry = db.scalar(select(Entry).where(Entry.id == entry_id, Entry.user_id == user_id))
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Entry not found.")
    return entry


@router.patch("/entries/{entry_id}")
def update_entry(entry_id: uuid.UUID, body: EntryPatch, auth: AuthDep, db: UserDb) -> EntryOut:
    entry = _entry(db, auth.user_id, entry_id)
    if body.text is not None:
        if not body.text.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Write a few words.")
        entry.text = body.text.strip()
    if body.happened_on is not None:
        entry.happened_on = _check_day(body.happened_on)
    if body.done is not None:
        if entry.kind != "goal":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Only goals can be marked done."
            )
        entry.done_at = datetime.now(UTC) if body.done else None
    db.commit()
    return EntryOut.model_validate(entry)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: uuid.UUID, auth: AuthDep, db: UserDb) -> Response:
    db.delete(_entry(db, auth.user_id, entry_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
