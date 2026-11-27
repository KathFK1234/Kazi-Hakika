"""Every migration can be applied, rolled back and applied again."""

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, make_url, text

from app.config import Settings


@pytest.fixture
def scratch_db() -> Iterator[str]:
    admin = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if not admin:
        pytest.skip("TEST_ADMIN_DATABASE_URL not set")
    url = Settings._use_psycopg_driver(admin)
    assert url
    name = f"kazi_mig_{uuid.uuid4().hex[:8]}"
    plain = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(plain, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    try:
        yield make_url(url).set(database=name).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(plain, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_upgrade_downgrade_upgrade(scratch_db: str) -> None:
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = scratch_db
    engine = create_engine(scratch_db)
    try:
        command.upgrade(cfg, "head")
        tables = set(inspect(engine).get_table_names())
        assert {"users", "applications", "stage_events", "sessions", "auth_tokens"} <= tables

        command.downgrade(cfg, "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        with engine.connect() as c:
            policies = c.execute(text("SELECT count(*) FROM pg_policies")).scalar_one()
        assert policies == 0

        command.upgrade(cfg, "head")
        with engine.connect() as c:
            forced = (
                c.execute(
                    text("SELECT relname FROM pg_class WHERE relforcerowsecurity ORDER BY relname")
                )
                .scalars()
                .all()
            )
        assert forced == ["applications", "nea_agencies", "reports", "stage_events"]
    finally:
        engine.dispose()
