"""Outbound lookups: SSRF guards, link checks, RDAP and the domain cache. No real network."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.services import lookups
from app.services.lookups import Blocked, Fetcher, Unreachable, resolve_target

PUBLIC = "93.184.215.14"


def resolver_for(table: dict[str, list[str]]) -> lookups.Resolver:
    def resolve(host: str, port: int) -> list[str]:
        if host not in table:
            raise Unreachable("dns")
        return table[host]

    return resolve


Handler = Callable[[httpx.Request], httpx.Response]


def fetcher(handler: Handler, hosts: dict[str, list[str]] | None = None) -> Fetcher:
    table = hosts if hosts is not None else {"tausi.co.ke": [PUBLIC], "rdap.org": [PUBLIC]}
    return Fetcher(resolver_for(table), httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.5",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # noqa: S104 (an address to refuse, not to bind)
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "224.0.0.1",
    ],
)
def test_private_and_special_addresses_are_refused(address: str) -> None:
    with pytest.raises(Blocked):
        resolve_target("https://evil.example/", resolver_for({"evil.example": [address]}))
    literal = f"[{address}]" if ":" in address else address
    with pytest.raises(Blocked):
        resolve_target(f"http://{literal}/", resolver_for({}))


def test_one_private_address_among_public_ones_is_refused() -> None:
    with pytest.raises(Blocked):
        resolve_target(
            "https://mixed.example/", resolver_for({"mixed.example": [PUBLIC, "10.0.0.1"]})
        )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://tausi.co.ke/",
        "file:///etc/passwd",
        "https://tausi.co.ke:8443/",
        "http://tausi.co.ke:22/",
        "https://user:pw@tausi.co.ke/",  # pragma: allowlist secret (refused, not used)
        "https://tausi.co.ke:notaport/",
    ],
)
def test_odd_schemes_ports_and_credentials_are_refused(url: str) -> None:
    with pytest.raises(Blocked):
        resolve_target(url, resolver_for({"tausi.co.ke": [PUBLIC]}))


def test_request_goes_to_the_checked_address_with_the_real_name() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    assert fetcher(handler).link_opens("https://tausi.co.ke/jobs?id=1") is True
    request = seen[0]
    assert request.method == "HEAD"
    assert request.url.host == PUBLIC
    assert request.url.path == "/jobs" and request.url.query == b"id=1"
    assert request.headers["host"] == "tausi.co.ke"
    assert request.extensions["sni_hostname"] == "tausi.co.ke"
    assert "KaziHakika" in request.headers["user-agent"]


def test_ipv6_addresses_are_bracketed() -> None:
    target = resolve_target("https://v6.example/a", resolver_for({"v6.example": ["2606:4700::1"]}))
    assert target.url == "https://[2606:4700::1]/a"


def test_head_refused_then_get_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(405 if request.method == "HEAD" else 200)

    assert fetcher(handler).link_opens("https://tausi.co.ke/j") is True


@pytest.mark.parametrize(
    ("status", "expected"), [(404, False), (410, False), (403, None), (429, None), (503, None)]
)
def test_status_meanings(status: int, expected: bool | None) -> None:
    assert fetcher(lambda r: httpx.Response(status)).link_opens("https://tausi.co.ke/j") is expected


def test_redirects_are_followed_and_rechecked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "tausi.co.ke":
            return httpx.Response(301, headers={"location": "https://inside.example/admin"})
        return httpx.Response(200)

    hosts = {"tausi.co.ke": [PUBLIC], "inside.example": ["10.0.0.7"]}
    # The redirect points at a private address: refused, never requested.
    assert fetcher(handler, hosts).link_opens("https://tausi.co.ke/j") is False

    def to_public(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/j":
            return httpx.Response(302, headers={"location": "/careers"})
        return httpx.Response(200)

    assert fetcher(to_public).link_opens("https://tausi.co.ke/j") is True


def test_too_many_redirects() -> None:
    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    assert fetcher(loop).link_opens("https://tausi.co.ke/j") is False


def test_unknown_name_timeouts_and_errors() -> None:
    ok = fetcher(lambda r: httpx.Response(200))
    assert ok.link_opens("https://nowhere.example/") is False

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    assert fetcher(slow).link_opens("https://tausi.co.ke/j") is None

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert fetcher(refused).link_opens("https://tausi.co.ke/j") is False


def rdap_handler(body: object, status: int = 200) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == "rdap.org"
        return httpx.Response(status, json=body)

    return handler


RDAP_BODY = {
    "events": [
        {"eventAction": "last changed", "eventDate": "2025-04-07T10:05:27Z"},
        {"eventAction": "registration", "eventDate": "2003-02-12T21:00:00Z"},
    ]
}


def test_rdap_registration_date() -> None:
    assert fetcher(rdap_handler(RDAP_BODY)).rdap_registered_on("tausi.co.ke") == (
        True,
        date(2003, 2, 12),
    )
    assert fetcher(rdap_handler({}, 404)).rdap_registered_on("tausi.co.ke") == (True, None)
    assert fetcher(rdap_handler({}, 500)).rdap_registered_on("tausi.co.ke") == (False, None)
    assert fetcher(rdap_handler({"events": "nope"})).rdap_registered_on("x.ke") == (True, None)
    bad_date = {"events": [{"eventAction": "registration", "eventDate": "soon"}]}
    assert fetcher(rdap_handler(bad_date)).rdap_registered_on("x.ke") == (True, None)


def test_rdap_body_is_capped() -> None:
    huge = {"events": [], "pad": "x" * (lookups.RDAP_MAX_BYTES + 10)}
    assert fetcher(rdap_handler(huge)).rdap_registered_on("tausi.co.ke") == (False, None)


def test_rdap_follows_its_redirect_to_the_registry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "rdap.org":
            return httpx.Response(
                302, headers={"location": "https://rdap.kenic.or.ke/domain/tausi.co.ke"}
            )
        return httpx.Response(200, json=RDAP_BODY)

    hosts = {"rdap.org": [PUBLIC], "rdap.kenic.or.ke": [PUBLIC]}
    assert fetcher(handler, hosts).rdap_registered_on("tausi.co.ke")[1] == date(2003, 2, 12)


def test_domain_facts_are_cached_for_seven_days(
    app_sessions: sessionmaker[Session], owner_engine: Engine
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=RDAP_BODY)

    f = fetcher(handler)
    now = datetime(2026, 11, 27, tzinfo=UTC)
    with app_sessions() as db:
        assert lookups.domain_facts(db, f, "tausi.co.ke", now) == date(2003, 2, 12)
        assert lookups.domain_facts(db, f, "tausi.co.ke", now + timedelta(days=6)) == date(
            2003, 2, 12
        )
    assert len(calls) == 1
    with app_sessions() as db:
        lookups.domain_facts(db, f, "tausi.co.ke", now + timedelta(days=8))
    assert len(calls) == 2
    with owner_engine.connect() as c:
        row = c.execute(text("SELECT resolves FROM domain_checks")).one()
    assert row.resolves is True


def test_failed_rdap_is_not_cached(
    app_sessions: sessionmaker[Session], owner_engine: Engine
) -> None:
    with app_sessions() as db:
        assert lookups.domain_facts(db, fetcher(rdap_handler({}, 503)), "tausi.co.ke") is None
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM domain_checks")).scalar_one() == 0


def test_system_resolver_reports_unknown_names() -> None:
    with pytest.raises(Unreachable):
        lookups.system_resolver("name.invalid", 443)


def test_internationalised_names_are_sent_as_punycode() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    hosts = {"xn--bcher-kva.de": [PUBLIC]}
    assert fetcher(handler, hosts).link_opens("https://bücher.de/jobs") is True
    assert seen[0].headers["host"] == "xn--bcher-kva.de"
    assert seen[0].extensions["sni_hostname"] == "xn--bcher-kva.de"


@pytest.mark.parametrize("url", ["https://a" + "b" * 70 + ".com/", "https://\u0000x.com/"])
def test_malformed_names_never_crash(url: str) -> None:
    ok = fetcher(lambda r: httpx.Response(200), {})
    assert ok.link_opens(url) is False
