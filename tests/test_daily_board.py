"""The daily job's board upkeep: link re-checks, archiving and purging."""

import json
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.jobs import daily
from app.services.digest import today_eat
from app.services.email import Mailer
from app.services.lookups import Fetcher
from tests.factories import make_board_role, make_user

PUBLIC = "93.184.215.14"
LINK_PASS = {"id": "link_resolves", "label": "Link opens", "result": "pass", "detail": "x"}
OTHER_PASS = {"id": "fee_language", "label": "Asks for money", "result": "pass", "detail": "y"}


def fetcher_answering(status: int, seen: list[str] | None = None) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url.path)
        return httpx.Response(status)

    return Fetcher(lambda host, port: [PUBLIC], httpx.MockTransport(handler))


def _run(sessions: sessionmaker[Session], settings: Settings, fetcher: Fetcher) -> daily.Counts:
    return daily.run(sessions, Mailer(sessions, settings, lambda m: None), settings, fetcher)


SETTABLE = {
    "status": "UPDATE board_roles SET status = :v WHERE id = :r",
    "checked_at": "UPDATE board_roles SET checked_at = CAST(:v AS timestamptz) WHERE id = :r",
    "created_at": "UPDATE board_roles SET created_at = CAST(:v AS timestamptz) WHERE id = :r",
    "archived_at": "UPDATE board_roles SET archived_at = CAST(:v AS timestamptz) WHERE id = :r",
}


def _set(owner: Engine, role: uuid.UUID, **cols: object) -> None:
    with owner.begin() as c:
        for col, value in cols.items():
            c.execute(text(SETTABLE[col]), {"v": value, "r": role})


def _row(owner: Engine, role: uuid.UUID) -> dict[str, object] | None:
    with owner.connect() as c:
        row = c.execute(
            text("SELECT status, checks, archived_at FROM board_roles WHERE id = :r"), {"r": role}
        ).one_or_none()
    return dict(row._mapping) if row else None


@pytest.fixture
def stale_role(owner_engine: Engine) -> uuid.UUID:
    role = make_board_role(owner_engine, make_user(owner_engine), url="https://tausi.co.ke/j1")
    _set(owner_engine, role, checked_at="2026-01-01T00:00:00Z")
    with owner_engine.begin() as c:
        c.execute(
            text("UPDATE board_roles SET checks = CAST(:c AS jsonb) WHERE id = :r"),
            {"c": json.dumps([LINK_PASS, OTHER_PASS]), "r": role},
        )
    return role


def test_broken_link_turns_verified_into_unverified(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    stale_role: uuid.UUID,
) -> None:
    counts = _run(app_sessions, settings, fetcher_answering(404))
    assert counts.links_rechecked == 1 and counts.roles_relabelled == 1
    row = _row(owner_engine, stale_role)
    assert row is not None and row["status"] == "unverified"
    link = next(c for c in row["checks"] if c["id"] == "link_resolves")  # type: ignore[attr-defined]
    assert link["result"] == "warn"


def test_link_working_again_restores_verified(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    stale_role: uuid.UUID,
) -> None:
    _set(owner_engine, stale_role, status="unverified")
    _run(app_sessions, settings, fetcher_answering(200))
    row = _row(owner_engine, stale_role)
    assert row is not None and row["status"] == "verified"


def test_recently_checked_hidden_and_flagged_roles_are_left_alone(
    owner_engine: Engine, app_sessions: sessionmaker[Session], settings: Settings
) -> None:
    poster = make_user(owner_engine)
    make_board_role(owner_engine, poster)  # checked just now
    for status in ("hidden", "flagged"):
        role = make_board_role(owner_engine, poster, status=status)
        _set(owner_engine, role, checked_at="2026-01-01T00:00:00Z")
    seen: list[str] = []
    counts = _run(app_sessions, settings, fetcher_answering(404, seen))
    assert counts.links_rechecked == 0 and seen == []


def test_at_most_200_rechecks_a_day(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily, "MAX_LINK_RECHECKS", 3)
    poster = make_user(owner_engine)
    for _ in range(5):
        _set(owner_engine, make_board_role(owner_engine, poster), checked_at="2026-01-01T00:00:00Z")
    seen: list[str] = []
    assert _run(app_sessions, settings, fetcher_answering(200, seen)).links_rechecked == 3
    assert len(seen) == 3


def test_rechecks_stop_at_the_runtime_cap(
    owner_engine: Engine,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    stale_role: uuid.UUID,
) -> None:
    monkeypatch.setattr(daily, "MAX_RUNTIME_SECONDS", -1)
    seen: list[str] = []
    assert _run(app_sessions, settings, fetcher_answering(200, seen)).links_rechecked == 0
    assert seen == []


def test_past_deadline_and_old_undated_roles_are_archived(
    owner_engine: Engine, app_sessions: sessionmaker[Session], settings: Settings
) -> None:
    poster = make_user(owner_engine)
    today = today_eat()
    past = make_board_role(owner_engine, poster, deadline=today - timedelta(days=1))
    due_today = make_board_role(owner_engine, poster, deadline=today)
    old_undated = make_board_role(owner_engine, poster)
    _set(owner_engine, old_undated, created_at="2026-01-01T00:00:00Z")
    new_undated = make_board_role(owner_engine, poster)
    counts = _run(app_sessions, settings, fetcher_answering(200))
    assert counts.roles_archived == 2
    statuses = {
        r: (_row(owner_engine, r) or {})["status"]
        for r in (past, due_today, old_undated, new_undated)
    }
    assert statuses == {
        past: "archived",
        due_today: "verified",
        old_undated: "archived",
        new_undated: "verified",
    }


def test_archived_roles_are_deleted_after_180_days(
    owner_engine: Engine, app_sessions: sessionmaker[Session], settings: Settings
) -> None:
    poster = make_user(owner_engine)
    old = make_board_role(owner_engine, poster, status="archived")
    _set(owner_engine, old, archived_at="2026-01-01T00:00:00Z")
    recent = make_board_role(owner_engine, poster, status="archived")
    _set(owner_engine, recent, archived_at="2026-11-01T00:00:00Z")
    with owner_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO domain_checks (domain, checked_at) VALUES "
                "('old.co.ke', now() - interval '31 days'), ('new.co.ke', now())"
            )
        )
    counts = _run(app_sessions, settings, fetcher_answering(200))
    assert counts.roles_purged == 1 and counts.domain_cache_purged == 1
    assert _row(owner_engine, old) is None and _row(owner_engine, recent) is not None


def test_users_cannot_act_as_the_job(
    owner_engine: Engine, app_sessions: sessionmaker[Session]
) -> None:
    """Without the job identity, the app role can't archive other people's posts."""
    role = make_board_role(owner_engine, make_user(owner_engine))
    with app_sessions() as s:
        changed = s.execute(
            text("UPDATE board_roles SET status = 'archived' WHERE id = :r RETURNING id"),
            {"r": role},
        ).one_or_none()
        s.commit()
    assert changed is None
