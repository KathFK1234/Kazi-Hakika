"""Daily job, run once by a Railway cron service (06:00 EAT = 03:00 UTC):

    python -m app.jobs.daily

Sends each opted-in, verified user at most one digest of deadlines in the
next 3 days (oldest sign-ups first if the email budget runs short), clears
expired sessions and tokens, logs counts and exits. No loops, no scheduler.
"""

import logging
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import make_engine, set_session_user
from app.errors import describe_db_error
from app.models import AuthToken, User, UserSession
from app.services.digest import digest_message, today_eat, upcoming
from app.services.email import Mailer, resend_transport
from app.services.email_templates import Brand

log = logging.getLogger("app.jobs.daily")

MAX_USERS_SCANNED = 10_000
MAX_CONSECUTIVE_FAILURES = 3
MAX_RUNTIME_SECONDS = 600


@dataclass
class Counts:
    scanned: int = 0
    sent: int = 0
    nothing_due: int = 0
    failed: int = 0
    skipped_budget: int = 0
    sessions_purged: int = 0
    tokens_purged: int = 0


def send_digests(
    sessions: sessionmaker[Session], mailer: Mailer, brand: Brand, today: date
) -> Counts:
    counts = Counts()
    started = time.monotonic()
    with sessions() as db:
        candidates = db.execute(
            select(User.id, User.email, User.handle)
            .where(
                User.reminder_opt_in.is_(True),
                User.email_verified_at.is_not(None),
                User.deleted_at.is_(None),
                or_(User.last_digest_on.is_(None), User.last_digest_on < today),
            )
            .order_by(User.created_at, User.id)
            .limit(MAX_USERS_SCANNED)
        ).all()

    failures = 0
    for index, user in enumerate(candidates):
        counts.scanned += 1
        if time.monotonic() - started > MAX_RUNTIME_SECONDS:
            log.warning("stopping: runtime cap reached")
            break
        if mailer.remaining_today() == 0:
            counts.skipped_budget = len(candidates) - index
            log.warning("stopping: email budget used up, %d users skipped", counts.skipped_budget)
            break

        with sessions() as db:
            set_session_user(db, user.id)
            items = upcoming(db, user.id, today)
        if not items:
            counts.nothing_due += 1
            continue

        # Claim today's digest first so a re-run can never send it twice.
        with sessions() as db, db.begin():
            claimed = db.execute(
                update(User)
                .where(
                    User.id == user.id,
                    or_(User.last_digest_on.is_(None), User.last_digest_on < today),
                )
                .values(last_digest_on=today)
                .returning(User.id)
            ).one_or_none()
        if claimed is None:
            continue

        if mailer.send(digest_message(brand, user.email, user.handle, items, today)):
            counts.sent += 1
            failures = 0
            continue

        # Not sent: release the claim so tomorrow's run (or a re-run) can try again.
        with sessions() as db, db.begin():
            db.execute(update(User).where(User.id == user.id).values(last_digest_on=None))
        counts.failed += 1
        failures += 1
        if failures >= MAX_CONSECUTIVE_FAILURES:
            log.error("stopping: %d sends failed in a row", failures)
            break
    return counts


def purge_expired(sessions: sessionmaker[Session], counts: Counts) -> None:
    now = datetime.now(UTC)
    with sessions() as db, db.begin():
        counts.sessions_purged = db.execute(
            delete(UserSession).where(UserSession.expires_at <= now)
        ).rowcount  # type: ignore[attr-defined]
        counts.tokens_purged = db.execute(
            delete(AuthToken).where(AuthToken.expires_at <= now)
        ).rowcount  # type: ignore[attr-defined]


def run(sessions: sessionmaker[Session], mailer: Mailer, settings: Settings) -> Counts:
    today = today_eat()
    counts = send_digests(sessions, mailer, Brand.from_settings(settings), today)
    purge_expired(sessions, counts)
    log.info("daily job done for %s: %s", today.isoformat(), counts)
    return counts


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,  # Railway shows stderr lines as errors
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    engine = make_engine(settings)
    try:
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        run(sessions, Mailer(sessions, settings, resend_transport(settings)), settings)
    except DBAPIError as exc:
        # Never the message: Postgres puts row values in it.
        log.error("daily job failed: %s", describe_db_error(exc))
        return 1
    except Exception:
        log.exception("daily job failed")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
