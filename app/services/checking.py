"""Run the verification rules with their network lookups, inside the caps.

Used by board posts and the public checker. Outbound lookups are limited to
20 an hour per person (or per IP for the anonymous checker) and 600 an hour
for the whole service; past either cap the checks still run, with the
network facts marked unknown, so nobody is refused a check.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NeaAgency
from app.services import lookups
from app.services.lookups import Fetcher
from app.services.ratelimit import Limit, RateLimiter
from app.services.verify import (
    Ad,
    Check,
    Link,
    Lookups,
    Verdict,
    evaluate,
    needs_domain_lookup,
    parse_link,
)
from app.services.verify import verdict as verdict_of

OUTBOUND_PER_ACTOR = Limit("outbound", 20, 3600)
OUTBOUND_ALL = Limit("outbound-all", 600, 3600)
# Licence statuses that mean "not licensed" in an uploaded NEA list.
UNLICENSED = frozenset({"revoked", "suspended", "expired", "deregistered", "inactive", "cancelled"})

# Lookups hold a request thread for up to ~10 s. With one worker and ~40
# threads, a burst could stall every other request, so at most this many
# run at once; past it, checks run without lookups (like the hourly cap).
MAX_CONCURRENT_LOOKUPS = 8
_lookup_slots = threading.BoundedSemaphore(MAX_CONCURRENT_LOOKUPS)
# One link-check thread per slot, so a check never waits in a queue.
_link_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LOOKUPS, thread_name_prefix="linkcheck")


@dataclass(frozen=True)
class CheckRun:
    checks: list[Check]
    verdict: Verdict
    # True when the caps stopped the network lookups this time.
    lookups_paused: bool


def nea_keys(db: Session) -> frozenset[str]:
    rows = db.execute(select(NeaAgency.name_key, NeaAgency.licence_status)).all()
    return frozenset(key for key, status in rows if status.strip().lower() not in UNLICENSED)


def run_checks(
    db: Session, fetcher: Fetcher, limiter: RateLimiter, actor: str, ad: Ad, today: date
) -> CheckRun:
    link = parse_link(ad.url) if ad.url else None
    facts = Lookups()
    paused = False
    if link is not None and ad.url:
        if not _lookup_slots.acquire(blocking=False):
            paused = True
        elif not (limiter.hit(OUTBOUND_PER_ACTOR, actor) and limiter.hit(OUTBOUND_ALL, "all")):
            _lookup_slots.release()
            paused = True
        else:
            try:
                facts = _look_up(db, fetcher, link, ad.url)
            finally:
                _lookup_slots.release()
    checks = evaluate(ad, facts, today, nea_keys(db))
    return CheckRun(checks, verdict_of(c.result for c in checks), paused)


def _look_up(db: Session, fetcher: Fetcher, link: Link, url: str) -> Lookups:
    # The link check and the RDAP lookup run side by side: one 5 s wait, not two.
    pending = _link_pool.submit(fetcher.link_opens, url)
    domain = needs_domain_lookup(link)
    registered_on = lookups.domain_facts(db, fetcher, domain) if domain else None
    try:
        link_ok = pending.result(timeout=lookups.TIMEOUT_SECONDS + 1)
    except FutureTimeout:
        link_ok = None
    return Lookups(registered_on=registered_on, link_ok=link_ok)
