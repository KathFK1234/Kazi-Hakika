import logging
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.jobs.daily import run
from app.services.digest import today_eat
from app.services.email import EmailMessage, EmailSendError, Mailer
from tests.conftest import make_settings
from tests.factories import make_application, make_user


def _verified_user(owner: Engine, handle: str, **cols: object) -> uuid.UUID:
    uid = make_user(owner, handle)
    with owner.begin() as c:
        c.execute(text("UPDATE users SET email_verified_at = now() WHERE id = :u"), {"u": uid})
        for col, value in cols.items():
            c.execute(text(f"UPDATE users SET {col} = :v WHERE id = :u"), {"v": value, "u": uid})  # noqa: S608
    return uid


@pytest.fixture
def mailer(
    app_sessions: sessionmaker[Session], settings: Settings
) -> tuple[Mailer, list[EmailMessage]]:
    sent: list[EmailMessage] = []
    return Mailer(app_sessions, settings, sent.append), sent


def test_one_digest_per_user_with_only_their_deadlines(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    mailer: tuple[Mailer, list[EmailMessage]],
) -> None:
    today = today_eat()
    a = _verified_user(owner_engine, "alice")
    b = _verified_user(owner_engine, "bob")
    make_application(owner_engine, a, "Due today", today)
    make_application(owner_engine, a, "Due in 3", today + timedelta(days=3))
    make_application(owner_engine, a, "Due in 4", today + timedelta(days=4))
    make_application(owner_engine, a, "Overdue", today - timedelta(days=1))
    make_application(owner_engine, b, "Bob's role", today + timedelta(days=1))

    m, sent = mailer
    counts = run(app_sessions, m, settings)
    assert counts.sent == 2
    by_to = {msg.to: msg for msg in sent}
    alice = by_to["alice@example.com"].text
    assert "Due today" in alice and "Due in 3" in alice
    assert "Due in 4" not in alice and "Overdue" not in alice
    assert "Bob's role" not in alice
    assert "Bob's role" in by_to["bob@example.com"].text

    # A second run the same day sends nothing more.
    assert run(app_sessions, m, settings).sent == 0
    assert len(sent) == 2


def test_skips_opted_out_unverified_and_finished_roles(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    mailer: tuple[Mailer, list[EmailMessage]],
) -> None:
    today = today_eat()
    off = _verified_user(owner_engine, "optedout", reminder_opt_in=False)
    unverified = make_user(owner_engine, "unverified")
    done = _verified_user(owner_engine, "rejected")
    for uid in (off, unverified):
        make_application(owner_engine, uid, "x", today)
    rid = make_application(owner_engine, done, "x", today)
    with owner_engine.begin() as c:
        c.execute(text("UPDATE applications SET stage = 'rejected' WHERE id = :i"), {"i": rid})

    m, sent = mailer
    counts = run(app_sessions, m, settings)
    assert sent == []
    assert counts.nothing_due == 1


def test_budget_runs_short_oldest_signups_first(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    database_urls: tuple[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    today = today_eat()
    for i in range(4):
        uid = _verified_user(owner_engine, f"user{i}", created_at=f"2026-01-0{i + 1}T00:00:00Z")
        make_application(owner_engine, uid, "r", today)
    small = make_settings(database_url=database_urls[1], email_daily_limit=2)
    sent: list[EmailMessage] = []
    with caplog.at_level(logging.WARNING):
        counts = run(app_sessions, Mailer(app_sessions, small, sent.append), small)
    assert [m.to for m in sent] == ["user0@example.com", "user1@example.com"]
    assert counts.skipped_budget == 2
    assert "email budget used up" in caplog.text


def test_failed_send_is_retried_next_run(
    owner_engine: Engine, app_sessions: sessionmaker[Session], settings: Settings
) -> None:
    uid = _verified_user(owner_engine, "retry")
    make_application(owner_engine, uid, "r", today_eat())

    def down(message: EmailMessage) -> None:
        raise EmailSendError("down")

    assert run(app_sessions, Mailer(app_sessions, settings, down), settings).failed == 1
    sent: list[EmailMessage] = []
    assert run(app_sessions, Mailer(app_sessions, settings, sent.append), settings).sent == 1


def test_purges_expired_sessions_and_tokens(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    mailer: tuple[Mailer, list[EmailMessage]],
) -> None:
    uid = make_user(owner_engine, "purge")
    with owner_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO sessions (user_id, token_hash, csrf_token, expires_at) VALUES "
                "(:u, 'old', 'c', now() - interval '1 day'), "
                "(:u, 'live', 'c', now() + interval '1 day')"
            ),
            {"u": uid},
        )
    counts = run(app_sessions, mailer[0], settings)
    assert counts.sessions_purged == 1
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT token_hash FROM sessions")).scalars().all() == ["live"]


def test_digest_preview(client: TestClient, outbox: list[EmailMessage]) -> None:
    from tests.helpers import signed_in

    me = signed_in(client, outbox, "preview")
    assert me.get("/api/account/digest-preview").json()["will_send"] is False
    me.post(
        "/api/applications",
        json={"role_title": "Soon", "company_name": "X", "deadline": today_eat().isoformat()},
    )
    preview = me.get("/api/account/digest-preview").json()
    assert preview["will_send"] is True
    assert [i["role_title"] for i in preview["items"]] == ["Soon"]


def test_main_exits_0_on_success(
    monkeypatch: pytest.MonkeyPatch, database_urls: tuple[str, str]
) -> None:
    from app.jobs import daily

    monkeypatch.setattr(daily, "get_settings", lambda: make_settings(database_url=database_urls[1]))
    assert daily.main() == 0


def test_main_exits_1_on_database_failure_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.jobs import daily

    unreachable = "postgresql+psycopg://kazi_app:s3cret-pw@127.0.0.1:1/nowhere"
    monkeypatch.setattr(daily, "get_settings", lambda: make_settings(database_url=unreachable))
    with caplog.at_level(logging.INFO):
        assert daily.main() == 1
    assert "daily job failed" in caplog.text
    assert "s3cret-pw" not in caplog.text


def test_deletes_only_old_unconfirmed_empty_accounts(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    mailer: tuple[Mailer, list[EmailMessage]],
) -> None:
    old = "now() - interval '31 days'"
    stale = make_user(owner_engine, "stale")
    in_use = make_user(owner_engine, "inuse")
    make_application(owner_engine, in_use, "keeps the account")
    confirmed = _verified_user(owner_engine, "confirmed")
    recent = make_user(owner_engine, "recent")
    with owner_engine.begin() as c:
        c.execute(
            text(f"UPDATE users SET created_at = {old} WHERE id IN (:a, :b, :c)"),  # noqa: S608
            {"a": stale, "b": in_use, "c": confirmed},
        )
    counts = run(app_sessions, mailer[0], settings)
    assert counts.unconfirmed_accounts_deleted == 1
    with owner_engine.connect() as c:
        left = set(c.execute(text("SELECT handle FROM users")).scalars())
    assert left == {"inuse", "confirmed", "recent"}
    assert recent  # created now, so it stays
