"""Dira check-in reminders in the daily job (3b.7)."""

import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.jobs.daily import run
from app.services.digest import today_eat
from app.services.email import EmailMessage, EmailSendError, Mailer
from tests.conftest import make_settings
from tests.factories import make_application, make_user

SENTINEL = "zq-reflection-sentinel-9902"


@pytest.fixture
def on(settings: Settings) -> Settings:
    return make_settings(database_url=settings.database_url, dira_enabled=True)


def _due_user(
    owner: Engine, handle: str, *, due_in: int = 0, reminded: str | None = None
) -> uuid.UUID:
    uid = make_user(owner, handle, verified=True)
    with owner.begin() as c:
        c.execute(
            text(
                "UPDATE users SET checkin_interval_weeks = 6, next_checkin_on = current_date + :d, "
                "last_checkin_email_on = CAST(:r AS date) WHERE id = :u"
            ),
            {"d": due_in, "r": reminded, "u": uid},
        )
        c.execute(
            text(
                "INSERT INTO checkins (user_id, on_date, ideal_role, changed) "
                "VALUES (:u, current_date - 42, :role, :changed)"
            ),
            {"u": uid, "role": SENTINEL, "changed": SENTINEL},
        )
    return uid


def _run(sessions: sessionmaker[Session], settings: Settings, sent: list[EmailMessage]) -> object:
    return run(sessions, Mailer(sessions, settings, sent.append), settings)


def test_digest_and_checkin_due_means_exactly_one_email(
    owner_engine: Engine, app_sessions: sessionmaker[Session], on: Settings
) -> None:
    """Acceptance check: a digest and a check-in due the same day: one email."""
    uid = _due_user(owner_engine, "both")
    make_application(owner_engine, uid, "Due soon", today_eat() + timedelta(days=1))
    sent: list[EmailMessage] = []
    counts = _run(app_sessions, on, sent)
    assert [m.kind for m in sent] == ["digest"]
    assert "/dira/checkin" in sent[0].text and "/dira/checkin" in sent[0].html
    assert counts.checkin_in_digest == 1 and counts.checkin_reminders == 0  # type: ignore[attr-defined]
    # A second run the same day sends nothing.
    _run(app_sessions, on, sent)
    assert len(sent) == 1


def test_standalone_reminder_is_a_link_only(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    on: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _due_user(owner_engine, "solo")
    sent: list[EmailMessage] = []
    with caplog.at_level(logging.DEBUG):
        _run(app_sessions, on, sent)
    assert [m.kind for m in sent] == ["checkin_reminder"]
    assert "/dira/checkin" in sent[0].text
    for part in (sent[0].text, sent[0].html, sent[0].subject, caplog.text):
        assert SENTINEL not in part
    # Once per period: tomorrow's run doesn't repeat it.
    _run(app_sessions, on, sent)
    assert len(sent) == 1


def test_not_due_off_unverified_or_already_reminded_get_nothing(
    owner_engine: Engine, app_sessions: sessionmaker[Session], on: Settings
) -> None:
    _due_user(owner_engine, "later", due_in=3)
    _due_user(owner_engine, "reminded", reminded=today_eat().isoformat())
    off = _due_user(owner_engine, "off")
    unverified = _due_user(owner_engine, "unconfirmed")
    with owner_engine.begin() as c:
        c.execute(text("UPDATE users SET checkin_interval_weeks = NULL WHERE id = :u"), {"u": off})
        c.execute(
            text("UPDATE users SET email_verified_at = NULL WHERE id = :u"), {"u": unverified}
        )
    sent: list[EmailMessage] = []
    _run(app_sessions, on, sent)
    assert sent == []


def test_overdue_period_reminded_earlier_gets_a_new_one(
    owner_engine: Engine, app_sessions: sessionmaker[Session], on: Settings
) -> None:
    # Reminded for the previous period (before this period's date): due again.
    _due_user(owner_engine, "again", reminded=(today_eat() - timedelta(days=50)).isoformat())
    sent: list[EmailMessage] = []
    _run(app_sessions, on, sent)
    assert [m.kind for m in sent] == ["checkin_reminder"]


def test_reminders_never_use_the_digest_reserve_and_retry_tomorrow(
    owner_engine: Engine, app_sessions: sessionmaker[Session], settings: Settings
) -> None:
    tight = make_settings(
        database_url=settings.database_url,
        dira_enabled=True,
        email_daily_limit=2,
        email_digest_reserve=1,
    )
    for i in range(3):
        _due_user(owner_engine, f"user{i}")
    sent: list[EmailMessage] = []
    counts = _run(app_sessions, tight, sent)
    assert len(sent) == 1  # limit 2 minus the reserve of 1
    assert counts.checkin_skipped_budget == 2  # type: ignore[attr-defined]
    with owner_engine.connect() as c:
        waiting = c.execute(
            text("SELECT count(*) FROM users WHERE last_checkin_email_on IS NULL")
        ).scalar_one()
    assert waiting == 2  # still due tomorrow


def test_failed_send_releases_the_claim(
    owner_engine: Engine, app_sessions: sessionmaker[Session], on: Settings
) -> None:
    uid = _due_user(owner_engine, "flaky")

    def boom(message: EmailMessage) -> None:
        raise EmailSendError("down")

    counts = run(app_sessions, Mailer(app_sessions, on, boom), on)
    assert counts.checkin_failed == 1
    with owner_engine.connect() as c:
        last = c.execute(
            text("SELECT last_checkin_email_on FROM users WHERE id = :u"), {"u": uid}
        ).scalar_one()
    assert last is None


def test_nothing_when_dira_is_off(
    owner_engine: Engine, app_sessions: sessionmaker[Session], settings: Settings
) -> None:
    uid = _due_user(owner_engine, "flagoff")
    make_application(owner_engine, uid, "Due soon", today_eat() + timedelta(days=1))
    sent: list[EmailMessage] = []
    _run(app_sessions, settings, sent)
    assert [m.kind for m in sent] == ["digest"]
    assert "/dira" not in sent[0].text
