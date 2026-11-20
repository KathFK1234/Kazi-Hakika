"""Request-scoped dependencies: who is signed in, their RLS-bound DB session, CSRF."""

import hmac
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_sessionmaker, set_session_user
from app.models import User, UserSession
from app.services.email import Mailer, resend_transport
from app.services.ratelimit import Limit, RateLimiter
from app.services.tokens import hash_token

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def client_ip(request: Request) -> str:
    settings: Settings = request.app.state.settings
    hops = settings.trusted_proxy_hops
    if hops:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        # Each trusted proxy appends the address it saw; read from the right.
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


def get_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.limiter
    return limiter


def enforce(request: Request, limit: Limit, key: str) -> None:
    limiter = get_limiter(request)
    if not limiter.hit(limit, key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait and try again.",
            headers={"Retry-After": str(limiter.retry_after(limit, key))},
        )


def get_system_db(request: Request) -> Iterator[Session]:
    """A session with no RLS identity: only for auth tables (users, sessions, tokens)."""
    with get_sessionmaker(request)() as session:
        yield session


SystemDb = Annotated[Session, Depends(get_system_db)]


def get_mailer(request: Request) -> Mailer:
    mailer: Mailer | None = getattr(request.app.state, "mailer", None)
    if mailer is None:
        settings: Settings = request.app.state.settings
        mailer = Mailer(get_sessionmaker(request), settings, resend_transport(settings))
        request.app.state.mailer = mailer
    return mailer


MailerDep = Annotated[Mailer, Depends(get_mailer)]


@dataclass(frozen=True)
class Auth:
    user_id: uuid.UUID
    session_id: uuid.UUID
    csrf_token: str


def optional_auth(request: Request, db: SystemDb) -> Auth | None:
    settings: Settings = request.app.state.settings
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw or len(raw) > 128:
        return None
    row = db.execute(
        select(UserSession.id, UserSession.user_id, UserSession.csrf_token)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == hash_token(raw),
            UserSession.expires_at > datetime.now(UTC),
            User.deleted_at.is_(None),
        )
    ).one_or_none()
    db.rollback()  # end the read transaction; this session is reused by nobody else
    if row is None:
        return None
    auth = Auth(user_id=row.user_id, session_id=row.id, csrf_token=row.csrf_token)
    request.state.user_id = auth.user_id
    return auth


def require_auth(request: Request, auth: Annotated[Auth | None, Depends(optional_auth)]) -> Auth:
    if auth is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    if request.method in UNSAFE_METHODS:
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent.encode(), auth.csrf_token.encode()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed.")
    return auth


AuthDep = Annotated[Auth, Depends(require_auth)]


def get_user_db(request: Request, auth: AuthDep) -> Iterator[Session]:
    """A session bound to the signed-in user: RLS shows only their rows."""
    with get_sessionmaker(request)() as session:
        set_session_user(session, auth.user_id)
        yield session


UserDb = Annotated[Session, Depends(get_user_db)]
