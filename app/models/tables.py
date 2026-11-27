import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk

STAGES = ("saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn")
SOURCES = ("own", "board")
NOTES_MAX = 5000
TAGS_MAX = 5
TAG_PATTERN = "[a-z0-9][a-z0-9-]{0,29}"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("handle ~ '^[a-z0-9_-]{3,30}$'", name="handle_format"),
        CheckConstraint(
            "checkin_interval_weeks IS NULL OR checkin_interval_weeks IN (4, 6, 8)",
            name="checkin_interval_valid",
        ),
        CheckConstraint(
            "weekly_target IS NULL OR weekly_target BETWEEN 1 AND 20", name="weekly_target_range"
        ),
    )

    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    handle: Mapped[str] = mapped_column(String(30), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_opt_in: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # The daily job sends at most one digest per user per day.
    last_digest_on: Mapped[date | None] = mapped_column(Date)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set only by the owner from ADMIN_EMAILS (app.admins); the app role has no
    # INSERT/UPDATE privilege on this column, so no Python default is sent.
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Dira check-ins: all off (NULL) by default.
    checkin_interval_weeks: Mapped[int | None] = mapped_column(SmallInteger)
    next_checkin_on: Mapped[date | None] = mapped_column(Date)
    last_checkin_email_on: Mapped[date | None] = mapped_column(Date)
    weekly_target: Mapped[int | None] = mapped_column(SmallInteger)


class Application(UUIDPk, Timestamps, Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(_in("stage", STAGES), name="stage_valid"),
        CheckConstraint(_in("source", SOURCES), name="source_valid"),
        CheckConstraint(f"char_length(notes) <= {NOTES_MAX}", name="notes_length"),
        CheckConstraint(
            f"cardinality(tags) <= {TAGS_MAX} AND array_to_string(tags, ',') ~ "
            f"'^({TAG_PATTERN}(,{TAG_PATTERN})*)?$'",
            name="tags_valid",
        ),
        # Lets stage_events prove an event belongs to its application's owner.
        UniqueConstraint("id", "user_id", name="uq_applications_id_user_id"),
        # user_id leads both, so they also serve plain user_id lookups.
        Index("ix_applications_user_id_stage", "user_id", "stage"),
        Index("ix_applications_user_id_deadline", "user_id", "deadline"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role_title: Mapped[str] = mapped_column(String(200))
    company_name: Mapped[str] = mapped_column(String(200))
    job_url: Mapped[str | None] = mapped_column(String(2048))
    source: Mapped[str] = mapped_column(String(10), server_default="own", default="own")
    board_role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("board_roles.id", ondelete="SET NULL"), index=True
    )
    stage: Mapped[str] = mapped_column(String(20), server_default="saved", default="saved")
    deadline: Mapped[date | None] = mapped_column(Date)
    applied_on: Mapped[date | None] = mapped_column(Date)
    salary_note: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, server_default="", default="")
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), server_default=text("'{}'::varchar[]"), default=list
    )

    events: Mapped[list[StageEvent]] = relationship(
        back_populates="application",
        foreign_keys="[StageEvent.application_id, StageEvent.user_id]",
        order_by="StageEvent.at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class StageEvent(UUIDPk, Timestamps, Base):
    __tablename__ = "stage_events"
    __table_args__ = (
        CheckConstraint(
            f"from_stage IS NULL OR {_in('from_stage', STAGES)}", name="from_stage_valid"
        ),
        CheckConstraint(_in("to_stage", STAGES), name="to_stage_valid"),
        ForeignKeyConstraint(
            ["application_id", "user_id"],
            ["applications.id", "applications.user_id"],
            ondelete="CASCADE",
            name="fk_stage_events_application_owner",
        ),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # Copied from the application so the RLS policy needs no join.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    from_stage: Mapped[str | None] = mapped_column(String(20))
    to_stage: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship(
        back_populates="events",
        foreign_keys="[StageEvent.application_id, StageEvent.user_id]",
        overlaps="user",
    )


class EmailBudget(Timestamps, Base):
    __tablename__ = "email_budget"
    __table_args__ = (CheckConstraint("sent_count >= 0", name="sent_count_nonnegative"),)

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    sent_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)


TOKEN_PURPOSES = ("verify_email", "reset_password")


class UserSession(UUIDPk, Timestamps, Base):
    """A signed-in browser. Only a SHA-256 of the cookie value is stored."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthToken(UUIDPk, Timestamps, Base):
    """One-time email verification and password reset tokens (hashed)."""

    __tablename__ = "auth_tokens"
    __table_args__ = (CheckConstraint(_in("purpose", TOKEN_PURPOSES), name="purpose_valid"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


BOARD_STATUSES = ("verified", "unverified", "flagged", "hidden", "archived")
# What the board shows to everyone (once approved).
VISIBLE_STATUSES = ("verified", "unverified")
REPORT_REASONS = ("fee", "fake", "expired", "duplicate", "other")


class BoardRole(UUIDPk, Timestamps, Base):
    """A role someone shared. RLS: public read of approved, visible posts;
    posters see their own; only admins and the daily job change status."""

    __tablename__ = "board_roles"
    __table_args__ = (
        CheckConstraint(_in("status", BOARD_STATUSES), name="status_valid"),
        CheckConstraint("report_count >= 0", name="report_count_nonnegative"),
        CheckConstraint("jsonb_typeof(checks) = 'array'", name="checks_is_array"),
        Index("ix_board_roles_status_deadline", "status", "deadline"),
        Index("ix_board_roles_status_checked_at", "status", "checked_at"),
        Index("ix_board_roles_archived_at", "archived_at"),
        Index(
            "uq_board_roles_live_job_url",
            "job_url",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    # NULL once the poster deletes their account (shown as deleted-user).
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    company_name: Mapped[str] = mapped_column(String(200))
    job_url: Mapped[str] = mapped_column(String(2048))
    company_domain: Mapped[str] = mapped_column(String(253))
    location: Mapped[str | None] = mapped_column(String(100))
    remote: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12))
    checks: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )
    report_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    # NULL while the post waits in the admin review queue.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Report(UUIDPk, Timestamps, Base):
    """One per user per role. A trigger keeps board_roles.report_count in step."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(_in("reason", REPORT_REASONS), name="reason_valid"),
        UniqueConstraint("board_role_id", "reported_by", name="uq_reports_role_reporter"),
    )

    board_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("board_roles.id", ondelete="CASCADE")
    )
    reported_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(300))


