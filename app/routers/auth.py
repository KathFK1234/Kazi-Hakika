"""Sign up, email verification, log in/out and password reset.

Responses never reveal whether an email address has an account: sign-up and
reset requests always answer the same way, and unknown emails cost the same
password-hashing time as known ones.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import (
    Auth,
    AuthDep,
    MailerDep,
    SettingsDep,
    SystemDb,
    client_ip,
    enforce,
    optional_auth,
)
from app.models import AuthToken, User, UserSession
from app.services import email_templates
from app.services.passwords import hash_password, needs_rehash, verify_password
from app.services.ratelimit import (
    LOGIN_PER_EMAIL,
    LOGIN_PER_IP,
    RESET_PER_EMAIL,
    RESET_PER_IP,
    SIGNUP_PER_IP,
    TOKEN_USE_PER_IP,
    VERIFY_RESEND_PER_USER,
)
from app.services.tokens import hash_token, new_token

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)
PASSWORD_MIN, PASSWORD_MAX = 10, 128
HANDLE_RE = re.compile(r"^[a-z0-9_-]{3,30}$")
RESERVED_HANDLES = frozenset(
    {"admin", "administrator", "support", "help", "kazi", "kazihakika", "kazi-hakika",
     "deleted-user", "moderator", "staff", "system", "root", "null", "anonymous", "api"}
)  # fmt: skip
CHECK_EMAIL = {"detail": "Check your email to finish signing up."}
RESET_SENT = {"detail": "If that email has an account, a reset link is on its way."}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


def _check_password(value: str) -> str:
    if not PASSWORD_MIN <= len(value) <= PASSWORD_MAX:
        raise ValueError(f"Password must be {PASSWORD_MIN} to {PASSWORD_MAX} characters.")
    if not value.strip():
        raise ValueError("Password can't be only spaces.")
    return value


class SignupIn(_Strict):
    email: EmailStr = Field(max_length=254)
    password: str
    handle: str

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("handle")
    @classmethod
    def _handle(cls, v: str) -> str:
        v = v.strip().lower()
        if not HANDLE_RE.fullmatch(v):
            raise ValueError("Handle: 3 to 30 letters, numbers, - or _.")
        if v in RESERVED_HANDLES:
            raise ValueError("That handle is reserved. Please pick another.")
        return v

    _pw = field_validator("password")(_check_password)


class LoginIn(_Strict):
    email: str = Field(max_length=254)
    password: str = Field(max_length=PASSWORD_MAX)


class TokenIn(_Strict):
    token: str = Field(min_length=20, max_length=128)


class ResetRequestIn(_Strict):
    email: str = Field(max_length=254)


class ResetConfirmIn(TokenIn):
    password: str

    _pw = field_validator("password")(_check_password)


class MeOut(BaseModel):
    id: str
    email: str
    handle: str
    email_verified: bool
    reminder_opt_in: bool
    csrf_token: str


def _issue_token(db: Session, user_id: object, purpose: str, ttl: timedelta) -> str:
    # One live token per purpose: issuing a new one retires the old.
    db.execute(delete(AuthToken).where(AuthToken.user_id == user_id, AuthToken.purpose == purpose))
    token = new_token()
    db.add(
        AuthToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    return token


def _consume_token(db: Session, token: str, purpose: str) -> User | None:
    now = datetime.now(UTC)
    row = db.execute(
        update(AuthToken)
        .where(
            AuthToken.token_hash == hash_token(token),
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(AuthToken.user_id)
    ).one_or_none()
    if row is None:
        return None
    return db.get(User, row.user_id)


def _start_session(db: Session, response: Response, settings: Settings, user: User) -> None:
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


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
def signup(
    body: SignupIn, request: Request, db: SystemDb, mailer: MailerDep, settings: SettingsDep
) -> dict[str, str]:
    enforce(request, SIGNUP_PER_IP, client_ip(request))
    brand = email_templates.Brand.from_settings(settings)

    existing = db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        hash_password(body.password)  # same cost as the new-account path
        db.rollback()
        mailer.send(email_templates.already_registered(brand, body.email))
        return CHECK_EMAIL

    if db.scalar(select(User.id).where(User.handle == body.handle)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That handle is taken.")

    user = User(email=body.email, handle=body.handle, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race on the same email or handle.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That handle is taken.") from None
    token = _issue_token(db, user.id, "verify_email", VERIFY_TTL)
    db.commit()
    mailer.send(email_templates.verify_email(brand, user.email, user.handle, token))
    return CHECK_EMAIL


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, db: SystemDb, settings: SettingsDep
) -> dict[str, str]:
    email = body.email.strip().lower()
    enforce(request, LOGIN_PER_IP, client_ip(request))
    enforce(request, LOGIN_PER_EMAIL, email)

    user = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    password_ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not password_ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Wrong email or password.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    _start_session(db, response, settings, user)
    db.commit()
    return {"detail": "Signed in."}


@router.post("/logout")
def logout(auth: AuthDep, response: Response, db: SystemDb, settings: SettingsDep) -> Response:
    db.execute(delete(UserSession).where(UserSession.id == auth.session_id))
    db.commit()
    clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me")
def me(
    auth: Annotated[Auth | None, Depends(optional_auth)], db: SystemDb, response: Response
) -> MeOut:
    response.headers["Cache-Control"] = "no-store"
    if auth is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    user = db.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    return MeOut(
        id=str(user.id),
        email=user.email,
        handle=user.handle,
        email_verified=user.email_verified_at is not None,
        reminder_opt_in=user.reminder_opt_in,
        csrf_token=auth.csrf_token,
    )


@router.post("/verify-email")
def verify_email(body: TokenIn, request: Request, db: SystemDb) -> dict[str, str]:
    enforce(request, TOKEN_USE_PER_IP, client_ip(request))
    user = _consume_token(db, body.token, "verify_email")
    if user is None:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="This link has expired or was already used."
        )
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    db.commit()
    return {"detail": "Email confirmed."}


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(
    auth: AuthDep, request: Request, db: SystemDb, mailer: MailerDep, settings: SettingsDep
) -> dict[str, str]:
    enforce(request, VERIFY_RESEND_PER_USER, str(auth.user_id))
    user = db.get(User, auth.user_id)
    if user is None or user.email_verified_at is not None:
        return {"detail": "Your email is already confirmed."}
    token = _issue_token(db, user.id, "verify_email", VERIFY_TTL)
    db.commit()
    brand = email_templates.Brand.from_settings(settings)
    if not mailer.send(email_templates.verify_email(brand, user.email, user.handle, token)):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="We couldn't send email right now. Please try again tomorrow.",
        )
    return {"detail": "Check your email."}


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_reset(
    body: ResetRequestIn,
    request: Request,
    db: SystemDb,
    mailer: MailerDep,
    settings: SettingsDep,
) -> dict[str, str]:
    email = body.email.strip().lower()
    enforce(request, RESET_PER_IP, client_ip(request))
    enforce(request, RESET_PER_EMAIL, email)
    user = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None:
        return RESET_SENT
    token = _issue_token(db, user.id, "reset_password", RESET_TTL)
    db.commit()
    brand = email_templates.Brand.from_settings(settings)
    mailer.send(email_templates.password_reset(brand, user.email, token))
    return RESET_SENT


@router.post("/password-reset/confirm")
def confirm_reset(
    body: ResetConfirmIn, request: Request, response: Response, db: SystemDb, settings: SettingsDep
) -> dict[str, str]:
    enforce(request, TOKEN_USE_PER_IP, client_ip(request))
    user = _consume_token(db, body.token, "reset_password")
    if user is None:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="This link has expired or was already used."
        )
    user.password_hash = hash_password(body.password)
    # Following the emailed link proves the address too.
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    # Sign out everywhere, then sign in here.
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    _start_session(db, response, settings, user)
    db.commit()
    return {"detail": "Password changed."}
