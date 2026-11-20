import logging

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.services import email_templates
from app.services.email import EmailMessage, EmailSendError, Mailer


def _msg(n: int = 0) -> EmailMessage:
    return EmailMessage(to=f"u{n}@example.com", subject="s", text="t", html="h", kind="test")


def _sent_today(owner: Engine) -> int:
    with owner.connect() as c:
        return int(
            c.execute(text("SELECT coalesce(sum(sent_count), 0) FROM email_budget")).scalar_one()
        )


def test_91st_email_is_refused_and_logged(
    app_sessions: sessionmaker[Session],
    owner_engine: Engine,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    delivered: list[EmailMessage] = []
    mailer = Mailer(app_sessions, settings, delivered.append)
    assert settings.email_daily_limit == 90

    results = [mailer.send(_msg(i)) for i in range(90)]
    assert all(results)
    with caplog.at_level(logging.WARNING):
        assert mailer.send(_msg(91)) is False
    assert len(delivered) == 90
    assert _sent_today(owner_engine) == 90
    assert "daily budget of 90 used up" in caplog.text
    assert "u91@example.com" not in caplog.text  # no addresses in logs
    assert mailer.remaining_today() == 0


def test_failed_send_does_not_use_budget(
    app_sessions: sessionmaker[Session], owner_engine: Engine, settings: Settings
) -> None:
    def broken(message: EmailMessage) -> None:
        raise EmailSendError("down")

    assert Mailer(app_sessions, settings, broken).send(_msg()) is False
    assert _sent_today(owner_engine) == 0


def test_zero_limit_sends_nothing(
    app_sessions: sessionmaker[Session], database_urls: tuple[str, str]
) -> None:
    delivered: list[EmailMessage] = []
    s = Settings(environment="test", database_url=database_urls[1], email_daily_limit=0)
    assert Mailer(app_sessions, s, delivered.append).send(_msg()) is False
    assert delivered == []


def test_templates_escape_html_and_keep_token_in_fragment() -> None:
    brand = email_templates.Brand("Kazi <b>", "tag", "https://kazi.example")
    msg = email_templates.verify_email(brand, "a@example.com", "<script>", "tok123")
    assert "<script>" not in msg.html
    assert "&lt;script&gt;" in msg.html
    assert "https://kazi.example/verify-email#token=tok123" in msg.text
    assert "?token" not in msg.text
