"""Engine, sessions and the per-transaction RLS identity (app.user_id)."""

import uuid
from functools import lru_cache
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.config import Settings, get_settings

RLS_USER_KEY = "rls_user_id"


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_size,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
            "connect_timeout": 5,
        },
    )


@lru_cache
def _default_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(get_settings()), expire_on_commit=False)


def get_sessionmaker(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] | None = getattr(request.app.state, "sessionmaker", None)
    return factory or _default_sessionmaker()


@event.listens_for(Session, "after_begin")
def _set_rls_user(session: Session, transaction: SessionTransaction, connection: Any) -> None:
    """Every transaction starts by declaring whose rows it may see.

    `is_local=true` scopes the setting to the transaction, so a pooled
    connection never carries one user's identity into another request.
    An empty value matches no rows under the RLS policies.
    """
    user_id = session.info.get(RLS_USER_KEY)
    connection.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id) if user_id else ""},
    )


def set_session_user(session: Session, user_id: uuid.UUID | None) -> None:
    """Bind a session to a user. Takes effect from the next transaction.

    In requests, app.deps.get_user_db is the one place this is called; the
    daily job calls it per user.
    """
    if session.in_transaction():
        raise RuntimeError("Set the RLS user before the session starts a transaction")
    session.info[RLS_USER_KEY] = user_id
