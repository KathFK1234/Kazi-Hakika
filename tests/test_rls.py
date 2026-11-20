"""Row-level security holds even for raw SQL, independent of the API's own filters."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db import set_session_user
from app.models import Application, StageEvent
from tests.factories import make_application, make_user


def _count_as(
    sessions: sessionmaker[Session],
    user: uuid.UUID | None,
    sql: str,
    params: dict[str, object] | None = None,
) -> int:
    with sessions() as s:
        set_session_user(s, user)
        return int(s.execute(text(sql), params or {}).scalar_one())


def test_app_role_cannot_bypass_rls(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert row == (False, False)


def test_raw_sql_under_a_sees_none_of_bs_rows(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    make_application(owner_engine, a)
    for _ in range(3):
        make_application(owner_engine, b)

    sql_for_b = "SELECT count(*) FROM applications WHERE user_id = :b"
    assert _count_as(app_sessions, a, sql_for_b, {"b": b}) == 0
    assert _count_as(app_sessions, a, "SELECT count(*) FROM applications") == 1
    assert _count_as(app_sessions, b, "SELECT count(*) FROM applications") == 3


def test_no_user_set_sees_nothing(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    make_application(owner_engine, make_user(owner_engine))
    assert _count_as(app_sessions, None, "SELECT count(*) FROM applications") == 0


def test_cannot_insert_rows_for_another_user(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    with app_sessions() as s:
        set_session_user(s, a)
        s.add(Application(user_id=b, role_title="x", company_name="y"))
        with pytest.raises(DBAPIError, match="row-level security"):
            s.commit()


def test_cannot_update_or_delete_another_users_rows(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    b_app = make_application(owner_engine, b, title="B's role")
    with app_sessions() as s:
        set_session_user(s, a)
        updated = s.execute(text("UPDATE applications SET role_title = 'hacked'"))
        deleted = s.execute(text("DELETE FROM applications"))
        s.commit()
    assert updated.rowcount == 0  # type: ignore[attr-defined]
    assert deleted.rowcount == 0  # type: ignore[attr-defined]
    with owner_engine.connect() as conn:
        title = conn.execute(
            text("SELECT role_title FROM applications WHERE id = :i"), {"i": b_app}
        ).scalar_one()
    assert title == "B's role"


def test_stage_event_must_match_application_owner(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a, b = make_user(owner_engine), make_user(owner_engine)
    b_app = make_application(owner_engine, b)
    with app_sessions() as s:
        set_session_user(s, a)
        s.add(
            StageEvent(
                application_id=b_app,
                user_id=a,
                to_stage="applied",
                at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_rls_identity_survives_commit_and_is_cleared_after(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    a = make_user(owner_engine)
    with app_sessions() as s:
        set_session_user(s, a)
        s.add(Application(user_id=a, role_title="one", company_name="c"))
        s.commit()
        # A new transaction after commit must still carry the identity.
        assert len(s.scalars(select(Application)).all()) == 1
    # A fresh session on a (likely reused) pooled connection carries none.
    assert _count_as(app_sessions, None, "SELECT count(*) FROM applications") == 0


def test_setting_user_mid_transaction_is_refused(app_sessions: sessionmaker[Session]) -> None:
    with app_sessions() as s:
        s.execute(text("SELECT 1"))
        with pytest.raises(RuntimeError):
            set_session_user(s, uuid.uuid4())
