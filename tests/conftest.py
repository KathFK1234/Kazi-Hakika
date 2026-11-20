"""Test fixtures. Database tests need TEST_ADMIN_DATABASE_URL (a superuser URL);
they create a throwaway database, migrate it as the owner, and connect the app
as the non-superuser kazi_app role so RLS is really exercised."""

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

# Tests never read a developer's .env: settings come only from code and CI env.
os.environ["ENVIRONMENT"] = "test"

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.services.email import EmailMessage, Mailer

APP_ROLE_PASSWORD = "kazi_app_test_only"
TABLES = ("stage_events", "applications", "sessions", "auth_tokens", "email_budget", "users")


def _admin_url() -> str | None:
    url = os.environ.get("TEST_ADMIN_DATABASE_URL")
    return Settings._use_psycopg_driver(url) if url else None


@pytest.fixture(scope="session")
def database_urls() -> Iterator[tuple[str, str]]:
    """(owner_url, app_url) for a freshly migrated test database."""
    admin = _admin_url()
    if not admin:
        pytest.skip("TEST_ADMIN_DATABASE_URL not set")
    name = f"kazi_test_{uuid.uuid4().hex[:8]}"
    plain_admin = make_url(admin).set(drivername="postgresql")
    with psycopg.connect(plain_admin.render_as_string(hide_password=False), autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    owner_url = make_url(admin).set(database=name).render_as_string(hide_password=False)

    cfg = Config("alembic.ini")
    cfg.attributes["url"] = owner_url
    command.upgrade(cfg, "head")

    owner = create_engine(owner_url)
    with owner.begin() as conn:
        conn.execute(text(f"ALTER ROLE kazi_app LOGIN PASSWORD '{APP_ROLE_PASSWORD}'"))
    owner.dispose()

    app_url = (
        make_url(owner_url)
        .set(username="kazi_app", password=APP_ROLE_PASSWORD)
        .render_as_string(hide_password=False)
    )
    try:
        yield owner_url, app_url
    finally:
        with psycopg.connect(
            plain_admin.render_as_string(hide_password=False), autocommit=True
        ) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def owner_engine(database_urls: tuple[str, str]) -> Iterator[Engine]:
    engine = create_engine(database_urls[0])
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def settings(database_urls: tuple[str, str]) -> Settings:
    return make_settings(database_url=database_urls[1])


def make_settings(**values: object) -> Settings:
    """Settings from code only, never from a local .env file."""
    return Settings(_env_file=None, **{"environment": "test", **values})  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def app_engine(settings: Settings) -> Iterator[Engine]:
    engine = make_engine(settings)
    yield engine
    engine.dispose()


@pytest.fixture
def app_sessions(app_engine: Engine, owner_engine: Engine) -> Iterator[sessionmaker[Session]]:
    yield sessionmaker(bind=app_engine, expire_on_commit=False)
    with owner_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))


@pytest.fixture
def outbox() -> list[EmailMessage]:
    return []


@pytest.fixture
def client(
    settings: Settings, app_sessions: sessionmaker[Session], outbox: list[EmailMessage]
) -> TestClient:
    app = create_app(settings)
    app.state.sessionmaker = app_sessions
    app.state.mailer = Mailer(app_sessions, settings, outbox.append)
    return TestClient(app, base_url="http://localhost:8000")
