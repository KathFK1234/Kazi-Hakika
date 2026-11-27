"""Dira API: settings, check-ins, entries, patterns, export and the feature switch."""

import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.main import create_app
from app.services.digest import today_eat
from app.services.email import EmailMessage, Mailer
from tests.conftest import make_settings
from tests.helpers import signed_in

SENTINEL = "zq-reflection-sentinel-4411"


@pytest.fixture
def dira(
    settings: Settings, app_sessions: sessionmaker[Session], outbox: list[EmailMessage]
) -> TestClient:
    on = make_settings(database_url=settings.database_url, dira_enabled=True)
    app = create_app(on)
    app.state.sessionmaker = app_sessions
    app.state.mailer = Mailer(app_sessions, on, outbox.append)
    return TestClient(app, base_url="http://localhost:8000")


@pytest.fixture
def me(dira: TestClient, outbox: list[EmailMessage]) -> TestClient:
    return signed_in(dira, outbox, "njeri")


def _checkin(c: TestClient, **fields: object) -> dict[str, object]:
    r = c.post("/api/dira/checkins", json={"ideal_role": "Backend engineer in fintech", **fields})
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_off_unless_enabled(client: TestClient, outbox: list[EmailMessage]) -> None:
    me = signed_in(client, outbox, "off")
    assert me.get("/api/dira").status_code == 404
    assert me.get("/api/meta").json()["features"] == {"dira": False}


def test_turning_checkins_on_makes_one_due_today(me: TestClient) -> None:
    assert me.get("/api/meta").json()["features"] == {"dira": True}
    first = me.get("/api/dira").json()
    assert first["settings"] == {
        "checkin_interval_weeks": None,
        "next_checkin_on": None,
        "weekly_target": None,
    }
    assert first["due"] is False
    r = me.patch("/api/dira/settings", json={"checkin_interval_weeks": 6, "weekly_target": 3})
    assert r.json()["next_checkin_on"] == today_eat().isoformat()
    assert me.get("/api/dira").json()["due"] is True
    # Changing the interval keeps the date; turning off clears it.
    r = me.patch("/api/dira/settings", json={"checkin_interval_weeks": 4, "weekly_target": 3})
    assert r.json()["next_checkin_on"] == today_eat().isoformat()
    off = me.patch("/api/dira/settings", json={"checkin_interval_weeks": None})
    assert off.json() == {
        "checkin_interval_weeks": None,
        "next_checkin_on": None,
        "weekly_target": None,
    }
    assert me.patch("/api/dira/settings", json={"checkin_interval_weeks": 5}).status_code == 422
    assert (
        me.patch(
            "/api/dira/settings", json={"checkin_interval_weeks": 4, "weekly_target": 21}
        ).status_code
        == 422
    )


def test_checkin_sets_the_next_date_and_lists_roles_as_reminders(me: TestClient) -> None:
    me.patch("/api/dira/settings", json={"checkin_interval_weeks": 8})
    a = me.post("/api/applications", json={"role_title": "SRE", "company_name": "Tausi"}).json()
    prompt = me.get("/api/dira/checkin").json()
    assert prompt["last_checkin_on"] is None and prompt["checked_in_today"] is False
    assert [r["role_title"] for r in prompt["roles_since"]] == ["SRE"]
    assert set(prompt["roles_since"][0]) == {"id", "role_title"}  # titles only

    saved = _checkin(me, excited="Infra work", confidence_planning=4)
    assert saved["on_date"] == today_eat().isoformat()
    overview = me.get("/api/dira").json()
    assert overview["settings"]["next_checkin_on"] == (today_eat() + timedelta(weeks=8)).isoformat()
    assert overview["due"] is False
    assert overview["checkins"][0]["excited"] == "Infra work"
    assert me.get("/api/dira/checkin").json()["checked_in_today"] is True
    assert a["id"]


def test_one_checkin_a_day_and_validation(me: TestClient) -> None:
    _checkin(me, excited="  ", drained="")
    again = me.post("/api/dira/checkins", json={"ideal_role": "Data"})
    assert again.status_code == 409
    assert me.post("/api/dira/checkins", json={"ideal_role": "  "}).status_code == 422
    assert (
        me.post("/api/dira/checkins", json={"ideal_role": "x", "confidence_action": 6}).status_code
        == 422
    )
    assert me.post("/api/dira/checkins", json={"ideal_role": "x" * 301}).status_code == 422
    assert me.post("/api/dira/checkins", json={"ideal_role": "x", "mood": 3}).status_code == 422
    assert me.get("/api/dira").json()["checkins"][0]["excited"] is None


def test_at_most_60_checkins(me: TestClient, owner_engine: Engine) -> None:
    uid = me.get("/api/auth/me").json()["id"]
    with owner_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO checkins (user_id, on_date, ideal_role) "
                "SELECT :u, current_date - g, 'x' FROM generate_series(1, 60) g"
            ),
            {"u": uid},
        )
    r = me.post("/api/dira/checkins", json={"ideal_role": "y"})
    assert r.status_code == 409 and "60" in r.json()["detail"]


