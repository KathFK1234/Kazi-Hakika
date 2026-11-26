import logging
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.services.email import EmailMessage, EmailSendError, resend_transport
from tests.conftest import make_settings

KEY = "re_test_secret_value_123"
MSG = EmailMessage(to="a@example.com", subject="Hi", text="text", html="<p>html</p>", kind="test")


def _settings() -> Settings:
    return make_settings(resend_api_key=KEY, email_from="Kazi <hello@kazi.example>")


def test_sends_the_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen.update(url=url, **kwargs)
        return httpx.Response(200, json={"id": "abc"})

    monkeypatch.setattr(httpx, "post", fake_post)
    resend_transport(_settings())(MSG)
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert seen["timeout"] == 5.0
    assert seen["json"] == {
        "from": "Kazi <hello@kazi.example>",
        "to": ["a@example.com"],
        "subject": "Hi",
        "text": "text",
        "html": "<p>html</p>",
    }


@pytest.mark.parametrize("status", [401, 422, 429, 500])
def test_provider_errors_raise_without_the_key(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(status, text=f"bad {KEY}"))
    with pytest.raises(EmailSendError) as caught:
        resend_transport(_settings())(MSG)
    assert str(status) in str(caught.value)
    assert KEY not in str(caught.value)


def test_network_errors_raise_without_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timed out talking to {url} with {KEY}")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(EmailSendError) as caught:
        resend_transport(_settings())(MSG)
    assert str(caught.value) == "ConnectTimeout"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_no_key_logs_instead_of_sending(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("sent"))
    with caplog.at_level(logging.INFO):
        resend_transport(make_settings())(MSG)
    assert "DEV EMAIL (kind=test)" in caplog.text

    prod = make_settings(
        environment="production",
        secret_key="x" * 40,
        base_url="https://kazi.example",
        trusted_proxy_hops=1,
    )
    caplog.clear()
    with caplog.at_level(logging.INFO):
        resend_transport(prod)(MSG)
    assert "RESEND_API_KEY is not set" in caplog.text
    assert "a@example.com" not in caplog.text


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_key_counts_as_no_key(blank: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("sent"))
    settings = make_settings(resend_api_key=blank)
    assert settings.resend_api_key is None
    resend_transport(settings)(MSG)
