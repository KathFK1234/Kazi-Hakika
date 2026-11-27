"""Daily job, run once by a Railway cron service (06:00 EAT = 03:00 UTC):

    python -m app.jobs.daily

Sends each opted-in, verified user at most one digest of deadlines in the
next 3 days (oldest sign-ups first if the email budget runs short), clears
expired sessions and tokens, deletes accounts still unconfirmed and empty
30 days after sign-up, looks after the board (re-checks up to 200 links,
archives roles past their deadline or 60 days old without one, deletes
archived roles after 180 days), logs counts and exits. No loops, no
scheduler.
"""

import logging
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import ColumnElement, Row, and_, delete, or_, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import make_engine, set_session_job, set_session_user
from app.errors import describe_db_error
from app.models import (
    VISIBLE_STATUSES,
    Application,
    AuthToken,
    BoardRole,
    DomainCheck,
    User,
    UserSession,
)
from app.services.digest import digest_message, today_eat, upcoming
from app.services.email import Mailer, resend_transport
from app.services.email_templates import CHECKIN_REMINDER_KIND, Brand, checkin_reminder
from app.services.lookups import Fetcher
from app.services.verify import verdict

log = logging.getLogger("app.jobs.daily")

MAX_USERS_SCANNED = 10_000
MAX_CONSECUTIVE_FAILURES = 3
MAX_RUNTIME_SECONDS = 600
# Unconfirmed accounts with nothing tracked are removed after this long.
UNCONFIRMED_EMPTY_ACCOUNT_DAYS = 30
# Board upkeep.
MAX_LINK_RECHECKS = 200
RECHECK_WORKERS = 4
RECHECK_AFTER_HOURS = 20
UNDATED_ROLE_DAYS = 60
ARCHIVE_PURGE_DAYS = 180
DOMAIN_CACHE_PURGE_DAYS = 30


@dataclass
class Counts:
    scanned: int = 0
    sent: int = 0
    nothing_due: int = 0
    failed: int = 0
    skipped_budget: int = 0
    sessions_purged: int = 0
    tokens_purged: int = 0
    unconfirmed_accounts_deleted: int = 0
    checkin_in_digest: int = 0
    checkin_reminders: int = 0
    checkin_failed: int = 0
    checkin_skipped_budget: int = 0
    links_rechecked: int = 0
    roles_relabelled: int = 0
    roles_archived: int = 0
    roles_purged: int = 0
    domain_cache_purged: int = 0


def _checkin_due(today: date) -> ColumnElement[bool]:
    """Check-ins on, due by today, and not yet reminded this period."""
    return and_(
        User.checkin_interval_weeks.is_not(None),
        User.next_checkin_on <= today,
        or_(
            User.last_checkin_email_on.is_(None),
            User.last_checkin_email_on < User.next_checkin_on,
        ),
        User.email_verified_at.is_not(None),
        User.deleted_at.is_(None),
    )


def checkin_due_ids(sessions: sessionmaker[Session], today: date) -> set[uuid.UUID]:
    with sessions() as db:
        return set(db.scalars(select(User.id).where(_checkin_due(today)).limit(MAX_USERS_SCANNED)))


def _mark_reminded(sessions: sessionmaker[Session], user_id: uuid.UUID, today: date) -> bool:
    """Claim this period's reminder; False if someone (a re-run) already did."""
    with sessions() as db, db.begin():
        return (
            db.execute(
                update(User)
                .where(User.id == user_id, _checkin_due(today))
                .values(last_checkin_email_on=today)
                .returning(User.id)
            ).one_or_none()
            is not None
        )


def send_digests(
    sessions: sessionmaker[Session],
    mailer: Mailer,
    brand: Brand,
    today: date,
    checkin_due: set[uuid.UUID] | None = None,
) -> Counts:
    counts = Counts()
    checkin_due = checkin_due or set()
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

        with_checkin = user.id in checkin_due and _mark_reminded(sessions, user.id, today)
        message = digest_message(
            brand, user.email, user.handle, items, today, checkin_due=with_checkin
        )
        if mailer.send(message):
            counts.sent += 1
            counts.checkin_in_digest += int(with_checkin)
            failures = 0
            continue
        if with_checkin:
            _release_reminder(sessions, user.id)

        # Not sent: release the claim so tomorrow's run (or a re-run) can try again.
        with sessions() as db, db.begin():
            db.execute(update(User).where(User.id == user.id).values(last_digest_on=None))
        counts.failed += 1
        failures += 1
        if failures >= MAX_CONSECUTIVE_FAILURES:
            log.error("stopping: %d sends failed in a row", failures)
            break
    return counts


