"""Apply ADMIN_EMAILS to users.is_admin: python -m app.admins

Run by scripts/start-web.sh as the database owner, after migrations. The app
role can't write users.is_admin at all (column privileges, migration 0005),
so admin rights come only from this variable, which lives in the Railway
dashboard, never in the repo. Accounts named here become admins once their
email is confirmed (the policies check that too); everyone else loses admin.
Logs counts only, never addresses.
"""

import logging
import os
import sys

import psycopg

log = logging.getLogger("kazi.admins")
MAX_ADMINS = 5


def parse(raw: str) -> list[str]:
    emails = sorted({e.strip().lower() for e in raw.split(",") if e.strip()})
    if len(emails) > MAX_ADMINS:
        raise ValueError(f"ADMIN_EMAILS lists more than {MAX_ADMINS} addresses")
    for email in emails:
        if "@" not in email or any(c.isspace() for c in email):
            raise ValueError("ADMIN_EMAILS must be a comma-separated list of emails")
    return emails


def apply(owner_url: str, emails: list[str]) -> tuple[int, int]:
    """(granted, revoked) row counts."""
    plain = owner_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(plain) as conn, conn.transaction():
        granted = conn.execute(
            "UPDATE users SET is_admin = true, updated_at = now() "
            "WHERE email = ANY(%s) AND NOT is_admin",
            (emails,),
        ).rowcount
        revoked = conn.execute(
            "UPDATE users SET is_admin = false, updated_at = now() "
            "WHERE is_admin AND NOT (email = ANY(%s))",
            (emails,),
        ).rowcount
    return granted, revoked


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(message)s")
    owner_url = os.environ.get("MIGRATIONS_DATABASE_URL")
    if not owner_url:
        log.info("admins: owner URL not set, skipped")
        return 0
    try:
        emails = parse(os.environ.get("ADMIN_EMAILS", ""))
        granted, revoked = apply(owner_url, emails)
    except ValueError as exc:
        log.error("admins: %s", exc)
        return 1
    except psycopg.Error as exc:
        log.error("admins: database error (SQLSTATE %s)", exc.sqlstate)
        return 1
    log.info("admins: %d listed, %d granted, %d revoked", len(emails), granted, revoked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
