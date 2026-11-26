"""Give the kazi_app role its login password: python -m app.app_role

Run by scripts/start-web.sh as the database owner, after migrations and
before the owner credentials are dropped. Reads MIGRATIONS_DATABASE_URL and
KAZI_APP_DB_PASSWORD; does nothing if the password isn't set (local runs).
Setting it on every start means rotating the password is a variable change
and a redeploy. Never prints the password or either URL.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import sys

import psycopg
from psycopg import sql

log = logging.getLogger("kazi.app_role")
APP_ROLE = "kazi_app"
MIN_LENGTH = 32
SCRAM_ITERATIONS = 4096  # Postgres's default scram_iterations


def scram_verifier(password: str, *, salt: bytes | None = None) -> str:
    """The SCRAM-SHA-256 verifier Postgres would store for this password
    (RFC 5802/7677), so ALTER ROLE never carries the password itself."""
    salt = salt or secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, SCRAM_ITERATIONS)
    client_key = hmac.digest(salted, b"Client Key", "sha256")
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")
    b64 = base64.b64encode
    return (
        f"SCRAM-SHA-256${SCRAM_ITERATIONS}:{b64(salt).decode()}"
        f"${b64(stored_key).decode()}:{b64(server_key).decode()}"
    )


def set_app_password(owner_url: str, password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"KAZI_APP_DB_PASSWORD must be {MIN_LENGTH}+ characters")
    # Printable ASCII only: Postgres applies SASLprep to other characters,
    # which a verifier computed here wouldn't match.
    if not (password.isascii() and password.isprintable()):
        raise ValueError("KAZI_APP_DB_PASSWORD must be printable ASCII")
    # psycopg wants a libpq URL, without SQLAlchemy's +psycopg driver name.
    plain = owner_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(plain, autocommit=True) as conn:
        conn.execute(
            sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(APP_ROLE), sql.Literal(scram_verifier(password))
            )
        )


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(message)s")
    owner_url = os.environ.get("MIGRATIONS_DATABASE_URL")
    password = os.environ.get("KAZI_APP_DB_PASSWORD", "")
    if not owner_url or not password:
        log.info("app role: KAZI_APP_DB_PASSWORD or owner URL not set, skipped")
        return 0
    try:
        set_app_password(owner_url, password)
    except ValueError as exc:
        log.error("app role: %s", exc)
        return 1
    except psycopg.Error as exc:
        log.error("app role: database error (SQLSTATE %s)", exc.sqlstate)
        return 1
    log.info("app role: login password set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