def _release_reminder(sessions: sessionmaker[Session], user_id: uuid.UUID) -> None:
    # Not sent: clear the claim so tomorrow's run tries again.
    with sessions() as db, db.begin():
        db.execute(update(User).where(User.id == user_id).values(last_checkin_email_on=None))


def send_checkin_reminders(
    sessions: sessionmaker[Session],
    mailer: Mailer,
    brand: Brand,
    today: date,
    counts: Counts,
    deadline: float,
) -> None:
    """Stand-alone reminders for users who got no digest today. They use only
    the budget left outside the digest reserve; past it, they wait a day."""
    with sessions() as db:
        due = db.execute(
            select(User.id, User.email, User.handle)
            .where(_checkin_due(today))
            .order_by(User.created_at, User.id)
            .limit(MAX_USERS_SCANNED)
        ).all()
    failures = 0
    for index, user in enumerate(due):
        if time.monotonic() > deadline:
            log.warning("stopping check-in reminders: runtime cap reached")
            break
        if mailer.remaining_today(CHECKIN_REMINDER_KIND) == 0:
            counts.checkin_skipped_budget = len(due) - index
            log.warning("check-in reminders: budget used up, %d wait a day", len(due) - index)
            break
        if not _mark_reminded(sessions, user.id, today):
            continue
        if mailer.send(checkin_reminder(brand, user.email, user.handle)):
            counts.checkin_reminders += 1
            failures = 0
            continue
        _release_reminder(sessions, user.id)
        counts.checkin_failed += 1
        failures += 1
        if failures >= MAX_CONSECUTIVE_FAILURES:
            log.error("stopping check-in reminders: %d sends failed in a row", failures)
            break


def purge_expired(sessions: sessionmaker[Session], counts: Counts) -> None:
    now = datetime.now(UTC)
    with sessions() as db, db.begin():
        counts.sessions_purged = db.execute(
            delete(UserSession).where(UserSession.expires_at <= now)
        ).rowcount  # type: ignore[attr-defined]
        counts.tokens_purged = db.execute(
            delete(AuthToken).where(AuthToken.expires_at <= now)
        ).rowcount  # type: ignore[attr-defined]


def purge_unconfirmed_empty_accounts(sessions: sessionmaker[Session], counts: Counts) -> None:
    """Delete accounts never confirmed and never used, 30 days after sign-up.

    The job's session has no RLS identity, so it can't see anyone's
    applications; "has none" is checked per user with an RLS-bound session.
    """
    cutoff = datetime.now(UTC) - timedelta(days=UNCONFIRMED_EMPTY_ACCOUNT_DAYS)
    with sessions() as db:
        stale = db.scalars(
            select(User.id).where(User.email_verified_at.is_(None), User.created_at < cutoff)
        ).all()
    for user_id in stale:
        with sessions() as db:
            set_session_user(db, user_id)
            has_apps = db.scalar(
                select(Application.id).where(Application.user_id == user_id).limit(1)
            )
        if has_apps is not None:
            continue
        with sessions() as db, db.begin():
            deleted = db.execute(
                delete(User).where(User.id == user_id, User.email_verified_at.is_(None))
            ).rowcount  # type: ignore[attr-defined]
        counts.unconfirmed_accounts_deleted += deleted


def _job_session(sessions: sessionmaker[Session]) -> Session:
    session = sessions()
    set_session_job(session)
    return session


