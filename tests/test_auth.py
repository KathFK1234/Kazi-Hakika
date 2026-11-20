import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.services.email import EmailMessage, Mailer
from app.services.ratelimit import LOGIN_FAILS_PER_EMAIL, LOGIN_FAILS_PER_EMAIL_IP, RateLimiter
from tests.conftest import make_settings
from tests.helpers import PASSWORD, login, signup, token_from


def test_signup_verify_login_me_logout(client: TestClient, outbox: list[EmailMessage]) -> None:
    r = client.post(
        "/api/auth/signup",
        json={"email": "Wanjiru@Example.com", "password": PASSWORD, "handle": "Wanjiru"},
    )
    assert r.status_code == 202
    assert outbox[-1].kind == "verify_email"
    assert outbox[-1].to == "wanjiru@example.com"

    # Unverified users can sign in; the flag says they're unverified.
    login(client, "wanjiru@example.com")
    me = client.get("/api/auth/me").json()
    assert me["handle"] == "wanjiru"
    assert me["email_verified"] is False

    r = client.post("/api/auth/verify-email", json={"token": token_from(outbox[-1])})
    assert r.status_code == 200
    assert client.get("/api/auth/me").json()["email_verified"] is True

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_session_cookie_flags(client: TestClient, outbox: list[EmailMessage]) -> None:
    email = signup(client, outbox, "amina")
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie


def test_only_token_hash_is_stored(
    client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    email = signup(client, outbox, "otieno")
    client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    raw = client.cookies.get("kh_session")
    assert raw
    with owner_engine.connect() as c:
        hashes = c.execute(text("SELECT token_hash FROM sessions")).scalars().all()
        pw = c.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert raw not in hashes
    assert pw.startswith("$argon2id$")


def test_signup_existing_email_does_not_reveal_it(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    signup(client, outbox, "kamau")
    # A new day for the per-address email limit.
    client.app.state.limiter.reset()  # type: ignore[attr-defined]
    r = client.post(
        "/api/auth/signup",
        json={"email": "kamau@example.com", "password": PASSWORD, "handle": "kamau2"},
    )
    assert r.status_code == 202
    assert r.json() == {"detail": "Check your email to finish signing up."}
    assert outbox[-1].kind == "already_registered"


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"email": "a@example.com", "password": "short", "handle": "abc"}, 422),
        ({"email": "a@example.com", "password": PASSWORD, "handle": "admin"}, 422),
        ({"email": "a@example.com", "password": PASSWORD, "handle": "no spaces"}, 422),
        ({"email": "not-an-email", "password": PASSWORD, "handle": "abcd"}, 422),
        ({"email": "a@example.com", "password": "x" * 129, "handle": "abcd"}, 422),
        ({"email": "a@example.com", "password": PASSWORD, "handle": "abcd", "is_admin": 1}, 422),
    ],
)
def test_signup_validation(client: TestClient, payload: dict[str, object], status: int) -> None:
    assert client.post("/api/auth/signup", json=payload).status_code == status


def test_taken_handle_does_not_reveal_whether_email_exists(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    signup(client, outbox, "known")
    signup(client, outbox, "takenhandle")
    registered = client.post(
        "/api/auth/signup",
        json={"email": "known@example.com", "password": PASSWORD, "handle": "takenhandle"},
    )
    unregistered = client.post(
        "/api/auth/signup",
        json={"email": "fresh@example.com", "password": PASSWORD, "handle": "takenhandle"},
    )
    assert registered.status_code == unregistered.status_code == 409
    assert registered.json() == unregistered.json()


def test_taken_handle_is_409(client: TestClient, outbox: list[EmailMessage]) -> None:
    signup(client, outbox, "njeri")
    r = client.post(
        "/api/auth/signup",
        json={"email": "other@example.com", "password": PASSWORD, "handle": "njeri"},
    )
    assert r.status_code == 409


def test_wrong_password_and_unknown_email_look_the_same(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    email = signup(client, outbox, "chebet")
    wrong = client.post("/api/auth/login", json={"email": email, "password": "wrong password!"})
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong password!"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_rate_limited_5_per_minute_per_ip(client: TestClient) -> None:
    for _ in range(5):
        r = client.post("/api/auth/login", json={"email": "x@example.com", "password": "nope"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "x@example.com", "password": "nope"})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1


def test_state_change_without_csrf_is_refused(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    login(client, signup(client, outbox, "mutua"))
    del client.headers["X-CSRF-Token"]
    assert client.post("/api/auth/logout").status_code == 403
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/auth/logout").status_code == 403


def test_cross_origin_and_form_posts_refused(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    r = client.post(
        "/api/auth/login",
        content=b"email=a&password=b",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 415


def test_verification_token_is_single_use(client: TestClient, outbox: list[EmailMessage]) -> None:
    client.post(
        "/api/auth/signup",
        json={"email": "once@example.com", "password": PASSWORD, "handle": "once"},
    )
    token = token_from(outbox[-1])
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 400


def test_password_reset_flow_signs_out_everywhere(
    client: TestClient, outbox: list[EmailMessage], settings: object
) -> None:
    email = signup(client, outbox, "akinyi")
    login(client, email)
    old_cookie = client.cookies.get("kh_session")

    r = client.post("/api/auth/password-reset/request", json={"email": email})
    assert r.status_code == 202
    token = token_from(outbox[-1])
    assert outbox[-1].kind == "password_reset"

    new_password = "a brand new passphrase"
    r = client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "password": new_password}
    )
    assert r.status_code == 200
    assert client.cookies.get("kh_session") != old_cookie

    # The old session is gone.
    client.cookies.set("kh_session", old_cookie or "")
    assert client.get("/api/auth/me").status_code == 401

    # The old password no longer works; the new one does.
    client.cookies.clear()
    bad = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"email": email, "password": new_password})
    assert good.status_code == 200
    # The token can't be reused.
    r = client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "password": "another one here"}
    )
    assert r.status_code == 400


