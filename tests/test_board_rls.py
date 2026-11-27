"""Board tables: who may read and change what, enforced by Postgres itself."""

import uuid

import psycopg
import pytest
from sqlalchemy import Engine, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app import admins
from app.db import set_session_job, set_session_user
from tests.factories import make_board_role, make_user


def _scalar(
    sessions: sessionmaker[Session],
    user: uuid.UUID | None,
    sql: str,
    params: dict[str, object] | None = None,
    *,
    job: bool = False,
    commit: bool = False,
) -> object:
    with sessions() as s:
        set_session_user(s, user)
        if job:
            set_session_job(s)
        value = s.execute(text(sql), params or {}).scalar()
        if commit:
            s.commit()
        return value


VISIBLE = "SELECT count(*) FROM board_roles"


def test_everyone_reads_only_approved_visible_posts(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    poster, other = make_user(owner_engine), make_user(owner_engine)
    make_board_role(owner_engine, poster)
    make_board_role(owner_engine, poster, status="unverified")
    make_board_role(owner_engine, poster, approved=False)
    for status in ("flagged", "hidden", "archived"):
        make_board_role(owner_engine, poster, status=status)

    assert _scalar(app_sessions, None, VISIBLE) == 2
    assert _scalar(app_sessions, other, VISIBLE) == 2
    # Posters see all of their own, whatever the status.
    assert _scalar(app_sessions, poster, VISIBLE) == 6


def test_admins_and_the_job_see_everything(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    poster = make_user(owner_engine)
    admin = make_user(owner_engine, admin=True, verified=True)
    unconfirmed_admin = make_user(owner_engine, admin=True)
    make_board_role(owner_engine, poster, status="flagged")
    make_board_role(owner_engine, poster, approved=False)

    assert _scalar(app_sessions, admin, VISIBLE) == 2
    assert _scalar(app_sessions, None, VISIBLE, job=True) == 2
    # Admin rights need a confirmed email.
    assert _scalar(app_sessions, unconfirmed_admin, VISIBLE) == 0


def test_posters_cannot_change_status_but_admins_can(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    poster = make_user(owner_engine)
    admin = make_user(owner_engine, admin=True, verified=True)
    role = make_board_role(owner_engine, poster, status="flagged")
    set_verified = "UPDATE board_roles SET status = 'verified' WHERE id = :r RETURNING id"

    assert _scalar(app_sessions, poster, set_verified, {"r": role}, commit=True) is None
    assert _scalar(app_sessions, admin, set_verified, {"r": role}, commit=True) == role


def test_posts_are_inserted_only_as_yourself(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    with app_sessions() as s:
        set_session_user(s, a)
        with pytest.raises(DBAPIError, match="row-level security"):
            s.execute(
                text(
                    "INSERT INTO board_roles (posted_by, title, company_name, job_url, "
                    "company_domain, status) VALUES (:b, 't', 'c', 'https://x.co', 'x.co', "
                    "'verified')"
                ),
                {"b": b},
            )


def test_posters_delete_only_their_own(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    mine, theirs = make_board_role(owner_engine, a), make_board_role(owner_engine, b)
    sql = "DELETE FROM board_roles WHERE id = :r RETURNING id"
    assert _scalar(app_sessions, a, sql, {"r": theirs}, commit=True) is None
    assert _scalar(app_sessions, a, sql, {"r": mine}, commit=True) == mine


def test_app_role_cannot_make_anyone_admin(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    user = make_user(owner_engine)
    with app_sessions() as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(text("UPDATE users SET is_admin = true WHERE id = :u"), {"u": user})
    with app_sessions() as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(
            text(
                "INSERT INTO users (email, password_hash, handle, is_admin) "
                "VALUES ('x@example.com', 'x', 'sneaky', true)"
            )
        )
    # Ordinary columns still update.
    with app_sessions() as s:
        s.execute(text("UPDATE users SET reminder_opt_in = false WHERE id = :u"), {"u": user})
        s.commit()


def _report(sessions: sessionmaker[Session], user: uuid.UUID, role: uuid.UUID) -> None:
    with sessions() as s:
        set_session_user(s, user)
        s.execute(
            text("INSERT INTO reports (board_role_id, reported_by, reason) VALUES (:r, :u, 'fee')"),
            {"r": role, "u": user},
        )
        s.commit()


def test_three_reports_hide_a_role_and_each_user_reports_once(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    role = make_board_role(owner_engine, make_user(owner_engine))
    reporters = [make_user(owner_engine) for _ in range(3)]
    _report(app_sessions, reporters[0], role)
    _report(app_sessions, reporters[1], role)
    with owner_engine.connect() as c:
        row = c.execute(
            text("SELECT report_count, status FROM board_roles WHERE id = :r"), {"r": role}
        ).one()
    assert tuple(row) == (2, "verified")

    with pytest.raises(DBAPIError, match="uq_reports_role_reporter"):
        _report(app_sessions, reporters[0], role)

    _report(app_sessions, reporters[2], role)
    with owner_engine.connect() as c:
        row = c.execute(
            text("SELECT report_count, status FROM board_roles WHERE id = :r"), {"r": role}
        ).one()
    assert tuple(row) == (3, "hidden")


def test_reports_are_seen_by_the_reporter_and_admins_only(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    role = make_board_role(owner_engine, make_user(owner_engine))
    reporter, other = make_user(owner_engine), make_user(owner_engine)
    admin = make_user(owner_engine, admin=True, verified=True)
    _report(app_sessions, reporter, role)
    count = "SELECT count(*) FROM reports"
    assert _scalar(app_sessions, reporter, count) == 1
    assert _scalar(app_sessions, other, count) == 0
    assert _scalar(app_sessions, None, count) == 0
    assert _scalar(app_sessions, admin, count) == 1
    # Filing a report in someone else's name is refused.
    with app_sessions() as s:
        set_session_user(s, other)
        with pytest.raises(DBAPIError, match="row-level security"):
            s.execute(
                text(
                    "INSERT INTO reports (board_role_id, reported_by, reason) "
                    "VALUES (:r, :u, 'fake')"
                ),
                {"r": role, "u": reporter},
            )


def test_only_admins_change_the_nea_list(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    user = make_user(owner_engine, verified=True)
    admin = make_user(owner_engine, admin=True, verified=True)
    insert = (
        "INSERT INTO nea_agencies (name, name_key, licence_status, synced_at) "
        "VALUES ('Acme Agency', :k, 'active', now()) RETURNING id"
    )
    with app_sessions() as s:
        set_session_user(s, user)
        with pytest.raises(DBAPIError, match="row-level security"):
            s.execute(text(insert), {"k": "acmeagency"})
    _scalar(app_sessions, admin, insert, {"k": "acmeagency"}, commit=True)
    assert _scalar(app_sessions, None, "SELECT count(*) FROM nea_agencies") == 1


def test_admin_emails_grant_and_revoke(
    owner_engine: Engine, database_urls: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    keep = make_user(owner_engine, "keeper", verified=True)
    old = make_user(owner_engine, "former", admin=True, verified=True)
    owner_url = make_url(database_urls[0]).set(drivername="postgresql")
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", owner_url.render_as_string(hide_password=False))
    monkeypatch.setenv("ADMIN_EMAILS", " Keeper@Example.com ,")
    assert admins.main() == 0
    with psycopg.connect(owner_url.render_as_string(hide_password=False)) as c:
        rows: dict[uuid.UUID, bool] = dict(c.execute("SELECT id, is_admin FROM users").fetchall())
    assert rows[keep] is True and rows[old] is False


@pytest.mark.parametrize(
    "raw", ["not-an-email", "a@x.com b@y.com", ",".join(f"u{i}@x.com" for i in range(6))]
)
def test_admin_emails_refuses_bad_lists(raw: str) -> None:
    with pytest.raises(ValueError):
        admins.parse(raw)
