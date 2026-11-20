"""Drive the real API the way the web app does."""

import re

from fastapi.testclient import TestClient

from app.services.email import EmailMessage

PASSWORD = "correct horse battery"


def token_from(message: EmailMessage) -> str:
    match = re.search(r"#token=([A-Za-z0-9_-]+)", message.text)
    assert match, "no token link in email"
    return match.group(1)


def signup(client: TestClient, outbox: list[EmailMessage], handle: str) -> str:
    """Sign up and verify; returns the email address."""
    email = f"{handle}@example.com"
    r = client.post(
        "/api/auth/signup", json={"email": email, "password": PASSWORD, "handle": handle}
    )
    assert r.status_code == 202, r.text
    r = client.post("/api/auth/verify-email", json={"token": token_from(outbox[-1])})
    assert r.status_code == 200, r.text
    return email


def login(client: TestClient, email: str) -> str:
    """Log in; returns the CSRF token and sets it as a default header."""
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    csrf = str(client.get("/api/auth/me").json()["csrf_token"])
    client.headers["X-CSRF-Token"] = csrf
    return csrf


def signed_in(client: TestClient, outbox: list[EmailMessage], handle: str) -> TestClient:
    login(client, signup(client, outbox, handle))
    return client
