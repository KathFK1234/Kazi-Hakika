"""Outbound lookups for the verification rules: does a link open, and when
was its domain registered (RDAP). The only code that requests user-supplied
URLs, so it guards against server-side request forgery:

- http(s) on ports 80/443 only; every hop (redirects too) is resolved first
  and refused unless every address is public (no loopback, private,
  link-local, carrier-grade NAT or reserved ranges, IPv4-mapped included);
- the request then goes to the address that was checked, with the original
  name for Host and TLS (SNI and certificate checks), so DNS can't answer
  differently in between (rebinding);
- one deadline of 5 seconds per lookup, at most 3 redirects, HEAD then one
  GET, bodies never read for link checks and capped for RDAP;
- nothing is logged but outcomes: no URLs, no domains.
"""

import ipaddress
import json
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import monotonic
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import DomainCheck

TIMEOUT_SECONDS = 5.0
MAX_REDIRECTS = 3
RDAP_URL = "https://rdap.org/domain/{}"
RDAP_MAX_BYTES = 256 * 1024
CACHE_DAYS = 7
USER_AGENT = "KaziHakikaLinkCheck/1.0 (job ad verification)"
REDIRECTS = frozenset({301, 302, 303, 307, 308})
# Sites that refuse automated checks or are briefly down: not proof either way.
INCONCLUSIVE = frozenset({401, 403, 429, 999})

Resolver = Callable[[str, int], list[str]]

_dns_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dns")


class Blocked(Exception):
    """The URL points somewhere we never connect to."""


class Unreachable(Exception):
    """The name doesn't resolve or nothing answered."""


def system_resolver(host: str, port: int) -> list[str]:
    future = _dns_pool.submit(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    try:
        infos = future.result(timeout=TIMEOUT_SECONDS)
    except FutureTimeout:
        raise TimeoutError("dns") from None
    except socket.gaierror, UnicodeError:
        raise Unreachable("dns") from None
    return sorted({str(info[4][0]) for info in infos})


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


@dataclass(frozen=True)
class Target:
    url: str  # with the checked address in place of the name
    host: str
    host_header: str
    https: bool


def resolve_target(url: str, resolver: Resolver) -> Target:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Blocked("scheme")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise Blocked("port") from None
    if port not in (80, 443):
        raise Blocked("port")
    if parts.username or parts.password:
        raise Blocked("credentials")
    try:
        # Internationalised names travel as punycode (bücher.de -> xn--bcher-kva.de).
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise Blocked("name") from None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addresses = resolver(host, port)
    else:
        addresses = [str(literal)]
    if not addresses or not all(_is_public(a) for a in addresses):
        raise Blocked("address")
    address = addresses[0]
    netloc = f"[{address}]" if ":" in address else address
    default = (parts.scheme == "https" and port == 443) or (parts.scheme == "http" and port == 80)
    if not default:
        netloc += f":{port}"
    host_header = host if default else f"{host}:{port}"
    pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    return Target(pinned, host, host_header, parts.scheme == "https")


class Fetcher:
    def __init__(
        self, resolver: Resolver = system_resolver, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.resolver = resolver
        self.transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            transport=self.transport,
            follow_redirects=False,
            trust_env=False,  # never a proxy from the environment
            headers={"User-Agent": USER_AGENT},
        )

    def _follow(
        self, client: httpx.Client, method: str, url: str, deadline: float
    ) -> httpx.Response:
        """Send, following up to MAX_REDIRECTS, re-checking every hop. Streams:
        the caller closes the response and reads the body only if it must."""
        for _ in range(MAX_REDIRECTS + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("deadline")
            target = resolve_target(url, self.resolver)
            request = client.build_request(
                method,
                target.url,
                headers={"Host": target.host_header, "Accept": "*/*"},
                timeout=httpx.Timeout(remaining),
                extensions={"sni_hostname": target.host} if target.https else {},
            )
            response = client.send(request, stream=True)
            location = response.headers.get("location")
            if response.status_code in REDIRECTS and location:
                response.close()
                url = urljoin(url, location)
                if response.status_code == 303 and method != "HEAD":
                    method = "GET"
                continue
            return response
        raise Unreachable("redirects")

    def link_opens(self, url: str) -> bool | None:
        """True: it answered 2xx. False: it doesn't exist, refused, or isn't
        allowed. None: unknown (timed out, or the site refuses bot checks)."""
        deadline = monotonic() + TIMEOUT_SECONDS
        try:
            with self._client() as client:
                status = 0
                for method in ("HEAD", "GET"):
                    with closing(self._follow(client, method, url, deadline)) as response:
                        status = response.status_code
                    if 200 <= status < 300:
                        return True
                    if status not in (403, 404, 405, 501, *INCONCLUSIVE):
                        break  # a HEAD answer that a GET won't change
                if status in INCONCLUSIVE or status >= 500:
                    return None
                return False
        except Blocked, Unreachable:
            return False
        except TimeoutError, httpx.TimeoutException:
            return None
        except httpx.HTTPError, httpx.InvalidURL, OSError, ValueError:
            # Malformed URLs and odd answers: the link doesn't open.
            return False

    def rdap_registered_on(self, domain: str) -> tuple[bool, date | None]:
        """(answered, registration date). answered=False means try again later."""
        deadline = monotonic() + TIMEOUT_SECONDS
        try:
            with (
                self._client() as client,
                closing(self._follow(client, "GET", RDAP_URL.format(domain), deadline)) as response,
            ):
                if response.status_code == 404:
                    return True, None
                if response.status_code != 200:
                    return False, None
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > RDAP_MAX_BYTES or monotonic() > deadline:
                        return False, None
        except Blocked, Unreachable, TimeoutError, httpx.HTTPError, httpx.InvalidURL, OSError:
            return False, None
        try:
            data = json.loads(body)
        except ValueError:
            return False, None
        return True, registration_date(data)


def registration_date(data: object) -> date | None:
    if not isinstance(data, dict):
        return None
    for event in data.get("events") or []:
        if isinstance(event, dict) and event.get("eventAction") == "registration":
            try:
                return datetime.fromisoformat(str(event.get("eventDate"))).date()
            except ValueError:
                return None
    return None


def domain_facts(
    db: Session, fetcher: Fetcher, domain: str, now: datetime | None = None
) -> date | None:
    """A domain's registration date, from the 7-day cache or RDAP."""
    now = now or datetime.now(UTC)
    row = db.get(DomainCheck, domain)
    if row is not None and row.checked_at > now - timedelta(days=CACHE_DAYS):
        return row.registered_on
    answered, registered_on = fetcher.rdap_registered_on(domain)
    if not answered:
        return row.registered_on if row is not None else None
    try:
        resolves = bool(fetcher.resolver(domain, 443))
    except Unreachable, TimeoutError, OSError:
        resolves = False
    values = {"registered_on": registered_on, "resolves": resolves, "checked_at": now}
    # Two checks of one domain at once both land here: upsert, don't collide.
    db.execute(
        insert(DomainCheck)
        .values(domain=domain, **values)
        .on_conflict_do_update(index_elements=["domain"], set_={**values, "updated_at": now})
    )
    db.commit()
    return registered_on