def test_reset_request_for_unknown_email_looks_the_same(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    signup(client, outbox, "wekesa")
    sent_before = len(outbox)
    known = client.post("/api/auth/password-reset/request", json={"email": "wekesa@example.com"})
    unknown = client.post("/api/auth/password-reset/request", json={"email": "no@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(outbox) == sent_before + 1


def test_expired_session_is_rejected(
    client: TestClient, outbox: list[EmailMessage], owner_engine: Engine
) -> None:
    login(client, signup(client, outbox, "kiprop"))
    with owner_engine.begin() as c:
        c.execute(text("UPDATE sessions SET expires_at = now() - interval '1 second'"))
    assert client.get("/api/auth/me").status_code == 401


def test_me_is_not_cached(client: TestClient, outbox: list[EmailMessage]) -> None:
    login(client, signup(client, outbox, "halima"))
    assert client.get("/api/auth/me").headers["cache-control"] == "no-store"


def test_signup_emails_one_per_address_per_day(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    signup(client, outbox, "repeat")
    before = len(outbox)
    for handle in ("repeat2", "repeat3"):
        r = client.post(
            "/api/auth/signup",
            json={"email": "repeat@example.com", "password": PASSWORD, "handle": handle},
        )
        assert r.status_code == 202
    # The address already got today's sign-up email, so no more are sent.
    assert len(outbox) == before


def _login_from(client: TestClient, ip: str, email: str, password: str) -> int:
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    return int(r.status_code)


@pytest.fixture
def proxied(
    database_urls: tuple[str, str],
    app_sessions: sessionmaker[Session],
    outbox: list[EmailMessage],
) -> TestClient:
    """A client behind one trusted proxy, so X-Forwarded-For picks the IP."""
    settings = make_settings(database_url=database_urls[1], trusted_proxy_hops=1)
    app = create_app(settings)
    app.state.sessionmaker = app_sessions
    app.state.mailer = Mailer(app_sessions, settings, outbox.append)
    return TestClient(app, base_url="http://localhost:8000")


def test_failed_logins_elsewhere_do_not_lock_the_owner_out(
    proxied: TestClient, outbox: list[EmailMessage]
) -> None:
    email = signup(proxied, outbox, "lockout")
    for i in range(5):
        assert _login_from(proxied, "203.0.113.9", email, f"wrong guess {i}") == 401
    assert _login_from(proxied, "203.0.113.9", email, "wrong guess 6") == 429
    # The owner, from their own address, still gets in.
    assert _login_from(proxied, "198.51.100.7", email, PASSWORD) == 200


def test_failures_per_account_and_address_are_capped(
    proxied: TestClient, outbox: list[EmailMessage]
) -> None:
    email = signup(proxied, outbox, "guessed")
    # Spread over many addresses so the per-IP limit never triggers.
    for i in range(10):
        assert _login_from(proxied, f"203.0.113.{i}", email, "wrong guess") == 401
    limiter: RateLimiter = proxied.app.state.limiter  # type: ignore[attr-defined]
    assert not limiter.blocked(LOGIN_FAILS_PER_EMAIL, email)
    for _ in range(10):
        limiter.hit(LOGIN_FAILS_PER_EMAIL_IP, f"{email}|192.0.2.1")
    assert _login_from(proxied, "192.0.2.1", email, PASSWORD) == 429
    # Successful logins don't count as failures.
    for _ in range(3):
        assert _login_from(proxied, "198.51.100.7", email, PASSWORD) == 200
    assert not limiter.blocked(LOGIN_FAILS_PER_EMAIL_IP, f"{email}|198.51.100.7")
