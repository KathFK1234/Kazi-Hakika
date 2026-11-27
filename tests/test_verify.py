"""Every verification rule, with Kenyan scam phrasings, and a labelled fixture of ads."""

from datetime import date, timedelta

import pytest

from app.services import verify
from app.services.verify import Ad, Lookups, evaluate, parse_link, verdict

TODAY = date(2026, 11, 27)
OLD = Lookups(registered_on=date(2012, 5, 1), link_ok=True)


def _by_id(checks: list[verify.Check]) -> dict[str, verify.Check]:
    return {c.id: c for c in checks}


# --- links ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "domain", "platform", "slug", "kind"),
    [
        ("https://www.tausi.co.ke/careers/1", "tausi.co.ke", None, None, "site"),
        ("https://careers.tausi.com/x", "tausi.com", None, None, "site"),
        ("https://boards.greenhouse.io/tausi/jobs/1", "greenhouse.io", "Greenhouse", "tausi",
         "platform"),
        ("https://job-boards.greenhouse.io/tausi/jobs/1", "greenhouse.io", "Greenhouse", "tausi",
         "platform"),
        ("https://jobs.lever.co/tausi/abc", "lever.co", "Lever", "tausi", "platform"),
        ("https://tausi.wd3.myworkdayjobs.com/en-US/x", "myworkdayjobs.com", "Workday", "tausi",
         "platform"),
        ("https://jobs.smartrecruiters.com/Tausi/1", "smartrecruiters.com", "SmartRecruiters",
         "Tausi", "platform"),
        ("https://jobs.ashbyhq.com/tausi/1", "ashbyhq.com", "Ashby", "tausi", "platform"),
        ("https://tausi.bamboohr.com/careers/1", "bamboohr.com", "BambooHR", "tausi", "platform"),
        ("https://www.linkedin.com/jobs/view/123", "linkedin.com", "LinkedIn", None, "platform"),
        ("https://www.linkedin.com/company/tausi/jobs", "linkedin.com", "LinkedIn", "tausi",
         "platform"),
        ("https://bit.ly/3abc", "bit.ly", None, None, "shortener"),
        ("https://wa.me/254700000000", "wa.me", None, None, "chat"),
        ("https://forms.gle/abc", "forms.gle", None, None, "form"),
        ("https://docs.google.com/forms/d/x", "google.com", None, None, "form"),
        ("http://203.0.113.9/jobs", "203.0.113.9", None, None, "ip"),
    ],
)  # fmt: skip
def test_parse_link(url: str, domain: str, platform: str, slug: str, kind: str) -> None:
    link = parse_link(url)
    assert link is not None
    assert (link.domain, link.platform, link.slug, link.kind) == (domain, platform, slug, kind)


@pytest.mark.parametrize("url", ["ftp://x.com/a", "javascript:alert(1)", "https://", "not a url"])
def test_parse_link_refuses_non_web_links(url: str) -> None:
    assert parse_link(url) is None


def test_linkedin_pages_other_than_jobs_are_ordinary_sites() -> None:
    link = parse_link("https://www.linkedin.com/posts/someone_hiring")
    assert link is not None and link.kind == "site"


@pytest.mark.parametrize(
    ("company", "label", "matches"),
    [
        ("Tausi Analytics Ltd", "tausi", True),
        ("Tausi Analytics Ltd", "tausianalytics", True),
        ("Kenya Commercial Bank", "kcb", True),
        ("Mawingu Technologies Kenya", "mawingu", True),
        ("Tausi Analytics", "tausi-careers", False),
        ("Tausi Analytics", "tausi-analytics", True),
        ("Tausi Analytics", "jobs-portal-ke", False),
        ("Tausi", "ta", False),
        ("Acme", "acmee", False),
        ("Kenya Commercial Bank", "kenyacommercialbank", True),
    ],
)
def test_names_match(company: str, label: str, matches: bool) -> None:
    assert verify.names_match(company, label) is matches


