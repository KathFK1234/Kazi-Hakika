"""Dira pattern rules: fixed counts, shown only from 5 applications."""

from datetime import date, timedelta

from app.services import patterns
from app.services.patterns import AppFacts

TODAY = date(2026, 11, 27)


def app(
    tags: tuple[str, ...] = (),
    *,
    stages: tuple[str, ...] = ("saved", "applied"),
    ended_from: str | None = None,
    source: str = "own",
    age_days: int = 1,
) -> AppFacts:
    return AppFacts(
        tags=tags,
        source=source,
        created_on=TODAY - timedelta(days=age_days),
        stages=frozenset(stages),
        ended_from=ended_from,
    )


def test_four_under_a_tag_show_nothing_five_appear() -> None:
    """Acceptance check: with 4 applications under a tag nothing shows; with 5 it does."""
    four = [app(("backend",)) for _ in range(4)]
    assert patterns.by_tag(four) == []
    five = [*four, app(("backend",), stages=("saved", "applied", "screening"))]
    assert patterns.by_tag(five) == [patterns.Group("backend", 5, 1)]


def test_only_applied_roles_count() -> None:
    saved_only = [app(("data",), stages=("saved",)) for _ in range(6)]
    assert patterns.by_tag(saved_only) == []
    withdrawn_unapplied = [
        app(("data",), stages=("saved", "withdrawn"), ended_from="saved") for _ in range(6)
    ]
    assert patterns.by_tag(withdrawn_unapplied) == []
    rejected_at_interview = [
        app(("data",), stages=("saved", "applied", "interview", "rejected"), ended_from="interview")
        for _ in range(5)
    ]
    assert patterns.by_tag(rejected_at_interview) == [patterns.Group("data", 5, 5)]


def test_by_source() -> None:
    apps = [app(source="board") for _ in range(5)] + [app(source="own") for _ in range(3)]
    assert [g.name for g in patterns.by_source(apps)] == ["board"]


def test_where_they_stop_needs_five_endings_and_prefers_earlier_ties() -> None:
    ended = [app(ended_from="applied") for _ in range(2)] + [
        app(ended_from="screening") for _ in range(2)
    ]
    assert patterns.where_they_stop(ended) is None
    ended.append(app(ended_from="interview"))
    assert patterns.where_they_stop(ended) == patterns.Stop("applied", 2, 5)


def test_direction_fit_matches_tag_words_only() -> None:
    apps = [app(("backend",)), app(("ai-infra",)), app(("design",)), app(()), app(("back",))]
    fit = patterns.direction_fit(apps, "Backend engineer working on AI infra at a fintech", TODAY)
    assert fit == patterns.DirectionFit(recent=5, matching=2, tags=["ai-infra", "backend"])


def test_direction_fit_needs_five_recent_and_a_direction() -> None:
    old = [app(("backend",), age_days=90) for _ in range(5)]
    assert patterns.direction_fit(old, "Backend engineer", TODAY) is None
    recent = [app(("backend",)) for _ in range(5)]
    assert patterns.direction_fit(recent, None, TODAY) is None
    assert patterns.direction_fit(recent, "Backend engineer", TODAY) == patterns.DirectionFit(
        5, 5, ["backend"]
    )
