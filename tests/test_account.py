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
