"""The board API: posting through the checks, review, browsing, saving, reports, admin."""

import logging
from datetime import timedelta

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import Settings
from app.main import create_app
from app.services.checking import OUTBOUND_PER_ACTOR
from app.services.digest import today_eat
from app.services.email import EmailMessage
from app.services.lookups import Fetcher
from tests.helpers import PASSWORD, login, signup

PUBLIC = "93.184.215.14"
SENTINEL = "zq-sentinel-ad-text-7731"
GOOD_TEXT = f"Tausi Analytics is hiring. Apply on our careers page. {SENTINEL}"
SCAM_TEXT = f"Pay a registration fee of KSh 1,000 to M-Pesa till 889900. {SENTINEL}"


def fake_fetcher() -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "rdap.org":
            return httpx.Response(
                200, json={"events": [{"eventAction": "registration", "eventDate": "2010-01-01"}]}
            )
        return httpx.Response(200)

    return Fetcher(lambda host, port: [PUBLIC], httpx.MockTransport(handler))


@pytest.fixture
def board_client(client: TestClient) -> TestClient:
    client.app.state.fetcher = fake_fetcher()  # type: ignore[attr-defined]
    return client


def _second_client(board_client: TestClient) -> TestClient:
    other = TestClient(board_client.app, base_url="http://localhost:8000")
    return other


def _join(c: TestClient, outbox: list[EmailMessage], handle: str) -> TestClient:
    login(c, signup(c, outbox, handle))
    return c


def _established(owner: Engine, handle: str, approved_posts: int = 2) -> None:
    """Older than 7 days with approved posts: skips the review queue."""
    with owner.begin() as c:
        uid = c.execute(
            text(
                "UPDATE users SET created_at = now() - interval '8 days' "
                "WHERE handle = :h RETURNING id"
            ),
            {"h": handle},
        ).scalar_one()
        for i in range(approved_posts):
            c.execute(
                text(
                    "INSERT INTO board_roles (posted_by, title, company_name, job_url, "
                    "company_domain, status, approved_at, created_at) VALUES (:u, 'Old', 'Old', "
                    ":url, 'old.co.ke', 'archived', now(), now() - interval '3 days')"
                ),
                {"u": uid, "url": f"https://old.co.ke/{handle}/{i}"},
            )


def _make_admin(owner: Engine, handle: str) -> None:
    with owner.begin() as c:
        c.execute(text("UPDATE users SET is_admin = true WHERE handle = :h"), {"h": handle})


def _post(c: TestClient, **fields: object) -> httpx2.Response:
    body = {
        "title": "Data Analyst",
        "company_name": "Tausi Analytics",
        "job_url": "https://www.tausi.co.ke/careers/data-analyst",
        "location": "Nairobi",
        "ad_text": GOOD_TEXT,
        **fields,
    }
    return c.post("/api/board", json=body)


def _public(c: TestClient, query: str = "") -> list[dict[str, object]]:
    r = c.get(f"/api/board{query}")
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


def test_board_is_public_and_starts_empty(board_client: TestClient) -> None:
    assert _public(board_client) == []


def test_posting_needs_a_confirmed_account(
    board_client: TestClient, outbox: list[EmailMessage]
) -> None:
    assert _post(board_client).status_code == 401
    board_client.post(
        "/api/auth/signup",
        json={"email": "new@example.com", "password": PASSWORD, "handle": "newbie"},
    )
    login(board_client, "new@example.com")
    r = _post(board_client)
    assert r.status_code == 403
    assert "Confirm your email" in r.json()["detail"]


def test_link_is_required_and_must_be_web(
    board_client: TestClient, outbox: list[EmailMessage]
) -> None:
    me = _join(board_client, outbox, "poster")
    assert _post(me, job_url="").status_code == 422
    assert _post(me, job_url="javascript:alert(1)").status_code == 422
    yesterday = (today_eat() - timedelta(days=1)).isoformat()
    assert _post(me, deadline=yesterday).status_code == 422


