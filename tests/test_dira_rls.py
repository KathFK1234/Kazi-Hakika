"""Check-ins and entries: forced RLS, like applications (acceptance check for 3b.1)."""

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.db import set_session_user
from tests.factories import make_application, make_user


def make_checkin(owner: Engine, user: uuid.UUID, day: str = "2026-11-01") -> uuid.UUID:
    with owner.begin() as c:
        return uuid.UUID(
            str(
                c.execute(
                    text(
                        "INSERT INTO checkins (user_id, on_date, ideal_role) "
                        "VALUES (:u, :d, 'Backend engineer in fintech') RETURNING id"
                    ),
                    {"u": user, "d": day},
                ).scalar_one()
            )
        )


def make_entry(owner: Engine, user: uuid.UUID, app: uuid.UUID | None = None) -> uuid.UUID:
    with owner.begin() as c:
        return uuid.UUID(
            str(
                c.execute(
                    text(
                        "INSERT INTO entries (user_id, kind, text, happened_on, application_id) "
                        "VALUES (:u, 'win', 'Shipped it', current_date, :a) RETURNING id"
                    ),
                    {"u": user, "a": app},
                ).scalar_one()
            )
        )


def _as(
    sessions: sessionmaker[Session], user: uuid.UUID | None, sql: str, **params: object
) -> object:
    with sessions() as s:
        set_session_user(s, user)
        value = s.execute(text(sql), params).scalar()
        s.commit()
        return value


SQL = {
    "checkins": {
        "all": "SELECT count(*) FROM checkins",
        "mine": "SELECT count(*) FROM checkins WHERE user_id = :u",
        "one": "SELECT count(*) FROM checkins WHERE id = :t",
        "update": "UPDATE checkins SET updated_at = now() WHERE id = :t RETURNING id",
        "delete": "DELETE FROM checkins WHERE id = :t RETURNING id",
    },
    "entries": {
        "all": "SELECT count(*) FROM entries",
        "mine": "SELECT count(*) FROM entries WHERE user_id = :u",
        "one": "SELECT count(*) FROM entries WHERE id = :t",
        "update": "UPDATE entries SET updated_at = now() WHERE id = :t RETURNING id",
        "delete": "DELETE FROM entries WHERE id = :t RETURNING id",
    },
}


@pytest.mark.parametrize("table", ["checkins", "entries"])
def test_users_never_touch_each_others_rows(
    table: str, owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    make = make_checkin if table == "checkins" else make_entry
    make(owner_engine, a)
    theirs = make(owner_engine, b)
    sql = SQL[table]

    assert _as(app_sessions, a, sql["all"]) == 1
    assert _as(app_sessions, a, sql["mine"], u=b) == 0
    assert _as(app_sessions, b, sql["mine"], u=b) == 1
    assert _as(app_sessions, a, sql["one"], t=theirs) == 0
    assert _as(app_sessions, None, sql["all"]) == 0
    assert _as(app_sessions, a, sql["update"], t=theirs) is None
    assert _as(app_sessions, a, sql["delete"], t=theirs) is None
    assert _as(app_sessions, b, sql["one"], t=theirs) == 1


def test_cannot_insert_a_checkin_for_someone_else(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    with app_sessions() as s:
        set_session_user(s, a)
        with pytest.raises(DBAPIError, match="row-level security"):
            s.execute(
                text(
                    "INSERT INTO checkins (user_id, on_date, ideal_role) "
                    "VALUES (:b, current_date, 'x')"
                ),
                {"b": b},
            )


def test_entry_cannot_point_at_someone_elses_application(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    b_app = make_application(owner_engine, b)
    with app_sessions() as s:
        set_session_user(s, a)
        with pytest.raises(DBAPIError, match="fk_entries_application_owner"):
            s.execute(
                text(
                    "INSERT INTO entries (user_id, kind, text, happened_on, application_id) "
                    "VALUES (:a, 'learning', 'x', current_date, :app)"
                ),
                {"a": a, "app": b_app},
            )


def test_entry_outlives_its_application(owner_engine: Engine) -> None:
    a = make_user(owner_engine)
    app = make_application(owner_engine, a)
    entry = make_entry(owner_engine, a, app)
    with owner_engine.begin() as c:
        c.execute(text("DELETE FROM applications WHERE id = :a"), {"a": app})
        row = c.execute(
            text("SELECT user_id, application_id FROM entries WHERE id = :e"), {"e": entry}
        ).one()
    assert row.user_id == a and row.application_id is None


@pytest.mark.parametrize(
    "tags",
    [["Backend"], ["a b"], ["-x"], ["x" * 31], ["a", "b", "c", "d", "e", "f"]],
)
def test_tag_rules_hold_in_the_database(tags: list[str], owner_engine: Engine) -> None:
    app = make_application(owner_engine, make_user(owner_engine))
    with owner_engine.begin() as c, pytest.raises(DBAPIError, match=r"tags_valid|too long"):
        c.execute(text("UPDATE applications SET tags = :t WHERE id = :a"), {"t": tags, "a": app})


def test_one_checkin_a_day_and_done_only_for_goals(owner_engine: Engine) -> None:
    a = make_user(owner_engine)
    make_checkin(owner_engine, a)
    with pytest.raises(DBAPIError, match="uq_checkins_user_id_on_date"):
        make_checkin(owner_engine, a)
    with owner_engine.begin() as c, pytest.raises(DBAPIError, match="done_only_for_goals"):
        c.execute(
            text(
                "INSERT INTO entries (user_id, kind, text, happened_on, done_at) "
                "VALUES (:a, 'win', 'x', current_date, now())"
            ),
            {"a": a},
        )


def test_app_role_may_write_the_checkin_settings(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a = make_user(owner_engine)
    with app_sessions() as s:
        s.execute(
            text(
                "UPDATE users SET checkin_interval_weeks = 6, next_checkin_on = current_date, "
                "weekly_target = 3, last_checkin_email_on = NULL WHERE id = :a"
            ),
            {"a": a},
        )
        s.commit()