def test_no_link_warns_and_skips_the_link_checks() -> None:
    checks = _by_id(evaluate(Ad(None, "", "Tausi"), Lookups(), TODAY))
    assert checks["link_present"].result == "warn"
    for id_ in ("link_host", "domain_match", "domain_age", "link_resolves"):
        assert checks[id_].result == "skip"


def test_company_site_passes_every_link_check() -> None:
    checks = _by_id(evaluate(Ad("https://tausi.co.ke/jobs/1", "", "Tausi Analytics"), OLD, TODAY))
    for id_ in ("link_present", "link_host", "domain_match", "domain_age", "link_resolves"):
        assert checks[id_].result == "pass", checks[id_]


def test_look_alike_domain_does_not_match() -> None:
    checks = _by_id(evaluate(Ad("https://tausi-careers.com/a", "", "Tausi"), OLD, TODAY))
    assert checks["domain_match"].result == "warn"


def test_other_domain_warns_on_match_and_is_unknown_host() -> None:
    checks = _by_id(evaluate(Ad("https://jobs-hiring-now.com/a", "", "Tausi"), OLD, TODAY))
    assert checks["link_host"].result == "unknown"
    assert checks["domain_match"].result == "warn"


def test_ats_slug_must_match_the_company() -> None:
    good = _by_id(evaluate(Ad("https://jobs.lever.co/tausi/1", "", "Tausi"), OLD, TODAY))
    bad = _by_id(evaluate(Ad("https://jobs.lever.co/otherco/1", "", "Tausi"), OLD, TODAY))
    assert good["link_host"].result == good["domain_match"].result == "pass"
    assert bad["domain_match"].result == "warn"
    assert good["domain_age"].result == "pass"


def test_linkedin_job_view_cannot_be_matched() -> None:
    checks = _by_id(evaluate(Ad("https://linkedin.com/jobs/view/1", "", "Tausi"), OLD, TODAY))
    assert checks["link_host"].result == "pass"
    assert checks["domain_match"].result == "unknown"


@pytest.mark.parametrize("url", ["https://bit.ly/x", "https://wa.me/2547", "https://forms.gle/x"])
def test_shorteners_chats_and_forms_warn(url: str) -> None:
    checks = _by_id(evaluate(Ad(url, "", "Tausi"), Lookups(link_ok=True), TODAY))
    assert checks["link_host"].result == "warn"
    assert checks["domain_age"].result == "skip"


def test_domain_age() -> None:
    ad = Ad("https://tausi.co.ke/j", "", "Tausi")
    new = Lookups(registered_on=TODAY - timedelta(days=89), link_ok=True)
    edge = Lookups(registered_on=TODAY - timedelta(days=90), link_ok=True)
    assert _by_id(evaluate(ad, new, TODAY))["domain_age"].result == "warn"
    assert _by_id(evaluate(ad, edge, TODAY))["domain_age"].result == "pass"
    assert _by_id(evaluate(ad, Lookups(link_ok=True), TODAY))["domain_age"].result == "unknown"


def test_link_resolves() -> None:
    ad = Ad("https://tausi.co.ke/j", "", "Tausi")
    assert _by_id(evaluate(ad, OLD, TODAY))["link_resolves"].result == "pass"
    broken = Lookups(registered_on=OLD.registered_on, link_ok=False)
    assert _by_id(evaluate(ad, broken, TODAY))["link_resolves"].result == "warn"
    assert _by_id(evaluate(ad, Lookups(), TODAY))["link_resolves"].result == "unknown"


def test_needs_domain_lookup_only_for_ordinary_sites() -> None:
    assert verify.needs_domain_lookup(parse_link("https://tausi.co.ke/x")) == "tausi.co.ke"
    assert verify.needs_domain_lookup(parse_link("https://jobs.lever.co/t/1")) is None
    assert verify.needs_domain_lookup(None) is None


