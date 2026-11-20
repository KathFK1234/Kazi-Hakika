"""Browser sessions: create one (and its cookie), or clear the cookie."""

from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User, UserSession
from app.services.tokens import hash_token, new_token


def start_session(db: Session, response: Response, settings: Settings, user: User) -> None:
    token = new_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            csrf_token=new_token(),
            expires_at=datetime.now(UTC) + timedelta(days=settings.session_days),
        )
    )
    # Housekeeping without a scheduler: drop this user's expired sessions.
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id, UserSession.expires_at <= datetime.now(UTC)
        )
    )
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
    )