def _with_link_result(checks: list[dict[str, str]], link_ok: bool | None) -> list[dict[str, str]]:
    if link_ok is True:
        result, detail = "pass", "The link opened."
    elif link_ok is False:
        result = "warn"
        detail = "The link didn't open. The ad may have closed, or it may not be real."
    else:
        result, detail = "unknown", "We couldn't check the link just now."
    return [
        {**c, "result": result, "detail": detail} if c.get("id") == "link_resolves" else c
        for c in checks
    ]


def recheck_board_links(
    sessions: sessionmaker[Session], fetcher: Fetcher, counts: Counts, deadline: float
) -> None:
    """Re-run "link opens" on the least recently checked live roles, and
    relabel them from their checks (verified <-> unverified; flagged and
    hidden roles are left alone)."""
    cutoff = datetime.now(UTC) - timedelta(hours=RECHECK_AFTER_HOURS)
    with _job_session(sessions) as db:
        due = db.execute(
            select(BoardRole.id, BoardRole.job_url)
            .where(
                BoardRole.status.in_(VISIBLE_STATUSES),
                BoardRole.archived_at.is_(None),
                BoardRole.checked_at < cutoff,
            )
            .order_by(BoardRole.checked_at, BoardRole.id)
            .limit(MAX_LINK_RECHECKS)
        ).all()
    if not due:
        return

    def check(row: Row[tuple[uuid.UUID, str]]) -> tuple[uuid.UUID, bool | None] | None:
        if time.monotonic() > deadline:
            return None  # out of time: left for tomorrow
        return row.id, fetcher.link_opens(row.job_url)

    with ThreadPoolExecutor(max_workers=RECHECK_WORKERS) as pool:
        results = [r for r in pool.map(check, due) if r is not None]
    if len(results) < len(due):
        log.warning("board re-checks stopped at the runtime cap: %d left", len(due) - len(results))
    for role_id, link_ok in results:
        with _job_session(sessions) as db, db.begin():
            role = db.get(BoardRole, role_id, with_for_update=True)
            if role is None or role.status not in VISIBLE_STATUSES:
                continue
            role.checks = _with_link_result(role.checks, link_ok)
            label = verdict(c.get("result", "") for c in role.checks)
            if label != role.status:
                role.status = label
                counts.roles_relabelled += 1
            role.checked_at = datetime.now(UTC)
            counts.links_rechecked += 1


def tidy_board(sessions: sessionmaker[Session], today: date, counts: Counts) -> None:
    now = datetime.now(UTC)
    with _job_session(sessions) as db, db.begin():
        counts.roles_archived = db.execute(
            update(BoardRole)
            .where(
                BoardRole.archived_at.is_(None),
                or_(
                    BoardRole.deadline < today,
                    and_(
                        BoardRole.deadline.is_(None),
                        BoardRole.created_at < now - timedelta(days=UNDATED_ROLE_DAYS),
                    ),
                ),
            )
            .values(status="archived", archived_at=now)
        ).rowcount  # type: ignore[attr-defined]
        counts.roles_purged = db.execute(
            delete(BoardRole).where(
                BoardRole.archived_at < now - timedelta(days=ARCHIVE_PURGE_DAYS)
            )
        ).rowcount  # type: ignore[attr-defined]
        counts.domain_cache_purged = db.execute(
            delete(DomainCheck).where(
                DomainCheck.checked_at < now - timedelta(days=DOMAIN_CACHE_PURGE_DAYS)
            )
        ).rowcount  # type: ignore[attr-defined]


def run(
    sessions: sessionmaker[Session],
    mailer: Mailer,
    settings: Settings,
    fetcher: Fetcher | None = None,
) -> Counts:
    started = time.monotonic()
    deadline = started + MAX_RUNTIME_SECONDS
    today = today_eat()
    brand = Brand.from_settings(settings)
    due = checkin_due_ids(sessions, today) if settings.dira_enabled else set()
    counts = send_digests(sessions, mailer, brand, today, due)
    if settings.dira_enabled:
        send_checkin_reminders(sessions, mailer, brand, today, counts, deadline)
    purge_expired(sessions, counts)
    purge_unconfirmed_empty_accounts(sessions, counts)
    tidy_board(sessions, today, counts)
    recheck_board_links(sessions, fetcher or Fetcher(), counts, started + MAX_RUNTIME_SECONDS)
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
