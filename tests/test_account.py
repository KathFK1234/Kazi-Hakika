import json

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.services.email import EmailMessage
from tests.helpers import PASSWORD, signed_in


def _user_id(client: TestClient) -> str:
    return str(client.get("/api/auth/me").json()["id"])


def test_toggle_reminders(client: TestClient, outbox: list[EmailMessage]) -> None:
    me = signed_in(client, outbox, "faith")
    r = me.patch("/api/account/settings", json={"reminder_opt_in": False})
    assert r.json() == {"reminder_opt_in": False}
    assert me.get("/api/auth/me").json()["reminder_opt_in"] is False


def test_export_contains_everything_the_user_owns(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    me = signed_in(client, outbox, "brian")
    a = me.post(
        "/api/applications",
        json={"role_title": "Data Analyst", "company_name": "Safari", "notes": "café ✓"},
    ).json()
    me.patch(f"/api/applications/{a['id']}", json={"stage": "applied"})
    me.post("/api/applications", json={"role_title": "SRE", "company_name": "Twiga"})

    r = me.get("/api/account/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    data = json.loads(r.content)
    assert data["account"]["handle"] == "brian"
    assert "password_hash" not in json.dumps(data)
    assert len(data["sign_ins"]) == 1
    assert set(data["sign_ins"][0]) == {"created_at", "expires_at"}
    cookie = me.cookies.get("kh_session")
    assert cookie and cookie not in r.text
    assert "hash" not in r.text
    assert {x["role_title"] for x in data["applications"]} == {"Data Analyst", "SRE"}
    analyst = next(x for x in data["applications"] if x["role_title"] == "Data Analyst")
    assert analyst["notes"] == "café ✓"
    assert [(e["from"], e["to"]) for e in analyst["stage_history"]] == [
        (None, "saved"),
        ("saved", "applied"),
    ]


def test_export_excludes_other_users(client: TestClient, outbox: list[EmailMessage]) -> None:
    other = TestClient(client.app, base_url="http://localhost:8000")
    signed_in(other, outbox, "other")
    other.post("/api/applications", json={"role_title": "Theirs", "company_name": "X"})
    me = signed_in(client, outbox, "mine")
    assert me.get("/api/account/export").json()["applications"] == []


def test_delete_needs_matching_handle(client: TestClient, outbox: list[EmailMessage]) -> None:
    me = signed_in(client, outbox, "grace")
    r = me.request("DELETE", "/api/account", json={"confirm_handle": "someone"})
    assert r.status_code == 400
    assert me.get("/api/auth/me").status_code == 200


def test_delete_removes_every_row_referencing_the_user(
    client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    """Acceptance check: after deletion no row in any table references the user."""
    me = signed_in(client, outbox, "dennis")
    uid = _user_id(me)
    a = me.post("/api/applications", json={"role_title": "QA", "company_name": "Z"}).json()
    me.patch(f"/api/applications/{a['id']}", json={"stage": "interview"})
    me.post("/api/auth/resend-verification")  # may be a no-op; tokens table covered either way

    r = me.request("DELETE", "/api/account", json={"confirm_handle": "Dennis"})
    assert r.status_code == 204
    assert me.get("/api/auth/me").status_code == 401

    with owner_engine.connect() as c:
        uuid_columns = c.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type = 'uuid'"
            )
        ).all()
        assert uuid_columns
        for table, column in uuid_columns:
            hits = c.execute(
                text(f'SELECT count(*) FROM "{table}" WHERE "{column}" = :u'),  # noqa: S608
                {"u": uid},
            ).scalar_one()
            assert hits == 0, f"{table}.{column} still references the deleted user"

    # The email can sign up again from scratch.
    r = client.post(
        "/api/auth/signup",
        json={"email": "dennis@example.com", "password": PASSWORD, "handle": "dennis"},
    )
    assert r.status_code == 202
    assert outbox[-1].kind == "verify_email"


def test_delete_needs_csrf(client: TestClient, outbox: list[EmailMessage]) -> None:
    me = signed_in(client, outbox, "mercy")
    del me.headers["X-CSRF-Token"]
    assert me.request("DELETE", "/api/account", json={"confirm_handle": "mercy"}).status_code == 403


def _post_and_report(
    me: TestClient, owner_engine: Engine, url: str = "https://tausi.co.ke/sre"
) -> tuple[str, str]:
    """me posts a role and reports someone else's; returns (my post, reported role)."""
    from tests.factories import make_board_role, make_user
    from tests.test_board import fake_fetcher

    me.app.state.fetcher = fake_fetcher()  # type: ignore[attr-defined]
    r = me.post(
        "/api/board",
        json={"title": "SRE", "company_name": "Tausi", "job_url": url},
    )
    assert r.status_code == 201, r.text
    other = make_board_role(owner_engine, make_user(owner_engine))
    assert me.post(f"/api/board/{other}/report", json={"reason": "fee"}).status_code == 201
    return r.json()["role"]["id"], str(other)


def test_export_includes_board_posts_and_reports(
    client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = signed_in(client, outbox, "poster")
    post, reported = _post_and_report(me, owner_engine)
    data = me.get("/api/account/export").json()
    assert [p["id"] for p in data["board_posts"]] == [post]
    assert data["board_posts"][0]["checks"]
    assert [(r["board_role_id"], r["reason"]) for r in data["reports"]] == [(reported, "fee")]


def test_deleted_users_posts_stay_up_as_deleted_user_unless_removed(
    client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = signed_in(client, outbox, "keeper")
    post, reported = _post_and_report(me, owner_engine)
    assert (
        me.request("DELETE", "/api/account", json={"confirm_handle": "keeper"}).status_code == 204
    )
    with owner_engine.connect() as c:
        posted_by = c.execute(
            text("SELECT posted_by FROM board_roles WHERE id = :p"), {"p": post}
        ).scalar_one()
        reports = c.execute(
            text("SELECT report_count FROM board_roles WHERE id = :r"), {"r": reported}
        )
        assert reports.scalar_one() == 0  # the report went with the account
    assert posted_by is None

    you = signed_in(client, outbox, "leaver")
    post, _ = _post_and_report(you, owner_engine, "https://tausi.co.ke/other")
    r = you.request(
        "DELETE", "/api/account", json={"confirm_handle": "leaver", "remove_posts": True}
    )
    assert r.status_code == 204
    with owner_engine.connect() as c:
        left = c.execute(text("SELECT count(*) FROM board_roles WHERE id = :p"), {"p": post})
        assert left.scalar_one() == 0