class DomainCheck(Timestamps, Base):
    """Cached lookups per registrable domain, kept 7 days."""

    __tablename__ = "domain_checks"

    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    registered_on: Mapped[date | None] = mapped_column(Date)
    resolves: Mapped[bool | None] = mapped_column(Boolean)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class NeaAgency(UUIDPk, Timestamps, Base):
    """Licensed employment agencies (NEAIMS list, uploaded by an admin)."""

    __tablename__ = "nea_agencies"

    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), unique=True)
    licence_status: Mapped[str] = mapped_column(String(40))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


ENTRY_KINDS = ("win", "learning", "goal")


class Checkin(UUIDPk, Timestamps, Base):
    """A Dira check-in: the most private data in the app (forced RLS, never logged)."""

    __tablename__ = "checkins"
    __table_args__ = (
        CheckConstraint("char_length(ideal_role) BETWEEN 1 AND 300", name="ideal_role_length"),
        CheckConstraint(
            "char_length(excited) <= 2000 AND char_length(changed) <= 2000 "
            "AND char_length(energised) <= 1000 AND char_length(drained) <= 1000",
            name="text_lengths",
        ),
        CheckConstraint(
            "coalesce(confidence_planning, 1) BETWEEN 1 AND 5 "
            "AND coalesce(confidence_control, 1) BETWEEN 1 AND 5 "
            "AND coalesce(confidence_curiosity, 1) BETWEEN 1 AND 5 "
            "AND coalesce(confidence_action, 1) BETWEEN 1 AND 5",
            name="confidence_range",
        ),
        CheckConstraint("jsonb_typeof(roles_shown) = 'array'", name="roles_shown_is_array"),
        UniqueConstraint("user_id", "on_date", name="uq_checkins_user_id_on_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    on_date: Mapped[date] = mapped_column(Date)
    ideal_role: Mapped[str] = mapped_column(String(300))
    excited: Mapped[str | None] = mapped_column(Text)
    energised: Mapped[str | None] = mapped_column(Text)
    drained: Mapped[str | None] = mapped_column(Text)
    changed: Mapped[str | None] = mapped_column(Text)
    confidence_planning: Mapped[int | None] = mapped_column(SmallInteger)
    confidence_control: Mapped[int | None] = mapped_column(SmallInteger)
    confidence_curiosity: Mapped[int | None] = mapped_column(SmallInteger)
    confidence_action: Mapped[int | None] = mapped_column(SmallInteger)
    # Application ids listed as reminders on the check-in page.
    roles_shown: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )


class Entry(UUIDPk, Timestamps, Base):
    """A win, learning or goal, optionally about one of the user's applications."""

    __tablename__ = "entries"
    __table_args__ = (
        CheckConstraint(_in("kind", ENTRY_KINDS), name="kind_valid"),
        CheckConstraint("char_length(text) >= 1", name="text_not_empty"),
        CheckConstraint("done_at IS NULL OR kind = 'goal'", name="done_only_for_goals"),
        # Clears only application_id when the application goes (Postgres 15+).
        ForeignKeyConstraint(
            ["application_id", "user_id"],
            ["applications.id", "applications.user_id"],
            ondelete="SET NULL (application_id)",
            name="fk_entries_application_owner",
        ),
        Index("ix_entries_user_id_happened_on", "user_id", "happened_on"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(String(1000))
    happened_on: Mapped[date] = mapped_column(Date)
    application_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
