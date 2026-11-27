"""Dira patterns: simple counts from the user's own tracker, by fixed rules.

No predictions and no guessing from free text: groups appear only once they
hold 5 or more applications, and the page labels every number "so far".
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from app.models import STAGES

MIN_GROUP = 5
RECENT_DAYS = 60
APPLIED_OR_LATER = frozenset({"applied", "screening", "interview", "offer"})
SCREENING_OR_LATER = frozenset({"screening", "interview", "offer"})
ENDED = frozenset({"rejected", "withdrawn"})


@dataclass(frozen=True)
class AppFacts:
    tags: tuple[str, ...]
    source: str
    created_on: date
    # Every stage the application has been in, from its history.
    stages: frozenset[str]
    # The stage it was in when it was rejected or withdrawn, if it ended.
    ended_from: str | None


@dataclass(frozen=True)
class Group:
    name: str
    total: int
    reached_screening: int


@dataclass(frozen=True)
class Stop:
    stage: str
    count: int
    ended: int


@dataclass(frozen=True)
class DirectionFit:
    recent: int
    matching: int
    tags: list[str]


def applied(app: AppFacts) -> bool:
    if app.stages & APPLIED_OR_LATER:
        return True
    return app.ended_from is not None and app.ended_from != "saved"


def _groups(apps: list[AppFacts], key: str) -> list[Group]:
    totals: Counter[str] = Counter()
    reached: Counter[str] = Counter()
    for app in apps:
        if not applied(app):
            continue
        names = app.tags if key == "tag" else (app.source,)
        for name in names:
            totals[name] += 1
            if app.stages & SCREENING_OR_LATER:
                reached[name] += 1
    return sorted(
        (Group(n, totals[n], reached[n]) for n in totals if totals[n] >= MIN_GROUP),
        key=lambda g: (-g.total, g.name),
    )


def by_tag(apps: list[AppFacts]) -> list[Group]:
    """Share of applied roles that reached screening or later, per tag."""
    return _groups(apps, "tag")


def by_source(apps: list[AppFacts]) -> list[Group]:
    """The same, per source (own find or the board)."""
    return _groups(apps, "source")


def where_they_stop(apps: list[AppFacts]) -> Stop | None:
    """The stage applications were in when they most often ended."""
    ended = [a.ended_from for a in apps if a.ended_from is not None]
    if len(ended) < MIN_GROUP:
        return None
    counts = Counter(ended)
    # Ties go to the earlier stage.
    stage = min(counts, key=lambda s: (-counts[s], STAGES.index(s)))
    return Stop(stage, counts[stage], len(ended))


def _tag_in(tag: str, sentence: str) -> bool:
    words = r"\s+".join(re.escape(w) for w in tag.split("-") if w)
    return bool(words) and re.search(rf"(?<![a-z0-9]){words}(?![a-z0-9])", sentence) is not None


def direction_fit(apps: list[AppFacts], ideal_role: str | None, today: date) -> DirectionFit | None:
    """How many recent applications carry a tag whose words appear in the
    latest ideal-role sentence. Tags only: the text is never interpreted."""
    if not ideal_role:
        return None
    recent = [a for a in apps if a.created_on >= today - timedelta(days=RECENT_DAYS)]
    if len(recent) < MIN_GROUP:
        return None
    sentence = " ".join(ideal_role.lower().replace("-", " ").split())
    matched: set[str] = set()
    matching = 0
    for app in recent:
        hits = {t for t in app.tags if _tag_in(t, sentence)}
        if hits:
            matching += 1
            matched |= hits
    return DirectionFit(len(recent), matching, sorted(matched))
