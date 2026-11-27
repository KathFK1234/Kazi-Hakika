"""The "Is this job real?" rules: pure functions, no AI, no I/O.

The same inputs always give the same checks, for everyone. Network facts
(when the domain was registered, whether the link opens) are looked up by
app.services.lookups and passed in, so every rule here is unit-testable.

Checks never quote the ad back: details name the rule that matched (for
example "registration fee"), never the pasted text, so stored results hold
no ad text.
"""

import ipaddress
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

Result = Literal["pass", "warn", "flag", "unknown", "skip"]
Verdict = Literal["verified", "unverified", "flagged"]

NEW_DOMAIN_DAYS = 90
MAX_TEXT = 10_000

# Hiring platforms companies use; the path or subdomain names the company.
ATS_NAMES = {
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "myworkdayjobs.com": "Workday",
    "smartrecruiters.com": "SmartRecruiters",
    "ashbyhq.com": "Ashby",
    "bamboohr.com": "BambooHR",
}
SHORTENERS = frozenset(
    {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "cutt.ly", "rb.gy", "shorturl.at", "is.gd"}
)
CHAT_HOSTS = frozenset({"wa.me", "whatsapp.com", "t.me", "telegram.me"})
FORM_HOSTS = frozenset({"forms.gle"})
PERSONAL_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.uk",
        "ymail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "protonmail.com",
        "proton.me",
        "gmx.com",
        "mail.com",
        "yandex.com",
    }
)
# Second-level suffixes where the registrable domain has three labels
# (acme.co.ke). A short list for the region instead of the full Public
# Suffix List; anything else is treated as name.tld.
MULTI_LABEL_SUFFIXES = frozenset(
    {
        "co.ke", "or.ke", "ac.ke", "go.ke", "ne.ke", "sc.ke", "me.ke", "info.ke", "mobi.ke",
        "co.tz", "or.tz", "ac.tz", "go.tz", "co.ug", "or.ug", "ac.ug", "go.ug", "co.rw",
        "com.ng", "org.ng", "com.gh", "co.za", "org.za", "co.uk", "org.uk", "ac.uk",
        "com.au", "co.in", "com.sg", "com.br", "co.jp", "com.eg", "com.et",
    }
)  # fmt: skip
LEGAL_WORDS = frozenset({"limited", "ltd", "plc", "inc", "llc", "llp", "co", "company", "the"})
COMPANY_FILLER = LEGAL_WORDS | {
    "kenya", "ke", "group", "holdings", "africa", "eastafrica", "ea", "international",
    "technologies", "technology", "tech", "solutions", "services", "careers", "jobs", "and",
}  # fmt: skip


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    result: Result
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class Ad:
    url: str | None
    text: str
    company: str
    agency: str | None = None


@dataclass(frozen=True)
class Link:
    host: str
    domain: str  # registrable domain, e.g. acme.co.ke
    platform: str | None  # "Greenhouse", "LinkedIn", ... when it's a hiring platform
    slug: str | None  # the company named by the platform's URL, if any
    kind: Literal["platform", "shortener", "chat", "form", "ip", "site"]


@dataclass(frozen=True)
class Lookups:
    """Network facts: None means unknown (lookup failed or not done)."""

    registered_on: date | None = None
    link_ok: bool | None = None


# --- parsing -------------------------------------------------------------