# --- text ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Successful applicants will pay a registration fee of KSh 1,500.",
        "Application fee: Kshs. 500/= payable before the interview.",
        "Pay KES 2000 for medical fee at our clinic.",
        "A small processing fee applies.",
        "Send 1,000 to M-Pesa till number 543210 to book your slot.",
        "Lipa na M-Pesa paybill 400200, account: JOB.",
        "Training fees of Sh 3,500 are refundable after your first salary.",
        "Kindly pay to secure your position.",
        "A refundable deposit is required.",
        "Ada ya usajili ni shilingi 1000.",
        "Visa processing fee covered by the candidate.",
        "Interview charges apply.",
        "Please send the money to confirm.",
    ],
)
def test_fee_language_is_flagged(text: str) -> None:
    check = _by_id(evaluate(Ad(None, text, "Tausi"), Lookups(), TODAY))["fee_language"]
    assert check.result == "flag", text
    # Details name the rule, never the pasted text.
    assert text not in check.detail


@pytest.mark.parametrize(
    "text",
    [
        "Competitive salary of KSh 150,000 gross plus medical cover.",
        "We pay our interns a monthly stipend.",
        "No fees are charged at any stage of our recruitment.",
        "Apply on our careers page before 5 December.",
    ],
)
def test_ordinary_pay_talk_is_not_flagged(text: str) -> None:
    check = _by_id(evaluate(Ad(None, text, "Tausi"), Lookups(), TODAY))["fee_language"]
    assert check.result == "pass", text


def test_personal_email_warns_company_email_passes() -> None:
    gmail = _by_id(evaluate(Ad(None, "Send CVs to hr.tausi@gmail.com", "Tausi"), Lookups(), TODAY))
    own = _by_id(evaluate(Ad(None, "Send CVs to hr@tausi.co.ke", "Tausi"), Lookups(), TODAY))
    none = _by_id(evaluate(Ad(None, "Apply on the website", "Tausi"), Lookups(), TODAY))
    assert gmail["personal_email"].result == "warn"
    assert "hr.tausi" not in gmail["personal_email"].detail
    assert own["personal_email"].result == "pass"
    assert none["personal_email"].result == "pass"


@pytest.mark.parametrize(
    "text",
    [
        "Call or WhatsApp 0712 345 678 for details.",
        "Contact +254712345678",
        "WhatsApp only: 0110 123 456",
    ],
)
def test_phone_only_contact_warns(text: str) -> None:
    check = _by_id(evaluate(Ad(None, text, "Tausi"), Lookups(), TODAY))["whatsapp_only"]
    assert check.result == "warn"


def test_phone_with_email_or_company_link_is_fine() -> None:
    with_email = "WhatsApp 0712345678 or email hr@tausi.co.ke"
    assert _by_id(evaluate(Ad(None, with_email, "Tausi"), Lookups(), TODAY))[
        "whatsapp_only"
    ].result == ("pass")
    with_link = Ad("https://tausi.co.ke/j", "Questions? Call 0712345678", "Tausi")
    assert _by_id(evaluate(with_link, OLD, TODAY))["whatsapp_only"].result == "pass"


OVERSEAS = "Urgent recruitment for housemaids in Saudi Arabia. Free visa and air ticket."


def test_overseas_recruiter_not_on_the_nea_list_is_flagged() -> None:
    keys = frozenset({verify.name_key("Licensed Partners Ltd")})
    ad = Ad(None, OVERSEAS, "Gulf Dreams Agency")
    assert _by_id(evaluate(ad, Lookups(), TODAY, keys))["overseas_recruiter"].result == "flag"


def test_licensed_agency_passes_whatever_the_spelling() -> None:
    keys = frozenset({verify.name_key("Licensed Partners Limited")})
    ad = Ad(None, OVERSEAS, "Tausi", agency="licensed partners ltd.")
    assert _by_id(evaluate(ad, Lookups(), TODAY, keys))["overseas_recruiter"].result == "pass"


def test_overseas_without_the_list_loaded_is_unknown() -> None:
    ad = Ad(None, OVERSEAS, "Gulf Dreams Agency")
    assert _by_id(evaluate(ad, Lookups(), TODAY, frozenset()))["overseas_recruiter"].result == (
        "unknown"
    )


def test_local_role_is_not_an_overseas_recruitment() -> None:
    ad = Ad(None, "Backend engineer, Nairobi office, hybrid.", "Tausi")
    assert _by_id(evaluate(ad, Lookups(), TODAY))["overseas_recruiter"].result == "pass"


