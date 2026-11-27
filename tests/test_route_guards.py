"""Every API route is guarded: writes need the CSRF token, private reads need a session.

Walks the app's routes, so a new endpoint that forgets its guard fails here.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.email import EmailMessage
from tests.conftest import make_settings
from tests.helpers import signed_in

# Writes that work before sign-in, by design (they carry no session).
ANONYMOUS_WRITES = {
    "/api/auth/signup",
    "/api/auth/login",
    "/api/auth/verify-email",
    "/api/auth/password-reset/request",
    "/api/auth/password-reset/confirm",
    "/api/check",
}
PUBLIC_READS = {"/health", "/api/meta", "/api/board", "/api/board/{role_id}", "/api/auth/me"}
UNSAFE = {"POST", "PATCH", "PUT", "DELETE"}
ZERO_ID = "00000000-0000-0000-0000-000000000000"


def _routes(settings: Settings) -> list[tuple[str, str]]:
    """Every API operation, from the OpenAPI schema (routers are mounted lazily)."""
    app = create_app(make_settings(database_url=settings.database_url, dira_enabled=True))
    paths: dict[str, dict[str, object]] = app.openapi()["paths"]
    return sorted(
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if method.upper() in {"GET", *UNSAFE}
    )


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", ZERO_ID, path)


@pytest.fixture
def dira_client(settings: Settings, client: TestClient) -> TestClient:
    on = make_settings(database_url=settings.database_url, dira_enabled=True)
    app = create_app(on)
    app.state.sessionmaker = client.app.state.sessionmaker  # type: ignore[attr-defined]
    app.state.mailer = client.app.state.mailer  # type: ignore[attr-defined]
    return TestClient(app, base_url="http://localhost:8000")


def test_routes_are_found(settings: Settings) -> None:
    paths = {p for _, p in _routes(settings)}
    assert {"/api/board", "/api/admin/queue", "/api/dira/checkins"} <= paths
    assert len(paths) > 30


def test_every_write_needs_the_csrf_token(
    settings: Settings, dira_client: TestClient, outbox: list[EmailMessage]
) -> None:
    me = signed_in(dira_client, outbox, "guarded")
    del me.headers["X-CSRF-Token"]
    for method, path in _routes(settings):
        if method not in UNSAFE or path in ANONYMOUS_WRITES:
            continue
        r = me.request(method, _concrete(path), json={})
        assert r.status_code == 403, f"{method} {path} answered {r.status_code} without CSRF"


def test_private_routes_need_a_session(settings: Settings, dira_client: TestClient) -> None:
    for method, path in _routes(settings):
        if path in PUBLIC_READS or path in ANONYMOUS_WRITES:
            continue
        r = dira_client.request(method, _concrete(path), json={})
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} signed out"
