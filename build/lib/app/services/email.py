"""Every email goes through Mailer.send(), which enforces the daily budget.

The budget row is incremented and the email handed to Resend inside one
transaction: if the send fails, the increment rolls back; if the day's budget
is used up, the email is refused and logged, never sent.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    # A short label for logs (never the address or the content).
    kind: str


Transport = Callable[[EmailMessage], None]


class EmailSendError(Exception):
    pass


def resend_transport(settings: Settings) -> Transport:
    if settings.resend_api_key is None:
        return log_transport(settings)
    api_key = settings.resend_api_key.get_secret_value()

    def send(message: EmailMessage) -> None:
        try:
            response = httpx.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": settings.email_from,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.text,
                    "html": message.html,
                },
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise EmailSendError(type(exc).__name__) from None
        if response.status_code >= 400:
            raise EmailSendError(f"Resend returned {response.status_code}")

    return send


def log_transport(settings: Settings) -> Transport:
    """No API key: nothing leaves the machine. Development prints the text so
    links (verification, reset) can be followed; production prints nothing."""

    def send(message: EmailMessage) -> None:
        if settings.is_production:
            log.warning("email not sent: RESEND_API_KEY is not set (kind=%s)", message.kind)
        else:
            log.info("DEV EMAIL (kind=%s) %s\n%s", message.kind, message.subject, message.text)

    return send


class Mailer:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings, transport: Transport):
        self.sessions = sessions
        self.limit = settings.email_daily_limit
        self.transport = transport

    def remaining_today(self) -> int:
        with self.sessions() as s:
            sent = s.execute(
                text("SELECT sent_count FROM email_budget WHERE day = :d"), {"d": _today()}
            ).scalar_one_or_none()
        return max(self.limit - (sent or 0), 0)

    def send(self, message: EmailMessage) -> bool:
        """True if sent. False if refused by the budget or the provider failed."""
        with self.sessions() as s, s.begin():
            # Atomic check-and-increment: the row lock serialises concurrent sends.
            counted = s.execute(
                text(
                    """
                    INSERT INTO email_budget AS b (day, sent_count) VALUES (:d, 1)
                    ON CONFLICT (day) DO UPDATE
                        SET sent_count = b.sent_count + 1, updated_at = now()
                        WHERE b.sent_count < :limit
                    RETURNING sent_count
                    """
                ),
                {"d": _today(), "limit": self.limit},
            ).scalar_one_or_none()
            if counted is None or counted > self.limit:
                s.rollback()
                log.warning(
                    "email refused: daily budget of %d used up (kind=%s)", self.limit, message.kind
                )
                return False
            try:
                self.transport(message)
            except EmailSendError as exc:
                s.rollback()
                log.error("email failed (kind=%s): %s", message.kind, exc)
                return False
        log.info("email sent (kind=%s, today=%d/%d)", message.kind, counted, self.limit)
        return True


def _today() -> date:
    """Budgets reset at midnight UTC, matching Resend's daily limit."""
    return datetime.now(UTC).date()