def test_no_text_skips_the_text_checks() -> None:
    checks = _by_id(evaluate(Ad("https://tausi.co.ke/j", "  ", "Tausi"), OLD, TODAY))
    for id_ in ("fee_language", "personal_email", "whatsapp_only", "overseas_recruiter"):
        assert checks[id_].result == "skip"


# --- verdicts and the fixture --------------------------------------------


def test_verdict_rules() -> None:
    assert verdict(["pass", "pass"]) == "verified"
    assert verdict(["pass", "warn"]) == "unverified"
    assert verdict(["pass", "skip"]) == "unverified"
    assert verdict(["pass", "flag", "warn"]) == "flagged"
    assert verdict([]) == "unverified"


def test_same_input_same_checks() -> None:
    ad = Ad("https://tausi.co.ke/j", "Pay a registration fee", "Tausi")
    assert evaluate(ad, OLD, TODAY) == evaluate(ad, OLD, TODAY)


NEA = frozenset({verify.name_key("Licensed Partners Ltd")})
FIXTURE = [
    # (name, ad, lookups, expected verdict)
    ("real: company site, full text", Ad(
        "https://www.tausi.co.ke/careers/data-analyst",
        "Tausi Analytics is hiring a Data Analyst in Nairobi. Apply on our careers page. "
        "Questions: careers@tausi.co.ke. We never charge fees.", "Tausi Analytics"),
     OLD, "verified"),
    ("real: Greenhouse", Ad(
        "https://boards.greenhouse.io/mawingu/jobs/4410",
        "Mawingu is hiring a Site Reliability Engineer (remote, Kenya).", "Mawingu Networks"),
     Lookups(link_ok=True), "verified"),
    ("real: licensed agency abroad", Ad(
        "https://www.licensedpartners.co.ke/jobs/12",
        "Licensed Partners is recruiting nurses for a hospital in Qatar. Visa sponsored. "
        "Email jobs@licensedpartners.co.ke.", "Licensed Partners Ltd"),
     OLD, "verified"),
    ("real but link only", Ad("https://www.tausi.co.ke/careers/1", "", "Tausi"),
     OLD, "unverified"),
    ("scam: registration fee", Ad(
        "https://tausi-jobs-portal.com/apply",
        "Tausi is recruiting 50 data clerks. Pay a registration fee of KSh 1,000 via M-Pesa "
        "till 889900 to confirm your interview.", "Tausi Analytics"),
     Lookups(registered_on=TODAY - timedelta(days=12), link_ok=True), "flagged"),
    ("scam: WhatsApp only, Gmail", Ad(
        None, "Urgent: shop attendants needed in Westlands. WhatsApp 0712 345 678 or send CV "
        "to jobs.westlands@gmail.com", "Westlands Supermarket"),
     Lookups(), "unverified"),
    ("scam: unlicensed overseas agency", Ad(
        None, "Gulf Dreams Recruitment: housemaids and drivers wanted in Dubai. Free visa and "
        "air tickets. Medical fee Sh 6,500.", "Gulf Dreams Recruitment"),
     Lookups(), "flagged"),
    ("scam: overseas, no fee, unlicensed", Ad(
        "https://gulfdreams.site/jobs", "Caregivers needed in Saudi Arabia. Agency handles "
        "visa and work permits.", "Gulf Dreams Recruitment"),
     Lookups(registered_on=TODAY - timedelta(days=30), link_ok=True), "flagged"),
    ("scam: medical fee in Kiswahili", Ad(
        None, "Nafasi za kazi! Lipa ada ya matibabu kabla ya mahojiano.", "Kazi Bora"),
     Lookups(), "flagged"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "ad", "lookups", "expected"), FIXTURE, ids=[f[0] for f in FIXTURE]
)
def test_fixture_ads_get_the_expected_label(
    name: str, ad: Ad, lookups: Lookups, expected: str
) -> None:
    checks = evaluate(ad, lookups, TODAY, NEA)
    assert verdict(c.result for c in checks) == expected, [
        (c.id, c.result) for c in checks if c.result != "pass"
    ]
