from datetime import timedelta
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.models import STAGES
from app.routers.applications import Stage, _today
from app.services.email import EmailMessage
from tests.helpers import signed_in


@pytest.fixture
def me(client: TestClient, outbox: list[EmailMessage]) -> TestClient:
    return signed_in(client, outbox, "wanjiku")


def _add(client: TestClient, **fields: object) -> dict[str, object]:
    body = {"role_title": "Backend Engineer", "company_name": "Acme", **fields}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_stage_literal_matches_db_stages() -> None:
    assert set(get_args(Stage)) == set(STAGES)


def test_requires_sign_in(client: TestClient) -> None:
    assert client.get("/api/applications").status_code == 401


def test_create_records_first_stage_event(me: TestClient) -> None:
    app = _add(me, job_url="https://jobs.example.com/1", notes="Referral from Ken")
    assert app["stage"] == "saved"
    assert app["source"] == "own"
    events = app["events"]
    assert isinstance(events, list) and len(events) == 1
    assert events[0]["from_stage"] is None and events[0]["to_stage"] == "saved"


def test_stage_change_writes_event_and_sets_applied_on(me: TestClient) -> None:
    app = _add(me)
    r = me.patch(f"/api/applications/{app['id']}", json={"stage": "applied"})
    body = r.json()
    assert [(e["from_stage"], e["to_stage"]) for e in body["events"]] == [
        (None, "saved"),
        ("saved", "applied"),
    ]
    assert body["applied_on"] == _today().isoformat()
    # Editing other fields doesn't add events.
    body = me.patch(f"/api/applications/{app['id']}", json={"notes": "called"}).json()
    assert len(body["events"]) == 2


def test_patch_clears_optional_fields_but_not_required(me: TestClient) -> None:
    app = _add(me, deadline="2030-01-01", salary_note="KSh 200k")
    r = me.patch(f"/api/applications/{app['id']}", json={"deadline": None, "salary_note": None})
    assert r.json()["deadline"] is None and r.json()["salary_note"] is None
    r = me.patch(f"/api/applications/{app['id']}", json={"role_title": None})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"role_title": ""},
        {"role_title": "   "},
        {"company_name": "x" * 201},
        {"job_url": "javascript:alert(1)"},
        {"job_url": "ftp://example.com"},
        {"stage": "hired"},
        {"notes": "x" * 5001},
        {"deadline": "1999-01-01"},
        {"source": "board"},
        {"user_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_validation(me: TestClient, fields: dict[str, object]) -> None:
    body = {"role_title": "Engineer", "company_name": "Acme", **fields}
    assert me.post("/api/applications", json=body).status_code == 422


def test_notes_up_to_5000_chars_accepted(me: TestClient) -> None:
    assert len(str(_add(me, notes="n" * 5000)["notes"])) == 5000


def test_filter_by_stage_and_deadline_window(me: TestClient) -> None:
    today = _today()
    _add(me, role_title="soon", deadline=(today + timedelta(days=2)).isoformat())
    _add(me, role_title="later", deadline=(today + timedelta(days=30)).isoformat())
    _add(me, role_title="overdue", deadline=(today - timedelta(days=1)).isoformat())
    _add(me, role_title="none")
    interview = _add(me, role_title="interviewing", stage="interview")

    titles = [
        a["role_title"] for a in me.get("/api/applications?due_within_days=7").json()["items"]
    ]
    assert titles == ["soon"]
    titles = [
        a["role_title"]
        for a in me.get("/api/applications?due_within_days=7&include_overdue=true").json()["items"]
    ]
    assert titles == ["overdue", "soon"]
    r = me.get("/api/applications?stage=interview&stage=offer").json()
    assert [a["id"] for a in r["items"]] == [interview["id"]]
    # Deadline sort puts undated last.
    all_titles = [a["role_title"] for a in me.get("/api/applications").json()["items"]]
    assert all_titles[:3] == ["overdue", "soon", "later"]


def test_paginated_at_50(me: TestClient, owner_engine: Engine) -> None:
    user_id = me.get("/api/auth/me").json()["id"]
    with owner_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO applications (user_id, role_title, company_name) "
                "SELECT :u, 'r' || g, 'c' FROM generate_series(1, 120) g"
            ),
            {"u": user_id},
        )
    page = me.get("/api/applications").json()
    assert len(page["items"]) == 50 and page["total"] == 120 and page["next_offset"] == 50
    last = me.get("/api/applications?offset=100").json()
    assert len(last["items"]) == 20 and last["next_offset"] is None
    assert me.get("/api/applications?limit=51").status_code == 422
    ids = {
        a["id"]
        for off in (0, 50, 100)
        for a in me.get(f"/api/applications?offset={off}").json()["items"]
    }
    assert len(ids) == 120  # stable order, no duplicates across pages


def test_delete(me: TestClient) -> None:
    app = _add(me)
    assert me.delete(f"/api/applications/{app['id']}").status_code == 204
    assert me.get(f"/api/applications/{app['id']}").status_code == 404


def test_user_a_gets_404_for_user_bs_application(
    client: TestClient, outbox: list[EmailMessage], settings: object
) -> None:
    """Acceptance check: cross-user access through the API is a 404, not a 403."""
    signed_in(client, outbox, "usera")
    b_client = TestClient(client.app, base_url="http://localhost:8000")
    signed_in(b_client, outbox, "userb")
    b_app = _add(b_client, role_title="B's secret role")

    path = f"/api/applications/{b_app['id']}"
    assert client.get(path).status_code == 404
    assert client.patch(path, json={"notes": "hijack"}).status_code == 404
    assert client.delete(path).status_code == 404
    assert client.get("/api/applications").json()["total"] == 0
    assert b_client.get(path).json()["notes"] == ""


def test_csrf_needed_for_writes(me: TestClient) -> None:
    del me.headers["X-CSRF-Token"]
    r = me.post("/api/applications", json={"role_title": "a", "company_name": "b"})
    assert r.status_code == 403
    assert me.get("/api/applications").status_code == 200
