"""Rows created as the table owner, bypassing the API, for test setup."""

import uuid
from datetime import date

from sqlalchemy import Engine, text


def make_user(
    owner: Engine, handle: str | None = None, *, admin: bool = False, verified: bool = False
) -> uuid.UUID:
    handle = handle or f"u{uuid.uuid4().hex[:10]}"
    with owner.begin() as conn:
        return uuid.UUID(
            str(
                conn.execute(
                    text(
                        "INSERT INTO users (email, password_hash, handle, is_admin, "
                        "email_verified_at) VALUES (:e, 'x', :h, :a, "
                        "CASE WHEN :v THEN now() END) RETURNING id"
                    ),
                    {"e": f"{handle}@example.com", "h": handle, "a": admin, "v": verified},
                ).scalar_one()
            )
        )


def make_board_role(
    owner: Engine,
    posted_by: uuid.UUID | None,
    *,
    status: str = "verified",
    approved: bool = True,
    title: str = "Data Analyst",
    deadline: date | None = None,
    url: str | None = None,
) -> uuid.UUID:
    with owner.begin() as conn:
        return uuid.UUID(
            str(
                conn.execute(
                    text(
                        "INSERT INTO board_roles (posted_by, title, company_name, job_url, "
                        "company_domain, status, approved_at, deadline) VALUES (:p, :t, 'Acme', "
                        ":u, 'acme.co.ke', :s, CASE WHEN :a THEN now() END, :d) RETURNING id"
                    ),
                    {
                        "p": posted_by,
                        "t": title,
                        "u": url or f"https://acme.co.ke/jobs/{uuid.uuid4().hex[:8]}",
                        "s": status,
                        "a": approved,
                        "d": deadline,
                    },
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
