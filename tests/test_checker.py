"""The public checker: no account, rate-limited, and it never stores the ad."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.models import Base
from tests.test_board import SCAM_TEXT, SENTINEL, fake_fetcher


@pytest.fixture
def anon(client: TestClient) -> TestClient:
    client.app.state.fetcher = fake_fetcher()  # type: ignore[attr-defined]
    return client


def _row_counts(owner: Engine) -> dict[str, int]:
    with owner.connect() as c:
        return {
            t: int(c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one())  # noqa: S608
            for t in Base.metadata.tables
        }


def test_scam_ad_is_flagged_without_an_account(anon: TestClient) -> None:
    r = anon.post("/api/check", json={"text": SCAM_TEXT, "company": "Tausi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "flagged"
    assert "scam" in body["summary"]
    assert {c["id"] for c in body["checks"]} >= {"fee_language", "link_present"}


def test_real_looking_link_passes(anon: TestClient) -> None:
    r = anon.post(
        "/api/check",
        json={
            "url": "https://www.tausi.co.ke/careers/1",
            "text": "Apply on our careers page.",
            "company": "Tausi Analytics",
        },
    )
    assert r.json()["verdict"] == "verified", r.json()


def test_needs_a_link_or_text(anon: TestClient) -> None:
    r = anon.post("/api/check", json={"url": " ", "text": "  "})
    assert r.status_code == 422
    assert "link" in r.json()["detail"]
    assert anon.post("/api/check", json={"url": "ftp://x.com"}).status_code == 422
    assert anon.post("/api/check", json={"text": "x", "extra": 1}).status_code == 422


def test_nothing_is_stored_but_the_domain_cache(
    anon: TestClient, owner_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    before = _row_counts(owner_engine)
    with caplog.at_level(logging.DEBUG):
        r = anon.post(
            "/api/check",
            json={"url": "https://www.tausi.co.ke/j", "text": SCAM_TEXT, "company": "Tausi"},
        )
    assert r.status_code == 200
    after = _row_counts(owner_engine)
    changed = {t for t in after if after[t] != before[t]}
    assert changed == {"domain_checks"}
    with owner_engine.connect() as c:
        row = c.execute(text("SELECT d::text FROM domain_checks d")).scalar_one()
    assert SENTINEL not in row and "/j" not in row
    assert SENTINEL not in caplog.text and "tausi" not in caplog.text


def test_ten_checks_a_minute_per_ip(anon: TestClient) -> None:
    codes = [anon.post("/api/check", json={"text": "hello"}).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_cross_site_posts_are_refused(anon: TestClient) -> None:
    r = anon.post("/api/check", json={"text": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