def test_new_accounts_wait_for_review_then_an_admin_approves(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = _join(board_client, outbox, "poster")
    r = _post(me)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"]["status"] == "verified"
    assert body["role"]["pending_review"] is True
    assert "moderator" in body["message"]
    role_id = body["role"]["id"]

    anon = _second_client(board_client)
    assert _public(anon) == []
    assert anon.get(f"/api/board/{role_id}").status_code == 404
    mine = me.get("/api/board/mine").json()["items"]
    assert [m["id"] for m in mine] == [role_id]

    admin = _join(_second_client(board_client), outbox, "kazimod")
    _make_admin(owner_engine, "kazimod")
    pending = admin.get("/api/admin/queue").json()["pending"]
    assert [p["id"] for p in pending] == [role_id]
    assert admin.post(f"/api/admin/board/{role_id}/approve").status_code == 200

    listed = _public(anon)
    assert [x["id"] for x in listed] == [role_id]
    assert listed[0]["posted_by"] == "poster"
    assert listed[0]["pending_review"] is False


def test_established_posters_go_straight_on_the_board(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    r = _post(me)
    assert r.status_code == 201
    assert r.json()["role"]["pending_review"] is False
    assert len(_public(_second_client(board_client))) == 1


def test_one_approved_post_is_not_enough(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = _join(board_client, outbox, "almost")
    _established(owner_engine, "almost", approved_posts=1)
    assert _post(me).json()["role"]["pending_review"] is True


def test_flagged_posts_never_reach_the_board_but_the_poster_sees_why(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    r = _post(me, ad_text=SCAM_TEXT)
    assert r.status_code == 201
    role = r.json()["role"]
    assert role["status"] == "flagged"
    assert "Not posted" in r.json()["message"]
    fee = next(c for c in role["checks"] if c["id"] == "fee_language")
    assert fee["result"] == "flag"
    assert _public(_second_client(board_client)) == []
    assert me.get(f"/api/board/{role['id']}").json()["status"] == "flagged"


def test_ad_text_is_never_stored_or_logged(
    board_client: TestClient,
    outbox: list[EmailMessage],
    owner_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    me = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    with caplog.at_level(logging.DEBUG):
        assert _post(me, ad_text=SCAM_TEXT, agency_name="Sentinel Agency").status_code == 201
    with owner_engine.connect() as c:
        dump = c.execute(text("SELECT string_agg(b::text, ' ') FROM board_roles b")).scalar_one()
    assert SENTINEL not in dump and "Sentinel Agency" not in dump
    assert SENTINEL not in caplog.text


def test_five_posts_a_day(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = _join(board_client, outbox, "busy")
    for i in range(5):
        assert _post(me, job_url=f"https://www.tausi.co.ke/jobs/{i}").status_code == 201
    r = _post(me, job_url="https://www.tausi.co.ke/jobs/6")
    assert r.status_code == 429
    assert "5 roles a day" in r.json()["detail"]


def test_the_same_link_is_posted_once(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = _join(board_client, outbox, "first")
    assert _post(me).status_code == 201
    other = _join(_second_client(board_client), outbox, "second")
    # The first copy is still pending (invisible to "second"): the unique index catches it.
    r = _post(other, job_url="https://www.tausi.co.ke/careers/data-analyst#apply")
    assert r.status_code == 409
    assert _post(me).status_code == 409


def test_filters(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    soon = (today_eat() + timedelta(days=3)).isoformat()
    later = (today_eat() + timedelta(days=40)).isoformat()
    _post(me, title="Remote SRE", job_url="https://www.tausi.co.ke/1", remote=True, deadline=soon)
    _post(me, title="Mombasa Clerk", job_url="https://www.tausi.co.ke/2", location="Mombasa")
    _post(me, title="Nairobi Analyst", job_url="https://www.tausi.co.ke/3", deadline=later)
    _post(me, title="Unverified", job_url="https://www.tausi.co.ke/4", ad_text="")
    with owner_engine.begin() as c:  # a past deadline the daily job hasn't archived yet
        c.execute(text("UPDATE board_roles SET deadline = current_date - 2 WHERE title = 'Old'"))
    anon = _second_client(board_client)

    def titles(q: str) -> set[object]:
        return {x["title"] for x in _public(anon, q)}

    assert titles("") == {"Remote SRE", "Mombasa Clerk", "Nairobi Analyst", "Unverified"}
    assert titles("?remote=true") == {"Remote SRE"}
    assert titles("?location=mombasa") == {"Mombasa Clerk"}
    assert titles("?q=analyst") == {"Nairobi Analyst"}
    assert titles("?q=%25") == set()  # LIKE wildcards are escaped
    assert titles("?due_within_days=7") == {"Remote SRE"}
    assert "Unverified" not in titles("?verified_only=true")


def test_save_to_tracker(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    poster = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    role_id = _post(poster).json()["role"]["id"]
    seeker = _join(_second_client(board_client), outbox, "seeker")
    r = seeker.post(f"/api/board/{role_id}/save")
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["source"] == "board" and app["board_role_id"] == role_id
    assert app["role_title"] == "Data Analyst" and app["stage"] == "saved"
    again = seeker.post(f"/api/board/{role_id}/save")
    assert again.status_code == 200 and again.json()["id"] == app["id"]
    assert seeker.get("/api/applications").json()["total"] == 1


def test_cannot_save_a_role_that_is_not_on_the_board(
    board_client: TestClient, outbox: list[EmailMessage]
) -> None:
    poster = _join(board_client, outbox, "poster")
    pending = _post(poster).json()["role"]["id"]
    seeker = _join(_second_client(board_client), outbox, "seeker")
    assert seeker.post(f"/api/board/{pending}/save").status_code == 404


def test_reports_hide_a_role_and_an_admin_restores_it(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    poster = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    role_id = _post(poster).json()["role"]["id"]
    assert poster.post(f"/api/board/{role_id}/report", json={"reason": "fee"}).status_code == 400

    for i in range(3):
        reporter = _join(_second_client(board_client), outbox, f"reporter{i}")
        r = reporter.post(f"/api/board/{role_id}/report", json={"reason": "fake", "note": "odd"})
        assert r.status_code == 201, r.text
        if i == 0:
            again = reporter.post(f"/api/board/{role_id}/report", json={"reason": "fee"})
            assert again.status_code == 409
    assert _public(_second_client(board_client)) == []

    admin = _join(_second_client(board_client), outbox, "kazimod")
    _make_admin(owner_engine, "kazimod")
    hidden = admin.get("/api/admin/queue").json()["hidden"]
    assert [h["id"] for h in hidden] == [role_id]
    assert hidden[0]["report_count"] == 3
    assert [r["reason"] for r in hidden[0]["reports"]] == ["fake"] * 3
    restored = admin.post(f"/api/admin/board/{role_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["status"] == "verified" and restored.json()["report_count"] == 0
    assert len(_public(_second_client(board_client))) == 1


def test_bad_report_reason(board_client: TestClient, outbox: list[EmailMessage]) -> None:
    me = _join(board_client, outbox, "someone")
    r = me.post("/api/board/00000000-0000-0000-0000-000000000000/report", json={"reason": "boring"})
    assert r.status_code == 422


def test_admin_hides_and_flagged_stays_flagged(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    poster = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    ok = _post(poster).json()["role"]["id"]
    scam = _post(poster, job_url="https://www.tausi.co.ke/x", ad_text=SCAM_TEXT).json()["role"]
    admin = _join(_second_client(board_client), outbox, "kazimod")
    _make_admin(owner_engine, "kazimod")
    assert admin.post(f"/api/admin/board/{ok}/hide").json()["status"] == "hidden"
    assert _public(_second_client(board_client)) == []
    assert [f["id"] for f in admin.get("/api/admin/queue").json()["flagged"]] == [scam["id"]]
    assert admin.post(f"/api/admin/board/{scam['id']}/approve").status_code == 409
    assert admin.post(f"/api/admin/board/{scam['id']}/restore").status_code == 409


def test_admin_pages_are_hidden_from_everyone_else(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    assert board_client.get("/api/admin/queue").status_code == 401
    me = _join(board_client, outbox, "curious")
    assert me.get("/api/admin/queue").status_code == 404
    assert me.post("/api/admin/nea", json={"csv": "Name\nX"}).status_code == 404
    assert me.get("/api/auth/me").json()["is_admin"] is False


def test_poster_deletes_only_their_own(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    poster = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    role_id = _post(poster).json()["role"]["id"]
    other = _join(_second_client(board_client), outbox, "other")
    assert other.delete(f"/api/board/{role_id}").status_code == 404
    assert poster.delete(f"/api/board/{role_id}").status_code == 204
    assert _public(other) == []


def test_nea_upload_feeds_the_overseas_check(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    admin = _join(board_client, outbox, "kazimod")
    _make_admin(owner_engine, "kazimod")
    assert admin.get("/api/auth/me").json()["is_admin"] is True
    csv_text = "﻿Agency Name,Licence Status\nLicensed Partners Ltd,Active\nGone Ltd,Revoked\n"
    r = admin.post("/api/admin/nea", json={"csv": csv_text})
    assert r.status_code == 200 and r.json()["total"] == 2
    more = admin.post("/api/admin/nea", json={"csv": "Name\nThird Agency\n", "replace": False})
    assert more.json()["total"] == 3
    assert admin.post("/api/admin/nea", json={"csv": "Company\nX"}).status_code == 422

    _established(owner_engine, "kazimod")
    abroad = "Nurses wanted in Qatar. Visa sponsored. Email jobs@licensedpartners.co.ke"
    ok = _post(
        admin,
        job_url="https://licensedpartners.co.ke/1",
        company_name="Licensed Partners",
        ad_text=abroad,
    ).json()["role"]
    revoked = _post(
        admin, job_url="https://gone.co.ke/1", company_name="Gone Ltd", ad_text=abroad
    ).json()["role"]
    assert ok["status"] == "verified"
    assert revoked["status"] == "flagged"


def test_outbound_lookups_pause_past_the_cap(
    board_client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    me = _join(board_client, outbox, "regular")
    _established(owner_engine, "regular")
    limiter = board_client.app.state.limiter  # type: ignore[attr-defined]
    actor = f"user:{me.get('/api/auth/me').json()['id']}"
    for _ in range(20):
        limiter.hit(OUTBOUND_PER_ACTOR, actor)
    r = _post(me)
    assert r.json()["lookups_paused"] is True
    resolves = next(c for c in r.json()["role"]["checks"] if c["id"] == "link_resolves")
    assert resolves["result"] == "unknown"


def test_board_reads_are_rate_limited(settings: Settings, app_sessions: object) -> None:
    app = create_app(settings)
    app.state.sessionmaker = app_sessions
    c = TestClient(app, base_url="http://localhost:8000")
    codes = [c.get("/api/board").status_code for _ in range(121)]
    assert codes[:120] == [200] * 120 and codes[120] == 429
