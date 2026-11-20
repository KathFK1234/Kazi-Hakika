"""Rows created as the table owner, bypassing the API, for test setup."""

import uuid
from datetime import date

from sqlalchemy import Engine, text


def make_user(owner: Engine, handle: str | None = None) -> uuid.UUID:
    handle = handle or f"u{uuid.uuid4().hex[:10]}"
    with owner.begin() as conn:
        return uuid.UUID(
            str(
                conn.execute(
                    text(
                        "INSERT INTO users (email, password_hash, handle) "
                        "VALUES (:e, 'x', :h) RETURNING id"
                    ),
                    {"e": f"{handle}@example.com", "h": handle},
                ).scalar_one()
            )
        )


def make_application(
    owner: Engine, user_id: uuid.UUID, title: str = "Engineer", deadline: date | None = None
) -> uuid.UUID:
    with owner.begin() as conn:
        return uuid.UUID(
            str(
                conn.execute(
                    text(
                        "INSERT INTO applications (user_id, role_title, company_name, deadline) "
                        "VALUES (:u, :t, 'Acme', :d) RETURNING id"
                    ),
                    {"u": user_id, "t": title, "d": deadline},
                ).scalar_one()
            )
        )