def test_delete_checkin_and_others_cannot(
    me: TestClient, dira: TestClient, outbox: list[EmailMessage]
) -> None:
    mine = _checkin(me)
    other = signed_in(TestClient(dira.app, base_url="http://localhost:8000"), outbox, "otieno")
    assert other.delete(f"/api/dira/checkins/{mine['id']}").status_code == 404
    assert other.get("/api/dira").json()["checkins"] == []
    assert me.delete(f"/api/dira/checkins/{mine['id']}").status_code == 204


def test_entries(me: TestClient, dira: TestClient, outbox: list[EmailMessage]) -> None:
    a = me.post("/api/applications", json={"role_title": "SRE", "company_name": "Tausi"}).json()
    win = me.post("/api/dira/entries", json={"kind": "win", "text": "Passed the take-home"}).json()
    learn = me.post(
        "/api/dira/entries",
        json={"kind": "learning", "text": "Ask about on-call", "application_id": a["id"]},
    ).json()
    goal = me.post("/api/dira/entries", json={"kind": "goal", "text": "Learn Terraform"}).json()
    assert win["happened_on"] == today_eat().isoformat()
    linked = me.get(f"/api/dira/entries?application_id={a['id']}").json()
    assert [e["id"] for e in linked] == [learn["id"]]
    assert [e["kind"] for e in me.get("/api/dira/entries?kind=goal").json()] == ["goal"]

    done = me.patch(f"/api/dira/entries/{goal['id']}", json={"done": True}).json()
    assert done["done_at"] is not None
    assert me.patch(f"/api/dira/entries/{win['id']}", json={"done": True}).status_code == 422
    assert me.patch(f"/api/dira/entries/{win['id']}", json={"text": "  "}).status_code == 422

    other = signed_in(TestClient(dira.app, base_url="http://localhost:8000"), outbox, "otieno")
    r = other.post(
        "/api/dira/entries", json={"kind": "win", "text": "x", "application_id": a["id"]}
    )
    assert r.status_code == 404
    assert other.patch(f"/api/dira/entries/{win['id']}", json={"text": "y"}).status_code == 404
    assert other.delete(f"/api/dira/entries/{win['id']}").status_code == 404
    assert me.delete(f"/api/dira/entries/{win['id']}").status_code == 204


def test_patterns_through_the_api(me: TestClient) -> None:
    for i in range(5):
        a = me.post(
            "/api/applications",
            json={
                "role_title": f"Role {i}",
                "company_name": "Tausi",
                "tags": ["Backend", "ai infra"],
            },
        ).json()
        assert a["tags"] == ["backend", "ai-infra"]
        me.patch(f"/api/applications/{a['id']}", json={"stage": "applied"})
        if i < 2:
            me.patch(f"/api/applications/{a['id']}", json={"stage": "screening"})
        me.patch(f"/api/applications/{a['id']}", json={"stage": "rejected"})
    _checkin(me, ideal_role="Backend engineer")
    p = me.get("/api/dira/patterns").json()
    assert p["applications"] == 5
    assert {g["name"]: (g["total"], g["reached_screening"]) for g in p["by_tag"]} == {
        "backend": (5, 2),
        "ai-infra": (5, 2),
    }
    assert p["stops"] == {"stage": "applied", "count": 3, "ended": 5}
    assert p["direction"] == {"recent": 5, "matching": 5, "tags": ["backend"]}


def test_tags_are_checked(me: TestClient) -> None:
    def add(tags: list[str]) -> int:
        body = {"role_title": "x", "company_name": "y", "tags": tags}
        return me.post("/api/applications", json=body).status_code

    assert add(["a", "b", "c", "d", "e", "f"]) == 422
    assert add(["no_underscores"]) == 422
    assert add(["x" * 31]) == 422
    assert add(["ok", "OK", " ok "]) == 201


def test_weekly_progress(me: TestClient) -> None:
    me.patch("/api/dira/settings", json={"checkin_interval_weeks": 4, "weekly_target": 2})
    a = me.post("/api/applications", json={"role_title": "x", "company_name": "y"}).json()
    me.patch(f"/api/applications/{a['id']}", json={"stage": "applied"})
    assert me.get("/api/dira").json()["week"] == {"target": 2, "applied_this_week": 1}


def test_export_and_no_reflection_in_logs(me: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    me.patch("/api/dira/settings", json={"checkin_interval_weeks": 6})
    with caplog.at_level(logging.DEBUG):
        _checkin(me, ideal_role=f"Lead {SENTINEL}", changed=SENTINEL, confidence_action=3)
        me.post("/api/dira/entries", json={"kind": "learning", "text": SENTINEL})
        me.post("/api/dira/checkins", json={"ideal_role": SENTINEL})  # refused: logged?
        data = me.get("/api/account/export").json()
    assert data["account"]["checkin_interval_weeks"] == 6
    assert data["checkins"][0]["changed"] == SENTINEL
    assert data["checkins"][0]["confidence"]["action"] == 3
    assert data["entries"][0]["text"] == SENTINEL
    assert SENTINEL not in caplog.text


def test_deletion_removes_checkins_and_entries(me: TestClient, owner_engine: Engine) -> None:
    _checkin(me)
    me.post("/api/dira/entries", json={"kind": "win", "text": "x"})
    assert me.request("DELETE", "/api/account", json={"confirm_handle": "njeri"}).status_code == 204
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM checkins")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM entries")).scalar_one() == 0