def registrable_domain(host: str) -> str:
    labels = host.lower().strip(".").split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def parse_link(url: str) -> Link | None:
    """None if it isn't an http(s) link with a host."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return Link(host, host, None, None, "ip")
    host = host.removeprefix("www.")
    domain = registrable_domain(host)
    segments = [s for s in parts.path.split("/") if s]
    first_label = host.split(".")[0]

    if domain == "linkedin.com":
        slug = segments[1] if len(segments) >= 2 and segments[0] == "company" else None
        if segments and segments[0] in ("jobs", "company"):
            return Link(host, domain, "LinkedIn", slug, "platform")
    if domain in ATS_NAMES:
        name = ATS_NAMES[domain]
        if domain in ("myworkdayjobs.com", "bamboohr.com"):
            slug = first_label if host != domain else None
        else:
            slug = segments[0] if segments else None
        return Link(host, domain, name, slug, "platform")
    if host in SHORTENERS or domain in SHORTENERS:
        return Link(host, domain, None, None, "shortener")
    if domain in CHAT_HOSTS or host in CHAT_HOSTS:
        return Link(host, domain, None, None, "chat")
    if host in FORM_HOSTS or (host == "docs.google.com" and segments[:1] == ["forms"]):
        return Link(host, domain, None, None, "form")
    return Link(host, domain, None, None, "site")


def needs_domain_lookup(link: Link | None) -> str | None:
    """The domain whose registration date matters, or None."""
    return link.domain if link is not None and link.kind == "site" else None


def _words(value: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    folded = folded.replace("&", " and ")
    return re.findall(r"[a-z0-9]+", folded)


def name_key(name: str) -> str:
    """Agency names compared without case, punctuation or legal suffixes."""
    return "".join(w for w in _words(name) if w not in LEGAL_WORDS)


def _company_forms(company: str) -> set[str]:
    named = [w for w in _words(company) if w not in LEGAL_WORDS]
    core = [w for w in named if w not in COMPANY_FILLER] or named
    forms = {"".join(named), "".join(core)}
    if core:
        forms.add(core[0])
    if len(named) >= 2:
        forms.add("".join(w[0] for w in named))  # Kenya Commercial Bank -> kcb
    return {f for f in forms if len(f) >= 3}


def names_match(company: str, label: str) -> bool:
    """Does a domain label or platform slug belong to the company?

    Exact forms only: look-alike domains (tausi-careers.com, tausi-jobs.com)
    are how scam ads borrow a real name, so they don't count as a match.
    """
    return "".join(_words(label)) in _company_forms(company)


# --- text rules ----------------------------------------------------------

_FEE_WORDS = (
    "application|processing|registration|admin|administration|medical|training|interview"
    "|facilitation|commitment|placement|booking|clearance|visa|visa processing|recruitment"
    "|consultation|uniform|onboarding|vetting|certificate|insurance"
)
FEE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a fee to apply or get hired", re.compile(rf"\b(?:{_FEE_WORDS})\s+(?:fees?|charges?)\b")),
    ("pay a fee or deposit", re.compile(
        r"\bpay\s+(?:a\s+|the\s+|an?\s+)?(?:small\s+|one[- ]off\s+|refundable\s+)?"
        r"(?:fee|deposit|amount|charge)")),
    ("pay to", re.compile(r"\bpay\s+to\b")),
    ("refundable deposit", re.compile(r"\brefundable\s+(?:deposit|fee)\b")),
    ("money in KSh", re.compile(
        r"\b(?:ksh|kshs|kes|sh)\.?\s*\d[\d,]*(?:\.\d+)?\s*(?:/=|/-)?.{0,40}?\b(?:fee|deposit|pay)"
        r"|\b(?:fee|deposit|pay)\b.{0,40}?\b(?:ksh|kshs|kes)\.?\s*\d")),
    ("an M-Pesa till or paybill", re.compile(
        r"\b(?:till|paybill|pay\s*bill)\s*(?:no\.?|number|#)?\s*:?\s*\d{4,}"
        r"|\blipa\s+na\s+m-?pesa\b|\bm-?pesa\b.{0,40}?\b(?:till|paybill|send|pay)\b")),
    ("ada (a fee, in Kiswahili)", re.compile(r"\bada\s+ya\s+\w+|\blipa\s+ada\b")),
    ("send money", re.compile(r"\bsend\s+(?:the\s+)?money\b")),
)  # fmt: skip
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
PHONE_RE = re.compile(r"(?:\+|\b00)?\b(?:254|0)\s?[17]\d{2}[\s-]?\d{3}[\s-]?\d{3}\b|\+\d{10,14}\b")
WHATSAPP_RE = re.compile(r"\bwhats\s?app\b|\bwa\.me\b", re.IGNORECASE)
OVERSEAS_RE = re.compile(
    r"\b(?:abroad|overseas|gulf|middle east|saudi|ksa|riyadh|jeddah|qatar|doha|dubai|uae"
    r"|abu dhabi|oman|muscat|kuwait|bahrain|lebanon|jordan|iraq|poland|romania)\b"
)
RECRUIT_RE = re.compile(
    r"\b(?:recruit\w*|agenc\w*|placement|visa|air ?tickets?|work permits?|housemaids?"
    r"|house ?helps?|domestic workers?|caregivers?)\b"
)


def _clean_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text[:MAX_TEXT]).lower()


def fee_phrases(text: str) -> list[str]:
    t = _clean_text(text)
    return [label for label, pattern in FEE_PATTERNS if pattern.search(t)]


def email_domains(text: str) -> list[str]:
    return sorted({m.lower() for m in EMAIL_RE.findall(text[:MAX_TEXT])})


def has_phone_or_whatsapp(text: str) -> bool:
    t = text[:MAX_TEXT]
    return bool(PHONE_RE.search(t) or WHATSAPP_RE.search(t))


def is_overseas_recruitment(text: str) -> bool:
    t = _clean_text(text)
    return bool(OVERSEAS_RE.search(t) and RECRUIT_RE.search(t))


# --- the checks ----------------------------------------------------------

LINK_LABELS = {
    "link_present": "Link to the job",
    "link_host": "Where the link goes",
    "domain_match": "Website matches the company",
    "domain_age": "Website age",
    "link_resolves": "Link opens",
}
TEXT_LABELS = {
    "fee_language": "Asks for money",
    "personal_email": "Company email",
    "whatsapp_only": "Ways to contact them",
    "overseas_recruiter": "Licensed agency (jobs abroad)",
}
HOST_WARNINGS = {
    "shortener": "A short link hides where it really goes. Ask for the full link.",
    "chat": "The link opens a chat (WhatsApp or Telegram), not a job ad.",
    "form": "The link is an online form, not a company or job site.",
    "ip": "The link is a bare number address, not a named website.",
}
NEA = "the National Employment Authority"


def _check(id_: str, result: Result, detail: str) -> Check:
    return Check(id_, LINK_LABELS.get(id_) or TEXT_LABELS[id_], result, detail)


def link_checks(link: Link | None, ad: Ad, lookups: Lookups, today: date) -> list[Check]:
    if link is None:
        detail = "No link given, so there's nothing to check."
        missing = (
            "There's no link to a company page or job site. Ask for one: real employers "
            "can point you to the ad."
        )
        return [_check("link_present", "warn", missing)] + [
            _check(id_, "skip", detail) for id_ in list(LINK_LABELS)[1:]
        ]
    return [
        _check("link_present", "pass", "A link was given."),
        _link_host(link, ad),
        _domain_match(link, ad),
        _domain_age(link, lookups, today),
        _link_resolves(lookups),
    ]


def _company(ad: Ad) -> str:
    return ad.company.strip() or "the company"


def _link_host(link: Link, ad: Ad) -> Check:
    if link.kind == "platform":
        return _check("link_host", "pass", f"Hosted on {link.platform}, a site companies use.")
    if link.kind in HOST_WARNINGS:
        return _check("link_host", "warn", HOST_WARNINGS[link.kind])
    if names_match(ad.company, link.domain.split(".")[0]):
        own = f"On what looks like {_company(ad)}'s own website ({link.domain})."
        return _check("link_host", "pass", own)
    unknown = f"{link.domain} isn't a known job site, and we can't tell if it's {_company(ad)}'s."
    return _check("link_host", "unknown", unknown)


def _domain_match(link: Link, ad: Ad) -> Check:
    company = _company(ad)
    if not ad.company.strip():
        return _check("domain_match", "skip", "No company name given.")
    if link.kind == "platform":
        if link.slug is None:
            unnamed = f"This {link.platform} link doesn't name the company; open it to check."
            return _check("domain_match", "unknown", unnamed)
        if names_match(ad.company, link.slug):
            return _check("domain_match", "pass", f"The {link.platform} page is {company}'s.")
        other = f"The {link.platform} page belongs to \u201c{link.slug}\u201d, not {company}."
        return _check("domain_match", "warn", other)
    if link.kind != "site":
        return _check("domain_match", "skip", "Not a website we can match to a company.")
    if names_match(ad.company, link.domain.split(".")[0]):
        return _check("domain_match", "pass", f"{link.domain} matches {company}.")
    mismatch = (
        f"{link.domain} doesn't match {company}. Scam ads often copy a real company's name "
        "onto another website."
    )
    return _check("domain_match", "warn", mismatch)


def _domain_age(link: Link, lookups: Lookups, today: date) -> Check:
    if link.kind == "platform":
        return _check("domain_age", "pass", f"{link.platform} is a long-running hiring site.")
    if link.kind != "site":
        return _check("domain_age", "skip", "Not a website we can look up.")
    if lookups.registered_on is None:
        unknown = f"We couldn't find when {link.domain} was registered."
        return _check("domain_age", "unknown", unknown)
    age = (today - lookups.registered_on).days
    if age < NEW_DOMAIN_DAYS:
        new = (
            f"{link.domain} was registered only {max(age, 0)} days ago. New websites are "
            "common in scams."
        )
        return _check("domain_age", "warn", new)
    since = f"{link.domain} has been registered since {lookups.registered_on.year}."
    return _check("domain_age", "pass", since)


def _link_resolves(lookups: Lookups) -> Check:
    if lookups.link_ok is True:
        return _check("link_resolves", "pass", "The link opened.")
    if lookups.link_ok is False:
        broken = "The link didn't open. The ad may have closed, or it may not be real."
        return _check("link_resolves", "warn", broken)
    return _check("link_resolves", "unknown", "We couldn't check the link just now.")


def text_checks(ad: Ad, nea_keys: frozenset[str] | None, link: Link | None) -> list[Check]:
    if not ad.text.strip():
        return [
            _check(id_, "skip", "Paste the ad's text to run this check.") for id_ in TEXT_LABELS
        ]
    return [_fees(ad), _personal_email(ad), _contact(ad, link), _overseas(ad, nea_keys)]


def _fees(ad: Ad) -> Check:
    fees = fee_phrases(ad.text)
    if not fees:
        return _check("fee_language", "pass", "No request for fees or deposits.")
    flagged = (
        f"Mentions {', '.join(fees)}. Real employers never charge you to apply, train or get hired."
    )
    return _check("fee_language", "flag", flagged)


def _personal_email(ad: Ad) -> Check:
    domains = email_domains(ad.text)
    personal = [d for d in domains if d in PERSONAL_EMAIL_DOMAINS]
    if personal:
        warn = (
            f"The contact uses a personal {personal[0]} address. Companies usually write "
            "from their own domain."
        )
        return _check("personal_email", "warn", warn)
    if domains:
        return _check("personal_email", "pass", "Contact emails use a company domain.")
    return _check("personal_email", "pass", "No personal email addresses in the ad.")


def _contact(ad: Ad, link: Link | None) -> Check:
    has_web = link is not None and link.kind in ("platform", "site")
    if has_phone_or_whatsapp(ad.text) and not email_domains(ad.text) and not has_web:
        only = (
            "The only contact is a phone or WhatsApp number. Real employers also have an "
            "email address or a website."
        )
        return _check("whatsapp_only", "warn", only)
    return _check("whatsapp_only", "pass", "There's a way to reach them besides a phone number.")


def _overseas(ad: Ad, nea_keys: frozenset[str] | None) -> Check:
    if not is_overseas_recruitment(ad.text):
        return _check("overseas_recruiter", "pass", "Not an ad recruiting for work abroad.")
    agency = (ad.agency or ad.company).strip()
    if not agency:
        unnamed = (
            f"Recruits for work abroad but doesn't name the agency. {NEA[0].upper()}{NEA[1:]} "
            "lists licensed agencies at neaims.go.ke."
        )
        return _check("overseas_recruiter", "flag", unnamed)
    if not nea_keys:
        not_loaded = (
            f"We haven't loaded {NEA}'s licence list yet. Check {agency} at neaims.go.ke "
            "before you pay or travel."
        )
        return _check("overseas_recruiter", "unknown", not_loaded)
    if name_key(agency) in nea_keys:
        return _check("overseas_recruiter", "pass", f"{agency} is on {NEA}'s licensed list.")
    unlicensed = (
        f"{agency} isn't on {NEA}'s list of licensed agencies. Unlicensed agencies recruiting "
        "for jobs abroad are a common scam."
    )
    return _check("overseas_recruiter", "flag", unlicensed)


def evaluate(
    ad: Ad, lookups: Lookups, today: date, nea_keys: frozenset[str] | None = None
) -> list[Check]:
    link = parse_link(ad.url) if ad.url else None
    return link_checks(link, ad, lookups, today) + text_checks(ad, nea_keys, link)


def verdict(results: Iterable[str]) -> Verdict:
    """Any flag: flagged. Every check passed: verified. Otherwise unverified."""
    values = list(results)
    if "flag" in values:
        return "flagged"
    if values and all(r == "pass" for r in values):
        return "verified"
    return "unverified"
