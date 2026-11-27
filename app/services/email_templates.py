"""Plain-text and simple HTML emails. Every dynamic value is HTML-escaped."""

from dataclasses import dataclass
from html import escape

from app.config import Settings
from app.services.email import EmailMessage


@dataclass(frozen=True)
class Brand:
    name: str
    tagline: str
    base_url: str

    @classmethod
    def from_settings(cls, settings: Settings) -> Brand:
        return cls(settings.app_name, settings.app_tagline, settings.base_url.rstrip("/"))


def layout(brand: Brand, inner_html: str, footer_html: str = "") -> str:
    """The one HTML shell for every email. inner_html must already be escaped."""
    footer = f"{footer_html}<br>" if footer_html else ""
    return (
        '<!doctype html><html><body style="font-family:sans-serif;line-height:1.5;'
        'max-width:36rem">'
        f"{inner_html}"
        f'<p style="color:#666">{footer}{escape(brand.name)}: {escape(brand.tagline)}</p>'
        "</body></html>"
    )


def text_footer(brand: Brand) -> str:
    return f"-- \n{brand.name}: {brand.tagline}"


def _html(brand: Brand, paragraphs: list[str], link: tuple[str, str] | None = None) -> str:
    body = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    if link:
        label, url = link
        body += f'<p><a href="{escape(url, quote=True)}">{escape(label)}</a></p>'
        body += f"<p>Or paste this link into your browser:<br>{escape(url)}</p>"
    return layout(brand, body)


def _text(brand: Brand, paragraphs: list[str], link: tuple[str, str] | None = None) -> str:
    parts = list(paragraphs)
    if link:
        parts.append(f"{link[0]}: {link[1]}")
    parts.append(text_footer(brand))
    return "\n\n".join(parts)


def _message(
    brand: Brand,
    to: str,
    kind: str,
    subject: str,
    paragraphs: list[str],
    link: tuple[str, str] | None = None,
) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject=subject,
        text=_text(brand, paragraphs, link),
        html=_html(brand, paragraphs, link),
        kind=kind,
    )


def verify_email(brand: Brand, to: str, handle: str, token: str) -> EmailMessage:
    # The token rides in the URL fragment, which browsers never send to servers.
    url = f"{brand.base_url}/verify-email#token={token}"
    return _message(
        brand,
        to,
        "verify_email",
        f"Confirm your email for {brand.name}",
        [
            f"Hi {handle},",
            "Confirm this email address to turn on deadline reminders. "
            "The link works for 24 hours.",
            "If you didn't sign up, ignore this email.",
        ],
        ("Confirm my email", url),
    )


def already_registered(brand: Brand, to: str) -> EmailMessage:
    return _message(
        brand,
        to,
        "already_registered",
        f"You already have a {brand.name} account",
        [
            "Someone (hopefully you) tried to sign up with this email address, "
            "but it already has an account.",
            "If you forgot your password, you can reset it from the sign-in page. "
            "If this wasn't you, you can ignore this email.",
        ],
        ("Sign in", f"{brand.base_url}/login"),
    )


def password_reset(brand: Brand, to: str, token: str) -> EmailMessage:
    url = f"{brand.base_url}/reset-password#token={token}"
    return _message(
        brand,
        to,
        "password_reset",
        f"Reset your {brand.name} password",
        [
            "Use the link below to choose a new password. It works for 1 hour and only once.",
            "Resetting signs you out everywhere. "
            "If you didn't ask for this, ignore this email; your password stays the same.",
        ],
        ("Choose a new password", url),
    )


CHECKIN_REMINDER_KIND = "checkin_reminder"


def checkin_link(brand: Brand) -> str:
    return f"{brand.base_url}/dira/checkin"


def checkin_reminder(brand: Brand, to: str, handle: str) -> EmailMessage:
    """A link only: reminders never carry anything the user wrote."""
    return _message(
        brand,
        to,
        CHECKIN_REMINDER_KIND,
        f"Time for your career check-in: {brand.name}",
        [
            f"Hi {handle},",
            "Your Dira check-in is ready whenever you are. It takes a few minutes: where you "
            "want your career to go, and what to keep or change.",
            "You can change how often these come, or turn them off, in Settings.",
        ],
        ("Start my check-in", checkin_link(brand)),
    )
