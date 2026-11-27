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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk

STAGES = ("saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn")
SOURCES = ("own", "board")
NOTES_MAX = 5000


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("handle ~ '^[a-z0-9_-]{3,30}$'", name="handle_format"),
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


class Application(UUIDPk, Timestamps, Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(_in("stage", STAGES), name="stage_valid"),
        CheckConstraint(_in("source", SOURCES), name="source_valid"),
        CheckConstraint(f"char_length(notes) <= {NOTES_MAX}", name="notes_length"),
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
