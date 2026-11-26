"""kazi_app gets its login password from KAZI_APP_DB_PASSWORD at start-up."""

import logging

import psycopg
import pytest
from sqlalchemy import make_url

from app import app_role
from tests.conftest import APP_ROLE_PASSWORD

NEW_PASSWORD = "x" * 40


def _plain(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def test_sets_the_password_and_logs_nothing_secret(
    database_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_url, app_url = database_urls
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", owner_url)
    monkeypatch.setenv("KAZI_APP_DB_PASSWORD", NEW_PASSWORD)
    try:
        with caplog.at_level(logging.INFO):
            assert app_role.main() == 0
        new_url = make_url(_plain(app_url)).set(password=NEW_PASSWORD)
        with psycopg.connect(new_url.render_as_string(hide_password=False)) as c:
            row = c.execute("SELECT current_user").fetchone()
        assert row == ("kazi_app",)
        with psycopg.connect(_plain(owner_url)) as c:
            stored = c.execute(
                "SELECT rolpassword FROM pg_authid WHERE rolname = 'kazi_app'"
            ).fetchone()
        assert stored is not None and stored[0].startswith("SCRAM-SHA-256$4096:")
        assert NEW_PASSWORD not in caplog.text
        assert owner_url not in caplog.text
    finally:
        with psycopg.connect(_plain(owner_url), autocommit=True) as c:
            c.execute(f"ALTER ROLE kazi_app PASSWORD '{APP_ROLE_PASSWORD}'")


def test_skips_without_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", "postgresql://unused@127.0.0.1:1/x")
    monkeypatch.delenv("KAZI_APP_DB_PASSWORD", raising=False)
    assert app_role.main() == 0


def test_refuses_a_short_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", "postgresql://unused@127.0.0.1:1/x")
    monkeypatch.setenv("KAZI_APP_DB_PASSWORD", "short")
    assert app_role.main() == 1


def test_database_errors_are_logged_by_sqlstate_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    url = "postgresql://nobody:hunter2hunter2@127.0.0.1:1/x"  # pragma: allowlist secret
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", url)
    monkeypatch.setenv("KAZI_APP_DB_PASSWORD", NEW_PASSWORD)
    with caplog.at_level(logging.INFO):
        assert app_role.main() == 1
    assert "hunter2" not in caplog.text
    assert NEW_PASSWORD not in caplog.text


def test_refuses_non_ascii_passwords(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", "postgresql://unused@127.0.0.1:1/x")
    monkeypatch.setenv("KAZI_APP_DB_PASSWORD", "é" * 40)
    assert app_role.main() == 1


def test_verifier_shape_and_fresh_salt() -> None:
    one, two = app_role.scram_verifier(NEW_PASSWORD), app_role.scram_verifier(NEW_PASSWORD)
    assert one.startswith("SCRAM-SHA-256$4096:") and NEW_PASSWORD not in one
    assert one != two  # a new salt each time
    fixed = app_role.scram_verifier(NEW_PASSWORD, salt=b"0" * 16)
    assert fixed == app_role.scram_verifier(NEW_PASSWORD, salt=b"0" * 16)
